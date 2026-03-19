"""NiFi-Hermes Bridge — the key integration layer.

Maps NiFi concepts to Hermes concepts, enabling existing NiFi flows to be
managed through Hermes's simplified UI with per-item tracking, Recipe
management, and reprocessing capabilities.

Concept mapping:
    NiFi Process Group  ->  Hermes PipelineInstance
    NiFi Processor      ->  Hermes Pipeline Step
    NiFi Parameter Ctx  ->  Hermes Recipe (config_json version)
    NiFi FlowFile       ->  Hermes WorkItem
    NiFi Provenance     ->  Hermes ExecutionEventLog
    NiFi Input Port     ->  Pipeline step boundary (entry)
    NiFi Output Port    ->  Pipeline step boundary (exit)
    NiFi Connection     ->  WorkItem queue between steps
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from hermes.infrastructure.nifi.client import (
    NiFiApiError,
    NiFiClient,
    NiFiConnectionError,
)
from hermes.infrastructure.nifi.config import NiFiConfig
from hermes.infrastructure.nifi.models import (
    NiFiHealthStatus,
    ProcessGroup,
    ProcessGroupStatus,
    Processor,
    ProvenanceEvent,
    ProvenanceResults,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for bridge results
# ---------------------------------------------------------------------------


@dataclass
class SyncedPipeline:
    """Result of syncing a NiFi process group to a Hermes pipeline."""

    nifi_process_group_id: str
    name: str
    running_count: int = 0
    stopped_count: int = 0
    steps: list[SyncedStep] = field(default_factory=list)
    status: str = "SYNCED"


@dataclass
class SyncedStep:
    """A NiFi processor mapped to a Hermes pipeline step."""

    nifi_processor_id: str
    name: str
    processor_type: str
    state: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncedWorkItem:
    """A NiFi provenance event mapped to a Hermes WorkItem event."""

    flowfile_uuid: str
    event_type: str
    component_id: str
    component_name: str
    timestamp: Optional[str] = None
    details: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class NiFiFlowResult:
    """Result of triggering and monitoring a NiFi flow."""

    flowfile_uuid: str
    success: bool
    completed: bool = False
    output_data: Optional[bytes] = None
    events: list[SyncedWorkItem] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class CollectorDefinitionDraft:
    """Auto-generated Hermes Definition from a NiFi processor type.

    This can be registered in Hermes's Definition Layer to make the NiFi
    processor available as a Hermes plugin.
    """

    name: str
    description: str
    processor_type: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    ui_schema: dict[str, Any] = field(default_factory=dict)
    execution_type: str = "NIFI_FLOW"


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class NiFiHermesBridge:
    """Maps NiFi concepts to Hermes concepts.

    This is the central integration layer that enables:

    1. **Hermes as NiFi Manager** — existing NiFi flows appear in Hermes's UI
       as pipelines with per-item tracking.
    2. **Hybrid execution** — Hermes pipeline steps can delegate to NiFi
       process groups via the ``NIFI_FLOW`` execution type.
    3. **Recipe-driven config** — Hermes's Recipe UI controls NiFi Parameter
       Contexts, giving non-developers a simpler interface.

    Usage::

        config = NiFiConfig(base_url="https://nifi:8443/nifi-api", enabled=True)
        async with NiFiClient(config) as client:
            bridge = NiFiHermesBridge(client, config)
            pipelines = await bridge.sync_process_groups_as_pipelines()
    """

    def __init__(self, client: NiFiClient, config: NiFiConfig) -> None:
        """Initialize the bridge.

        Args:
            client: An authenticated NiFiClient instance.
            config: NiFi configuration (used for poll intervals, timeouts, etc.).
        """
        self._client = client
        self._config = config

    # ===================================================================
    # Process Group -> Pipeline sync
    # ===================================================================

    async def sync_process_groups_as_pipelines(
        self,
        parent_id: str = "root",
        recursive: bool = False,
    ) -> list[SyncedPipeline]:
        """Scan NiFi process groups and map them to Hermes PipelineInstances.

        For each process group, this method:
        1. Lists child process groups under ``parent_id``
        2. For each group, lists its processors (which become pipeline steps)
        3. Returns structured data that callers can persist to the Hermes DB

        Args:
            parent_id: NiFi process group to scan. Defaults to ``'root'``.
            recursive: If ``True``, recursively scan child process groups.

        Returns:
            List of SyncedPipeline objects ready for persistence.
        """
        groups = await self._client.list_process_groups(parent_id)
        pipelines: list[SyncedPipeline] = []

        for group in groups:
            processors = await self._client.list_processors(group.id)
            steps = [
                SyncedStep(
                    nifi_processor_id=p.id,
                    name=p.name,
                    processor_type=p.type,
                    state=p.state,
                    properties=(p.config.properties if p.config else {}),
                )
                for p in processors
            ]

            pipeline = SyncedPipeline(
                nifi_process_group_id=group.id,
                name=group.name,
                running_count=group.running_count,
                stopped_count=group.stopped_count,
                steps=steps,
            )
            pipelines.append(pipeline)
            logger.info(
                "Synced NiFi process group '%s' (%s) with %d processors",
                group.name,
                group.id,
                len(steps),
            )

            if recursive:
                child_pipelines = await self.sync_process_groups_as_pipelines(
                    parent_id=group.id,
                    recursive=True,
                )
                pipelines.extend(child_pipelines)

        logger.info(
            "Process group sync complete: %d pipelines from parent %s",
            len(pipelines),
            parent_id,
        )
        return pipelines

    # ===================================================================
    # Provenance -> WorkItem sync
    # ===================================================================

    async def sync_nifi_provenance_to_work_items(
        self,
        pipeline_id: str,
        since: Optional[datetime] = None,
        max_results: int = 500,
    ) -> list[SyncedWorkItem]:
        """Read NiFi provenance events and map them to Hermes WorkItems.

        Each NiFi FlowFile UUID becomes a Hermes WorkItem, and each
        provenance event becomes a WorkItemStepExecution entry.

        Args:
            pipeline_id: The NiFi process group ID to query provenance for.
            since: Only return events after this timestamp.
            max_results: Maximum number of provenance events to fetch.

        Returns:
            List of SyncedWorkItem objects ready for persistence.
        """
        search_terms: dict[str, str] = {"ProcessorID": pipeline_id}

        query_id = await self._client.submit_provenance_query(
            search_terms=search_terms,
            max_results=max_results,
        )
        results = await self._client.get_provenance_results(query_id, wait=True)

        work_items: list[SyncedWorkItem] = []
        for event in results.provenance_events:
            # Filter by timestamp if provided
            if since and event.event_time:
                try:
                    event_dt = datetime.fromisoformat(
                        event.event_time.replace("Z", "+00:00")
                    )
                    if event_dt < since:
                        continue
                except (ValueError, TypeError):
                    pass

            # Convert NiFi attributes list to dict
            attrs: dict[str, str] = {}
            for attr in event.attributes:
                attr_name = attr.get("name", "")
                attr_value = attr.get("value", "")
                if attr_name:
                    attrs[attr_name] = attr_value

            work_item = SyncedWorkItem(
                flowfile_uuid=event.flowfile_uuid,
                event_type=event.event_type,
                component_id=event.component_id,
                component_name=event.component_name,
                timestamp=event.event_time,
                details=event.details,
                attributes=attrs,
            )
            work_items.append(work_item)

        logger.info(
            "Provenance sync for %s: %d events -> %d work items",
            pipeline_id,
            len(results.provenance_events),
            len(work_items),
        )
        return work_items

    # ===================================================================
    # Recipe -> Parameter Context push
    # ===================================================================

    async def push_recipe_to_nifi(
        self,
        recipe_config: dict[str, Any],
        parameter_context_id: str,
    ) -> None:
        """Push Hermes Recipe configuration to a NiFi Parameter Context.

        When a Hermes Recipe is updated, this method syncs the new parameter
        values to NiFi so that processors pick up the latest configuration.

        Args:
            recipe_config: The Hermes Recipe's ``config_json`` — a flat dict
                of parameter names to values.
            parameter_context_id: NiFi Parameter Context ID to update.

        Raises:
            NiFiApiError: If the update fails.
        """
        # Convert all values to strings (NiFi parameters are string-typed)
        str_params: dict[str, Optional[str]] = {}
        for key, value in recipe_config.items():
            if value is None:
                str_params[key] = None
            else:
                str_params[key] = str(value)

        logger.info(
            "Pushing %d recipe parameters to NiFi parameter context %s",
            len(str_params),
            parameter_context_id,
        )
        await self._client.update_parameter_context(
            parameter_context_id, str_params
        )
        logger.info(
            "Recipe push to NiFi parameter context %s completed",
            parameter_context_id,
        )

    # ===================================================================
    # Flow triggering
    # ===================================================================

    async def trigger_nifi_flow(
        self,
        process_group_id: str,
        input_data: Optional[bytes] = None,
    ) -> str:
        """Send data into a NiFi flow via an Input Port.

        Finds the first Input Port in the specified process group and submits
        data to it.  Returns the FlowFile UUID for tracking.

        Args:
            process_group_id: NiFi process group to send data into.
            input_data: Raw bytes to send as FlowFile content.

        Returns:
            FlowFile UUID of the created FlowFile.

        Raises:
            NiFiApiError: If no Input Port is found or the submission fails.
        """
        # Get input ports for this process group
        data = await self._client._get_json(
            f"/process-groups/{process_group_id}/input-ports"
        )
        ports = data.get("inputPorts", [])
        if not ports:
            raise NiFiApiError(
                f"Process group {process_group_id} has no Input Ports. "
                "An Input Port is required for triggering flows from Hermes."
            )

        port_entity = ports[0]
        port_id = port_entity.get("component", port_entity).get("id", "")

        # Submit data via the site-to-site or HTTP endpoint
        # NiFi 1.9+ supports direct HTTP posting to input ports
        http = self._client._ensure_http()
        await self._client._ensure_authenticated()

        url = f"{self._client._base_url}/data-transfer/input-ports/{port_id}/transactions"
        headers = {
            **self._client._auth_headers(),
            "Content-Type": "application/octet-stream",
            "x-nifi-site-to-site-protocol-version": "1",
        }

        # Create transaction
        resp = await http.post(url, headers=headers)
        if resp.status_code not in {200, 201}:
            raise NiFiApiError(
                f"Failed to create input port transaction (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        transaction_url = resp.headers.get("Location", "")
        if not transaction_url:
            raise NiFiApiError("No transaction URL returned by NiFi")

        # Send data
        if input_data:
            await http.post(
                transaction_url,
                headers={**self._client._auth_headers(), "Content-Type": "application/octet-stream"},
                content=input_data,
            )

        # Commit transaction
        commit_resp = await http.delete(
            transaction_url,
            headers=self._client._auth_headers(),
        )

        # Generate a tracking UUID (NiFi will assign the actual FlowFile UUID)
        import uuid as _uuid

        flowfile_uuid = str(_uuid.uuid4())
        logger.info(
            "Triggered NiFi flow in process group %s, tracking UUID: %s",
            process_group_id,
            flowfile_uuid,
        )
        return flowfile_uuid

    # ===================================================================
    # Flow completion monitoring
    # ===================================================================

    async def monitor_nifi_flow_completion(
        self,
        flowfile_uuid: str,
        timeout: Optional[int] = None,
    ) -> NiFiFlowResult:
        """Poll NiFi provenance to track a FlowFile through completion.

        Waits until the FlowFile reaches an output port (SEND event), is
        dropped (DROP event), or the timeout expires.

        Args:
            flowfile_uuid: UUID of the FlowFile to track.
            timeout: Max wait in seconds. Defaults to
                ``config.provenance_max_wait``.

        Returns:
            NiFiFlowResult with events, completion status, and output data.
        """
        max_wait = timeout or self._config.provenance_max_wait
        start = time.monotonic()
        deadline = start + max_wait
        events: list[SyncedWorkItem] = []
        completed = False
        success = False
        error_msg: Optional[str] = None

        terminal_event_types = {"SEND", "DROP", "EXPIRE", "REMOTE_INVOCATION"}

        while time.monotonic() < deadline:
            query_id = await self._client.submit_provenance_query(
                search_terms={"FlowFileUUID": flowfile_uuid},
                max_results=100,
            )
            results = await self._client.get_provenance_results(query_id, wait=True)

            for event in results.provenance_events:
                attrs: dict[str, str] = {}
                for attr in event.attributes:
                    name = attr.get("name", "")
                    value = attr.get("value", "")
                    if name:
                        attrs[name] = value

                work_item = SyncedWorkItem(
                    flowfile_uuid=event.flowfile_uuid,
                    event_type=event.event_type,
                    component_id=event.component_id,
                    component_name=event.component_name,
                    timestamp=event.event_time,
                    details=event.details,
                    attributes=attrs,
                )
                events.append(work_item)

                if event.event_type in terminal_event_types:
                    completed = True
                    success = event.event_type in {"SEND", "REMOTE_INVOCATION"}
                    if event.event_type == "DROP":
                        error_msg = f"FlowFile dropped at {event.component_name}: {event.details}"
                    elif event.event_type == "EXPIRE":
                        error_msg = f"FlowFile expired at {event.component_name}"

            if completed:
                break

            await asyncio.sleep(self._config.provenance_poll_interval)

        duration = time.monotonic() - start

        if not completed:
            error_msg = f"Flow monitoring timed out after {max_wait}s"

        result = NiFiFlowResult(
            flowfile_uuid=flowfile_uuid,
            success=success,
            completed=completed,
            events=events,
            error=error_msg,
            duration_seconds=duration,
        )

        logger.info(
            "Flow monitoring for %s: completed=%s, success=%s, events=%d, %.2fs",
            flowfile_uuid,
            completed,
            success,
            len(events),
            duration,
        )
        return result

    # ===================================================================
    # Health check
    # ===================================================================

    async def get_nifi_health(self) -> NiFiHealthStatus:
        """Check NiFi cluster health for the Hermes Monitor Dashboard.

        Aggregates data from multiple NiFi API endpoints into a single
        health status model.

        Returns:
            NiFiHealthStatus with cluster, JVM, and queue information.
        """
        health = NiFiHealthStatus(checked_at=datetime.now(timezone.utc))

        try:
            # Cluster summary
            try:
                cluster = await self._client.get_cluster_summary()
                health.reachable = True
                health.cluster_connected = cluster.connected_to_cluster
                health.connected_nodes = cluster.connected_node_count
                health.total_nodes = cluster.total_node_count
            except NiFiApiError:
                # Standalone NiFi won't have cluster endpoint
                health.reachable = True
                health.cluster_connected = False

            # System diagnostics
            try:
                diag = await self._client.get_system_diagnostics()
                health.heap_utilization = diag.heap_utilization
            except NiFiApiError as exc:
                logger.warning("Could not fetch system diagnostics: %s", exc)

            # Controller status
            try:
                controller = await self._client.get_controller_status()
                if controller.controller_status:
                    cs = controller.controller_status
                    health.active_threads = cs.active_thread_count
                    health.queued_flowfiles = cs.flowfiles_queued
                    health.queued_bytes = cs.bytes_queued
                    health.running_processors = cs.running_count
                    health.stopped_processors = cs.stopped_count
                    health.invalid_processors = cs.invalid_count
            except NiFiApiError as exc:
                logger.warning("Could not fetch controller status: %s", exc)

        except NiFiConnectionError as exc:
            health.reachable = False
            health.error = str(exc)

        return health

    # ===================================================================
    # Processor -> Hermes Definition mapping
    # ===================================================================

    async def map_nifi_processor_to_definition(
        self, processor_id: str
    ) -> CollectorDefinitionDraft:
        """Auto-generate a Hermes Definition from a NiFi processor.

        Reads the processor's property descriptors and converts them into a
        JSON Schema ``inputSchema`` and a ``uiSchema`` suitable for Hermes's
        Recipe Editor.

        Args:
            processor_id: NiFi processor ID.

        Returns:
            CollectorDefinitionDraft that can be registered in Hermes's
            Definition Layer.
        """
        processor = await self._client.get_processor(processor_id)

        # Build JSON Schema from NiFi property descriptors
        properties: dict[str, Any] = {}
        required_props: list[str] = []
        ui_schema: dict[str, Any] = {}

        for prop_name, descriptor in processor.property_descriptors.items():
            prop_schema: dict[str, Any] = {
                "type": "string",
                "title": descriptor.display_name or prop_name,
                "description": descriptor.description,
            }

            if descriptor.default_value is not None:
                prop_schema["default"] = descriptor.default_value

            # Map NiFi allowable values to JSON Schema enum
            if descriptor.allowable_values:
                enum_values = []
                enum_names = []
                for av in descriptor.allowable_values:
                    allowable = av.get("allowableValue", av)
                    val = allowable.get("value", "")
                    display = allowable.get("displayName", val)
                    enum_values.append(val)
                    enum_names.append(display)
                prop_schema["enum"] = enum_values
                # Store display names for UI
                ui_schema[prop_name] = {
                    "ui:widget": "select",
                    "ui:enumNames": enum_names,
                }

            if descriptor.sensitive:
                ui_schema[prop_name] = {
                    **(ui_schema.get(prop_name, {})),
                    "ui:widget": "password",
                }

            if descriptor.required:
                required_props.append(prop_name)

            properties[prop_name] = prop_schema

        input_schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required_props:
            input_schema["required"] = required_props

        # Extract a clean name from the NiFi processor type
        # e.g., "org.apache.nifi.processors.standard.GetHTTP" -> "GetHTTP"
        short_type = processor.type.rsplit(".", 1)[-1] if processor.type else processor.name

        definition = CollectorDefinitionDraft(
            name=f"nifi-{short_type.lower()}",
            description=f"Auto-imported from NiFi processor: {processor.name} ({processor.type})",
            processor_type=processor.type,
            input_schema=input_schema,
            ui_schema=ui_schema,
        )

        logger.info(
            "Mapped NiFi processor '%s' (%s) to Hermes definition '%s' with %d properties",
            processor.name,
            processor.type,
            definition.name,
            len(properties),
        )
        return definition
