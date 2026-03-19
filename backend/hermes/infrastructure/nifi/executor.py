"""NiFi Flow Executor.

Implements the same interface pattern as Hermes's ``PluginExecutor`` but
delegates execution to a NiFi process group.  This allows ``NIFI_FLOW``
to be used as a step execution type in any Hermes pipeline, seamlessly
mixing NiFi flows with native Hermes plugins.

Execution flow:
    1. Receive config + input_data from Hermes's Processing Orchestrator
    2. Resolve the target NiFi process group from config
    3. Push input data to NiFi via an Input Port
    4. Monitor provenance for the FlowFile through completion
    5. Retrieve output from Output Port (if applicable)
    6. Return result with NiFi provenance events as EventLog entries

Usage::

    executor = NiFiFlowExecutor(client, config)
    result = await executor.execute(
        config={"process_group_id": "abc-123", "timeout": 120},
        input_data=b'{"records": [...]}',
        context={"pipeline_id": "p1", "step_id": "s1"},
    )
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from hermes.infrastructure.nifi.bridge import NiFiHermesBridge
from hermes.infrastructure.nifi.client import NiFiApiError, NiFiClient
from hermes.infrastructure.nifi.config import NiFiConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result model (mirrors PluginResult from hermes.plugins.executor)
# ---------------------------------------------------------------------------


@dataclass
class NiFiExecutionLogEntry:
    """A log entry from NiFi flow execution, mapped from provenance events."""

    timestamp: float
    level: str
    message: str
    nifi_event_type: str = ""
    nifi_component_id: str = ""
    nifi_component_name: str = ""


@dataclass
class NiFiExecutionResult:
    """Result of a NiFi flow execution.

    Designed to be compatible with ``PluginResult`` from
    ``hermes.plugins.executor`` so the Processing Orchestrator can handle
    both uniformly.
    """

    success: bool
    outputs: list[Any] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    logs: list[NiFiExecutionLogEntry] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    duration_seconds: float = 0.0
    last_progress: float = 0.0

    # NiFi-specific
    flowfile_uuid: str | None = None
    provenance_event_count: int = 0


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class NiFiFlowExecutor:
    """Executes NiFi flows as Hermes pipeline steps.

    This class provides the same ``execute()`` contract as ``PluginExecutor``,
    making NiFi flows interchangeable with native Hermes plugins in pipeline
    definitions.

    Config keys (passed via the ``config`` dict):
        ``process_group_id`` (str, required):
            NiFi process group to execute.
        ``timeout`` (int, optional):
            Max seconds to wait for flow completion. Defaults to
            ``NiFiConfig.provenance_max_wait``.
        ``start_group`` (bool, optional):
            If ``True``, start the process group before sending data.
            Defaults to ``False``.
        ``stop_after`` (bool, optional):
            If ``True``, stop the process group after execution completes.
            Defaults to ``False``.
        ``content_type`` (str, optional):
            MIME type for the input data. Defaults to ``application/octet-stream``.
    """

    def __init__(self, client: NiFiClient, config: NiFiConfig) -> None:
        """Initialize the NiFi flow executor.

        Args:
            client: An authenticated NiFiClient instance.
            config: NiFi configuration.
        """
        self._client = client
        self._config = config
        self._bridge = NiFiHermesBridge(client, config)

    async def execute(
        self,
        config: dict[str, Any],
        input_data: Any = None,
        context: dict[str, Any] | None = None,
    ) -> NiFiExecutionResult:
        """Execute a NiFi flow and return the result.

        This method:
        1. Resolves the target process group from ``config``
        2. Optionally starts the process group
        3. Sends ``input_data`` to the process group's Input Port
        4. Monitors NiFi provenance until completion or timeout
        5. Optionally stops the process group
        6. Returns a result compatible with ``PluginResult``

        Args:
            config: Execution configuration. Must contain ``process_group_id``.
            input_data: Input data to send to the NiFi flow.  Can be ``bytes``,
                ``str``, or a JSON-serializable object.
            context: Execution context from Hermes (pipeline_id, step_id, etc.).

        Returns:
            NiFiExecutionResult with outputs, events, and status.
        """
        start_time = time.monotonic()
        result = NiFiExecutionResult(success=False)
        ctx = context or {}

        # Extract config
        process_group_id = config.get("process_group_id")
        if not process_group_id:
            result.errors.append({
                "code": "CONFIG_ERROR",
                "message": "Missing required config key 'process_group_id'",
            })
            return result

        timeout = config.get("timeout", self._config.provenance_max_wait)
        start_group = config.get("start_group", False)
        stop_after = config.get("stop_after", False)

        logger.info(
            "NiFi flow execution starting: pg=%s, pipeline=%s, step=%s",
            process_group_id,
            ctx.get("pipeline_id", "?"),
            ctx.get("step_id", "?"),
        )

        try:
            # Step 1: Optionally start the process group
            if start_group:
                result.logs.append(NiFiExecutionLogEntry(
                    timestamp=time.time(),
                    level="INFO",
                    message=f"Starting NiFi process group {process_group_id}",
                ))
                await self._client.start_process_group(process_group_id)

            # Step 2: Prepare input data
            raw_input = self._prepare_input(input_data)

            # Step 3: Trigger the NiFi flow
            result.logs.append(NiFiExecutionLogEntry(
                timestamp=time.time(),
                level="INFO",
                message=f"Triggering NiFi flow in process group {process_group_id}",
            ))

            flowfile_uuid = await self._bridge.trigger_nifi_flow(
                process_group_id=process_group_id,
                input_data=raw_input,
            )
            result.flowfile_uuid = flowfile_uuid

            # Step 4: Monitor for completion
            result.logs.append(NiFiExecutionLogEntry(
                timestamp=time.time(),
                level="INFO",
                message=f"Monitoring FlowFile {flowfile_uuid} (timeout={timeout}s)",
            ))

            flow_result = await self._bridge.monitor_nifi_flow_completion(
                flowfile_uuid=flowfile_uuid,
                timeout=timeout,
            )

            # Step 5: Map flow result to execution result
            result.success = flow_result.success
            result.provenance_event_count = len(flow_result.events)

            if flow_result.output_data:
                result.outputs.append(flow_result.output_data)

            if flow_result.error:
                result.errors.append({
                    "code": "NIFI_FLOW_ERROR",
                    "message": flow_result.error,
                })

            # Map provenance events to log entries
            for event in flow_result.events:
                result.logs.append(NiFiExecutionLogEntry(
                    timestamp=time.time(),
                    level="INFO",
                    message=f"[{event.event_type}] {event.component_name}: {event.details}",
                    nifi_event_type=event.event_type,
                    nifi_component_id=event.component_id,
                    nifi_component_name=event.component_name,
                ))

            result.summary = {
                "flowfile_uuid": flowfile_uuid,
                "completed": flow_result.completed,
                "provenance_events": len(flow_result.events),
                "process_group_id": process_group_id,
            }

        except NiFiApiError as exc:
            result.errors.append({
                "code": "NIFI_API_ERROR",
                "message": str(exc),
            })
            logger.error("NiFi flow execution failed: %s", exc)

        except Exception as exc:
            result.errors.append({
                "code": "UNEXPECTED_ERROR",
                "message": f"Unexpected error during NiFi flow execution: {exc}",
            })
            logger.exception("Unexpected error in NiFi flow executor")

        finally:
            # Step 6: Optionally stop the process group
            if stop_after and process_group_id:
                try:
                    await self._client.stop_process_group(process_group_id)
                    result.logs.append(NiFiExecutionLogEntry(
                        timestamp=time.time(),
                        level="INFO",
                        message=f"Stopped NiFi process group {process_group_id}",
                    ))
                except NiFiApiError as exc:
                    logger.warning(
                        "Failed to stop process group %s after execution: %s",
                        process_group_id,
                        exc,
                    )

        result.duration_seconds = time.monotonic() - start_time
        result.exit_code = 0 if result.success else 1

        logger.info(
            "NiFi flow execution completed: pg=%s, success=%s, events=%d, %.2fs",
            process_group_id,
            result.success,
            result.provenance_event_count,
            result.duration_seconds,
        )

        return result

    @staticmethod
    def _prepare_input(input_data: Any) -> bytes | None:
        """Convert input data to bytes for sending to NiFi.

        Args:
            input_data: Can be ``bytes``, ``str``, or a JSON-serializable object.

        Returns:
            Raw bytes, or ``None`` if no input.
        """
        if input_data is None:
            return None
        if isinstance(input_data, bytes):
            return input_data
        if isinstance(input_data, str):
            return input_data.encode("utf-8")
        # Assume JSON-serializable
        return json.dumps(input_data, ensure_ascii=False).encode("utf-8")
