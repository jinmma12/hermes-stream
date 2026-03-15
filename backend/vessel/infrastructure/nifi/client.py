"""NiFi REST API Client.

Async HTTP client for Apache NiFi's REST API (1.9.x+, forward-compatible
with 2.x where possible).  Uses ``httpx.AsyncClient`` for all communication.

Features:
- Token-based authentication with automatic refresh
- NiFi revision (optimistic locking) handling on mutations
- Configurable retry logic for transient errors
- Structured logging of every API call
- Rate-limit awareness via ``Retry-After`` header

Usage::

    from vessel.infrastructure.nifi.client import NiFiClient
    from vessel.infrastructure.nifi.config import NiFiConfig

    config = NiFiConfig(base_url="https://nifi:8443/nifi-api", username="admin", password="***")
    async with NiFiClient(config) as client:
        groups = await client.list_process_groups()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import httpx

from vessel.infrastructure.nifi.config import NiFiConfig
from vessel.infrastructure.nifi.models import (
    ClusterSummary,
    Connection,
    ControllerStatus,
    FlowFileSummary,
    NiFiRevision,
    Parameter,
    ParameterContext,
    Position,
    ProcessGroup,
    ProcessGroupStatus,
    Processor,
    ProcessorStatus,
    ProvenanceEvent,
    ProvenanceResults,
    QueueSize,
    SystemDiagnostics,
    Template,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NiFiApiError(Exception):
    """Base exception for NiFi API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class NiFiAuthError(NiFiApiError):
    """Authentication or authorization failure."""


class NiFiConflictError(NiFiApiError):
    """Optimistic-lock conflict (HTTP 409)."""


class NiFiNotFoundError(NiFiApiError):
    """Requested resource not found (HTTP 404)."""


class NiFiConnectionError(NiFiApiError):
    """Cannot reach the NiFi instance."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NiFiClient:
    """Async REST API client for Apache NiFi.

    Can be used as an async context manager::

        async with NiFiClient(config) as client:
            ...

    Or managed manually::

        client = NiFiClient(config)
        await client.connect()
        ...
        await client.close()
    """

    # HTTP methods that are safe to retry on transient errors
    _RETRYABLE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    _RETRYABLE_STATUS_CODES = frozenset({502, 503, 504, 429})

    def __init__(self, config: NiFiConfig) -> None:
        """Initialize the NiFi client.

        Args:
            config: NiFi connection configuration.
        """
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._token: Optional[str] = config.token
        self._token_expiry: float = 0.0
        self._client_id: str = str(uuid.uuid4())
        self._http: Optional[httpx.AsyncClient] = None

    # -- Lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        """Create the underlying HTTP client and authenticate if credentials
        are provided."""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.request_timeout),
            verify=True,
            follow_redirects=True,
        )
        if self._token is None and self._config.username and self._config.password:
            await self.login(self._config.username, self._config.password)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "NiFiClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- Authentication ------------------------------------------------------

    async def login(self, username: str, password: str) -> str:
        """Authenticate against NiFi and obtain an access token.

        Args:
            username: NiFi username.
            password: NiFi password.

        Returns:
            The access token string.

        Raises:
            NiFiAuthError: If authentication fails.
        """
        url = f"{self._base_url}/access/token"
        http = self._ensure_http()

        try:
            resp = await http.post(
                url,
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.ConnectError as exc:
            raise NiFiConnectionError(f"Cannot reach NiFi at {self._base_url}: {exc}")

        if resp.status_code == 201:
            self._token = resp.text.strip()
            self._token_expiry = time.monotonic() + self._config.token_refresh_interval
            logger.info("NiFi authentication successful (token expires in %ds)", self._config.token_refresh_interval)
            return self._token
        else:
            raise NiFiAuthError(
                f"NiFi login failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                response_body=resp.text,
            )

    async def _ensure_authenticated(self) -> None:
        """Refresh the auth token if it is expired or about to expire."""
        if self._token is None:
            return  # anonymous mode
        if time.monotonic() >= self._token_expiry:
            if self._config.username and self._config.password:
                logger.info("NiFi token expired, refreshing...")
                await self.login(self._config.username, self._config.password)
            else:
                logger.warning("NiFi token expired but no credentials configured for refresh")

    # -- Low-level HTTP helpers ----------------------------------------------

    def _ensure_http(self) -> httpx.AsyncClient:
        """Return the HTTP client, raising if not connected."""
        if self._http is None:
            raise RuntimeError(
                "NiFiClient is not connected. Call connect() or use as async context manager."
            )
        return self._http

    def _auth_headers(self) -> dict[str, str]:
        """Return authorization headers if a token is available."""
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        expected_status: Optional[set[int]] = None,
    ) -> httpx.Response:
        """Execute an HTTP request against the NiFi API with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API path relative to base_url (e.g., ``/process-groups/root``).
            json: JSON body (mutually exclusive with ``data``).
            data: Form-encoded body.
            params: Query parameters.
            headers: Additional headers.
            expected_status: Set of acceptable HTTP status codes.
                Defaults to ``{200, 201}``.

        Returns:
            The httpx.Response.

        Raises:
            NiFiApiError: On unexpected status codes.
            NiFiAuthError: On 401/403.
            NiFiConflictError: On 409 (revision conflict).
            NiFiNotFoundError: On 404.
            NiFiConnectionError: On connection failure.
        """
        await self._ensure_authenticated()
        http = self._ensure_http()

        url = f"{self._base_url}{path}"
        merged_headers = {**self._auth_headers(), **(headers or {})}
        expected = expected_status or {200, 201}

        last_exc: Optional[Exception] = None
        attempts = 1 + (self._config.max_retries if method.upper() in self._RETRYABLE_METHODS else 0)

        for attempt in range(1, attempts + 1):
            try:
                logger.debug(
                    "NiFi API %s %s (attempt %d/%d)",
                    method, path, attempt, attempts,
                )
                resp = await http.request(
                    method,
                    url,
                    json=json,
                    data=data,
                    params=params,
                    headers=merged_headers,
                )
            except httpx.ConnectError as exc:
                last_exc = NiFiConnectionError(
                    f"Cannot reach NiFi at {url}: {exc}"
                )
                if attempt < attempts:
                    await asyncio.sleep(min(2 ** attempt, 10))
                continue
            except httpx.TimeoutException as exc:
                last_exc = NiFiApiError(f"Request timed out: {exc}")
                if attempt < attempts:
                    await asyncio.sleep(min(2 ** attempt, 10))
                continue

            # Rate limiting
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "5"))
                logger.warning("NiFi rate limit hit, waiting %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue

            # Retryable server errors
            if resp.status_code in self._RETRYABLE_STATUS_CODES and attempt < attempts:
                await asyncio.sleep(min(2 ** attempt, 10))
                continue

            # Map error status codes to specific exceptions
            if resp.status_code in {401, 403}:
                raise NiFiAuthError(
                    f"NiFi auth error on {method} {path} (HTTP {resp.status_code})",
                    status_code=resp.status_code,
                    response_body=resp.text,
                )
            if resp.status_code == 404:
                raise NiFiNotFoundError(
                    f"NiFi resource not found: {method} {path}",
                    status_code=404,
                    response_body=resp.text,
                )
            if resp.status_code == 409:
                raise NiFiConflictError(
                    f"NiFi revision conflict on {method} {path}. "
                    "Another client may have modified this resource.",
                    status_code=409,
                    response_body=resp.text,
                )

            if resp.status_code not in expected:
                raise NiFiApiError(
                    f"Unexpected NiFi response: {method} {path} returned {resp.status_code}",
                    status_code=resp.status_code,
                    response_body=resp.text,
                )

            return resp

        # All attempts exhausted
        if last_exc is not None:
            raise last_exc
        raise NiFiApiError(f"All {attempts} attempts failed for {method} {path}")

    async def _get_json(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """GET and return parsed JSON."""
        resp = await self._request("GET", path, **kwargs)
        return resp.json()  # type: ignore[no-any-return]

    # -- Revision helpers ----------------------------------------------------

    def _make_revision(self, version: int = 0) -> dict[str, Any]:
        """Build a NiFi revision dict for mutation requests."""
        return {"version": version, "clientId": self._client_id}

    @staticmethod
    def _extract_revision(entity: dict[str, Any]) -> NiFiRevision:
        """Extract the revision from a NiFi entity response."""
        rev = entity.get("revision", {})
        return NiFiRevision(version=rev.get("version", 0), client_id=rev.get("clientId"))

    # ===================================================================
    # Process Groups
    # ===================================================================

    async def list_process_groups(
        self, parent_id: str = "root"
    ) -> list[ProcessGroup]:
        """List child process groups under a parent.

        Args:
            parent_id: Parent process group ID, or ``'root'`` for the root group.

        Returns:
            List of ProcessGroup models.
        """
        data = await self._get_json(f"/process-groups/{parent_id}/process-groups")
        groups: list[ProcessGroup] = []
        for entity in data.get("processGroups", []):
            component = entity.get("component", entity)
            component["revision"] = entity.get("revision")
            groups.append(ProcessGroup.model_validate(component))
        return groups

    async def get_process_group(self, pg_id: str) -> ProcessGroup:
        """Get a single process group by ID.

        Args:
            pg_id: Process group ID.

        Returns:
            ProcessGroup model.

        Raises:
            NiFiNotFoundError: If the process group does not exist.
        """
        data = await self._get_json(f"/process-groups/{pg_id}")
        component = data.get("component", data)
        component["revision"] = data.get("revision")
        return ProcessGroup.model_validate(component)

    async def get_process_group_status(self, pg_id: str) -> ProcessGroupStatus:
        """Get status/throughput for a process group.

        Args:
            pg_id: Process group ID.

        Returns:
            ProcessGroupStatus with aggregate snapshot.
        """
        data = await self._get_json(f"/flow/process-groups/{pg_id}/status")
        status_data = data.get("processGroupStatus", data)
        return ProcessGroupStatus.model_validate(status_data)

    async def start_process_group(self, pg_id: str) -> None:
        """Start all processors in a process group.

        Args:
            pg_id: Process group ID.
        """
        await self._request(
            "PUT",
            f"/flow/process-groups/{pg_id}",
            json={
                "id": pg_id,
                "state": "RUNNING",
            },
        )
        logger.info("Started NiFi process group %s", pg_id)

    async def stop_process_group(self, pg_id: str) -> None:
        """Stop all processors in a process group.

        Args:
            pg_id: Process group ID.
        """
        await self._request(
            "PUT",
            f"/flow/process-groups/{pg_id}",
            json={
                "id": pg_id,
                "state": "STOPPED",
            },
        )
        logger.info("Stopped NiFi process group %s", pg_id)

    async def create_process_group(
        self,
        parent_id: str,
        name: str,
        position: Optional[Position] = None,
    ) -> ProcessGroup:
        """Create a new process group.

        Args:
            parent_id: Parent process group ID.
            name: Name of the new group.
            position: Canvas position. Defaults to (0, 0).

        Returns:
            The created ProcessGroup.
        """
        pos = position or Position(x=0, y=0)
        resp = await self._request(
            "POST",
            f"/process-groups/{parent_id}/process-groups",
            json={
                "revision": self._make_revision(),
                "component": {
                    "name": name,
                    "position": {"x": pos.x, "y": pos.y},
                },
            },
        )
        data = resp.json()
        component = data.get("component", data)
        component["revision"] = data.get("revision")
        return ProcessGroup.model_validate(component)

    # ===================================================================
    # Processors
    # ===================================================================

    async def list_processors(self, pg_id: str) -> list[Processor]:
        """List all processors in a process group.

        Args:
            pg_id: Process group ID.

        Returns:
            List of Processor models.
        """
        data = await self._get_json(f"/process-groups/{pg_id}/processors")
        processors: list[Processor] = []
        for entity in data.get("processors", []):
            component = entity.get("component", entity)
            component["revision"] = entity.get("revision")
            processors.append(Processor.model_validate(component))
        return processors

    async def get_processor(self, processor_id: str) -> Processor:
        """Get a single processor by ID.

        Args:
            processor_id: Processor ID.

        Returns:
            Processor model.
        """
        data = await self._get_json(f"/processors/{processor_id}")
        component = data.get("component", data)
        component["revision"] = data.get("revision")
        return Processor.model_validate(component)

    async def update_processor_properties(
        self, processor_id: str, properties: dict[str, Any]
    ) -> Processor:
        """Update processor properties.

        The processor must be STOPPED before properties can be updated.

        Args:
            processor_id: Processor ID.
            properties: Dict of property name to value.

        Returns:
            Updated Processor model.

        Raises:
            NiFiConflictError: If the processor was modified concurrently.
        """
        # Fetch current state to get revision
        current = await self.get_processor(processor_id)
        revision = current.revision or NiFiRevision(version=0)

        resp = await self._request(
            "PUT",
            f"/processors/{processor_id}",
            json={
                "revision": {
                    "version": revision.version,
                    "clientId": self._client_id,
                },
                "component": {
                    "id": processor_id,
                    "config": {
                        "properties": properties,
                    },
                },
            },
        )
        data = resp.json()
        component = data.get("component", data)
        component["revision"] = data.get("revision")
        return Processor.model_validate(component)

    async def start_processor(self, processor_id: str) -> None:
        """Start a single processor.

        Args:
            processor_id: Processor ID.
        """
        current = await self.get_processor(processor_id)
        revision = current.revision or NiFiRevision(version=0)

        await self._request(
            "PUT",
            f"/processors/{processor_id}/run-status",
            json={
                "revision": {
                    "version": revision.version,
                    "clientId": self._client_id,
                },
                "state": "RUNNING",
            },
        )
        logger.info("Started NiFi processor %s", processor_id)

    async def stop_processor(self, processor_id: str) -> None:
        """Stop a single processor.

        Args:
            processor_id: Processor ID.
        """
        current = await self.get_processor(processor_id)
        revision = current.revision or NiFiRevision(version=0)

        await self._request(
            "PUT",
            f"/processors/{processor_id}/run-status",
            json={
                "revision": {
                    "version": revision.version,
                    "clientId": self._client_id,
                },
                "state": "STOPPED",
            },
        )
        logger.info("Stopped NiFi processor %s", processor_id)

    async def get_processor_status(self, processor_id: str) -> ProcessorStatus:
        """Get status/statistics for a processor.

        Args:
            processor_id: Processor ID.

        Returns:
            ProcessorStatus model.
        """
        data = await self._get_json(f"/processors/{processor_id}/status")
        status_data = data.get("processorStatus", data)
        return ProcessorStatus.model_validate(status_data)

    # ===================================================================
    # Connections & Queues
    # ===================================================================

    async def list_connections(self, pg_id: str) -> list[Connection]:
        """List all connections in a process group.

        Args:
            pg_id: Process group ID.

        Returns:
            List of Connection models.
        """
        data = await self._get_json(f"/process-groups/{pg_id}/connections")
        connections: list[Connection] = []
        for entity in data.get("connections", []):
            component = entity.get("component", entity)
            component["revision"] = entity.get("revision")
            component["status"] = entity.get("status", {}).get("aggregateSnapshot")
            connections.append(Connection.model_validate(component))
        return connections

    async def get_queue_size(self, connection_id: str) -> QueueSize:
        """Get the queue size for a connection.

        Args:
            connection_id: Connection ID.

        Returns:
            QueueSize with object_count and byte_count.
        """
        data = await self._get_json(f"/connections/{connection_id}/status")
        snapshot = (
            data.get("connectionStatus", {})
            .get("aggregateSnapshot", {})
        )
        return QueueSize(
            objectCount=snapshot.get("flowFilesQueued", 0),
            byteCount=snapshot.get("bytesQueued", 0),
        )

    async def empty_queue(self, connection_id: str) -> None:
        """Empty (drop) all FlowFiles from a connection queue.

        This is a destructive operation.  NiFi performs it asynchronously; this
        method submits the drop request and polls until complete.

        Args:
            connection_id: Connection ID.
        """
        # Submit drop request
        resp = await self._request(
            "POST",
            f"/flowfile-queues/{connection_id}/drop-requests",
        )
        drop_data = resp.json()
        drop_id = drop_data.get("dropRequest", {}).get("id", "")

        # Poll until complete
        for _ in range(60):  # up to 60 seconds
            status_resp = await self._get_json(
                f"/flowfile-queues/{connection_id}/drop-requests/{drop_id}"
            )
            dr = status_resp.get("dropRequest", {})
            if dr.get("finished", False):
                logger.info(
                    "Queue emptied for connection %s: dropped %d FlowFiles",
                    connection_id,
                    dr.get("droppedCount", 0),
                )
                # Clean up the drop request
                await self._request(
                    "DELETE",
                    f"/flowfile-queues/{connection_id}/drop-requests/{drop_id}",
                )
                return
            await asyncio.sleep(1.0)

        logger.warning("Queue drop for connection %s did not complete within timeout", connection_id)

    # ===================================================================
    # Data Provenance
    # ===================================================================

    async def submit_provenance_query(
        self,
        search_terms: Optional[dict[str, str]] = None,
        max_results: int = 100,
    ) -> str:
        """Submit a provenance query.

        Args:
            search_terms: Dict of search field to value.  Common fields:
                ``FlowFileUUID``, ``ProcessorID``, ``Relationship``.
            max_results: Maximum number of results to return.

        Returns:
            The provenance query ID for polling with
            :meth:`get_provenance_results`.
        """
        query: dict[str, Any] = {
            "provenance": {
                "request": {
                    "maxResults": max_results,
                    "summarize": False,
                    "searchTerms": {},
                },
            }
        }
        if search_terms:
            formatted: dict[str, dict[str, str]] = {}
            for key, value in search_terms.items():
                formatted[key] = {"value": value}
            query["provenance"]["request"]["searchTerms"] = formatted

        resp = await self._request("POST", "/provenance", json=query)
        data = resp.json()
        query_id: str = data.get("provenance", {}).get("id", "")
        logger.debug("Submitted provenance query %s", query_id)
        return query_id

    async def get_provenance_results(
        self,
        query_id: str,
        wait: bool = True,
    ) -> ProvenanceResults:
        """Get results of a provenance query.

        Args:
            query_id: The query ID returned by :meth:`submit_provenance_query`.
            wait: If ``True``, poll until the query is finished or times out.

        Returns:
            ProvenanceResults model.
        """
        deadline = time.monotonic() + self._config.provenance_max_wait

        while True:
            data = await self._get_json(f"/provenance/{query_id}")
            prov = data.get("provenance", {})
            results_data = prov.get("results", {})
            results = ProvenanceResults.model_validate(results_data)

            if not wait or results.finished or results.percentage_completed >= 100:
                # Clean up the query
                try:
                    await self._request("DELETE", f"/provenance/{query_id}")
                except NiFiApiError:
                    pass  # best-effort cleanup
                return results

            if time.monotonic() >= deadline:
                logger.warning("Provenance query %s timed out", query_id)
                try:
                    await self._request("DELETE", f"/provenance/{query_id}")
                except NiFiApiError:
                    pass
                return results

            await asyncio.sleep(self._config.provenance_poll_interval)

    async def get_provenance_event(self, event_id: str) -> ProvenanceEvent:
        """Get a single provenance event by ID.

        Args:
            event_id: The provenance event ID.

        Returns:
            ProvenanceEvent model.
        """
        data = await self._get_json(f"/provenance-events/{event_id}")
        event_data = data.get("provenanceEvent", data)
        return ProvenanceEvent.model_validate(event_data)

    # ===================================================================
    # FlowFile Content
    # ===================================================================

    async def get_flowfile_content(
        self, connection_id: str, flowfile_uuid: str
    ) -> bytes:
        """Download the content of a FlowFile in a connection queue.

        Args:
            connection_id: Connection ID containing the FlowFile.
            flowfile_uuid: UUID of the FlowFile.

        Returns:
            Raw content bytes.
        """
        resp = await self._request(
            "GET",
            f"/flowfile-queues/{connection_id}/flowfiles/{flowfile_uuid}/content",
            expected_status={200},
        )
        return resp.content

    async def list_flowfiles_in_queue(
        self, connection_id: str
    ) -> list[FlowFileSummary]:
        """List FlowFiles currently sitting in a connection queue.

        Args:
            connection_id: Connection ID.

        Returns:
            List of FlowFileSummary models.
        """
        # Submit listing request
        resp = await self._request(
            "POST",
            f"/flowfile-queues/{connection_id}/listing-requests",
        )
        listing_data = resp.json()
        listing_id = listing_data.get("listingRequest", {}).get("id", "")

        # Poll until complete
        flowfiles: list[FlowFileSummary] = []
        deadline = time.monotonic() + 30.0

        while time.monotonic() < deadline:
            status_data = await self._get_json(
                f"/flowfile-queues/{connection_id}/listing-requests/{listing_id}"
            )
            lr = status_data.get("listingRequest", {})
            if lr.get("finished", False):
                for ff in lr.get("flowFileSummaries", []):
                    flowfiles.append(FlowFileSummary.model_validate(ff))
                # Clean up
                try:
                    await self._request(
                        "DELETE",
                        f"/flowfile-queues/{connection_id}/listing-requests/{listing_id}",
                    )
                except NiFiApiError:
                    pass
                return flowfiles
            await asyncio.sleep(0.5)

        logger.warning("FlowFile listing for connection %s timed out", connection_id)
        return flowfiles

    # ===================================================================
    # Templates (NiFi 1.x)
    # ===================================================================

    async def list_templates(self) -> list[Template]:
        """List all templates available on the NiFi instance.

        Returns:
            List of Template models.
        """
        data = await self._get_json("/resources")
        # Templates endpoint
        data = await self._get_json("/flow/templates")
        templates: list[Template] = []
        for entity in data.get("templates", []):
            tmpl_data = entity.get("template", entity)
            templates.append(Template.model_validate(tmpl_data))
        return templates

    async def instantiate_template(
        self,
        pg_id: str,
        template_id: str,
        position: Optional[Position] = None,
    ) -> ProcessGroup:
        """Instantiate a template into a process group.

        Args:
            pg_id: Target process group ID.
            template_id: Template ID.
            position: Canvas position for the instantiated flow.

        Returns:
            The resulting ProcessGroup (NiFi returns the created flow snippet).
        """
        pos = position or Position(x=0, y=0)
        resp = await self._request(
            "POST",
            f"/process-groups/{pg_id}/template-instance",
            json={
                "templateId": template_id,
                "originX": pos.x,
                "originY": pos.y,
            },
        )
        data = resp.json()
        # The response contains a flow snippet; return the parent PG
        return await self.get_process_group(pg_id)

    async def upload_template(
        self, pg_id: str, template_xml: bytes
    ) -> Template:
        """Upload a template XML to a process group.

        Args:
            pg_id: Target process group ID.
            template_xml: Raw XML bytes of the template.

        Returns:
            The created Template.
        """
        http = self._ensure_http()
        await self._ensure_authenticated()

        url = f"{self._base_url}/process-groups/{pg_id}/templates/upload"
        resp = await http.post(
            url,
            headers=self._auth_headers(),
            files={"template": ("template.xml", template_xml, "application/xml")},
        )
        if resp.status_code not in {200, 201}:
            raise NiFiApiError(
                f"Template upload failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        data = resp.json()
        tmpl_data = data.get("template", data)
        return Template.model_validate(tmpl_data)

    # ===================================================================
    # Parameter Contexts (NiFi 1.10+)
    # ===================================================================

    async def list_parameter_contexts(self) -> list[ParameterContext]:
        """List all parameter contexts.

        Returns:
            List of ParameterContext models.
        """
        data = await self._get_json("/flow/parameter-contexts")
        contexts: list[ParameterContext] = []
        for entity in data.get("parameterContexts", []):
            component = entity.get("component", entity)
            component["revision"] = entity.get("revision")
            contexts.append(ParameterContext.model_validate(component))
        return contexts

    async def get_parameter_context(self, pc_id: str) -> ParameterContext:
        """Get a single parameter context by ID.

        Args:
            pc_id: Parameter context ID.

        Returns:
            ParameterContext model.
        """
        data = await self._get_json(f"/parameter-contexts/{pc_id}")
        component = data.get("component", data)
        component["revision"] = data.get("revision")
        return ParameterContext.model_validate(component)

    async def update_parameter_context(
        self, pc_id: str, parameters: dict[str, Optional[str]]
    ) -> ParameterContext:
        """Update parameters in a parameter context.

        This submits an update request and polls until NiFi has applied the
        changes (NiFi must stop and restart affected processors).

        Args:
            pc_id: Parameter context ID.
            parameters: Dict of parameter name to value.  Use ``None`` as
                value to remove a parameter.

        Returns:
            Updated ParameterContext.

        Raises:
            NiFiConflictError: On revision conflict.
            NiFiApiError: If the update fails or times out.
        """
        current = await self.get_parameter_context(pc_id)
        revision = current.revision or NiFiRevision(version=0)

        param_list: list[dict[str, Any]] = []
        for name, value in parameters.items():
            param_list.append({
                "parameter": {
                    "name": name,
                    "value": value,
                    "sensitive": False,
                },
            })

        resp = await self._request(
            "POST",
            f"/parameter-contexts/{pc_id}/update-requests",
            json={
                "revision": {
                    "version": revision.version,
                    "clientId": self._client_id,
                },
                "id": pc_id,
                "component": {
                    "id": pc_id,
                    "parameters": param_list,
                },
            },
        )
        data = resp.json()
        request_id = data.get("request", {}).get("requestId", data.get("id", ""))

        # Poll until update completes
        deadline = time.monotonic() + self._config.provenance_max_wait
        while time.monotonic() < deadline:
            status_data = await self._get_json(
                f"/parameter-contexts/{pc_id}/update-requests/{request_id}"
            )
            req = status_data.get("request", status_data)
            if req.get("complete", False):
                # Clean up
                try:
                    await self._request(
                        "DELETE",
                        f"/parameter-contexts/{pc_id}/update-requests/{request_id}",
                    )
                except NiFiApiError:
                    pass
                failure = req.get("failureReason")
                if failure:
                    raise NiFiApiError(f"Parameter context update failed: {failure}")
                return await self.get_parameter_context(pc_id)
            await asyncio.sleep(1.0)

        raise NiFiApiError(
            f"Parameter context update for {pc_id} timed out after "
            f"{self._config.provenance_max_wait}s"
        )

    # ===================================================================
    # System / Cluster
    # ===================================================================

    async def get_system_diagnostics(self) -> SystemDiagnostics:
        """Get NiFi system diagnostics (JVM, disk, threads).

        Returns:
            SystemDiagnostics model.
        """
        data = await self._get_json("/system-diagnostics")
        snapshot = data.get("systemDiagnostics", {}).get("aggregateSnapshot", {})
        return SystemDiagnostics.model_validate(snapshot)

    async def get_cluster_summary(self) -> ClusterSummary:
        """Get NiFi cluster summary.

        Returns:
            ClusterSummary model.  For standalone instances, ``clustered``
            will be ``False``.
        """
        data = await self._get_json("/controller/cluster/summary", expected_status={200, 404})
        summary_data = data.get("clusterSummary", data)
        return ClusterSummary.model_validate(summary_data)

    async def get_controller_status(self) -> ControllerStatus:
        """Get NiFi controller status (aggregate counts and queue sizes).

        Returns:
            ControllerStatus model.
        """
        data = await self._get_json("/flow/status")
        return ControllerStatus.model_validate(data)
