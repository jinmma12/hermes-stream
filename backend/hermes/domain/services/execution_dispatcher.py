"""Execution dispatcher - routes step execution to the appropriate backend."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from hermes.infrastructure.nifi.config import NiFiConfig

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of dispatching a step execution."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    logs: list[dict[str, Any]] = field(default_factory=list)


class ExecutionDispatcher:
    """Dispatches execution to the appropriate backend based on execution_type.

    Supported execution types:
    - PLUGIN: Hermes plugin protocol (subprocess with stdin/stdout JSON)
    - SCRIPT: Arbitrary script execution
    - HTTP: REST API call
    - NIFI_FLOW: Trigger NiFi process group
    """

    def __init__(self, nifi_config: NiFiConfig | None = None) -> None:
        self.nifi_config = nifi_config or NiFiConfig()

    async def dispatch(
        self,
        execution_type: str,
        execution_ref: str | None,
        config: dict[str, Any],
        input_data: Any = None,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Dispatch execution to the appropriate handler.

        Args:
            execution_type: One of PLUGIN, SCRIPT, HTTP, NIFI_FLOW.
            execution_ref: Reference to the executable (plugin name, script path, URL, etc.).
            config: Resolved configuration for the step.
            input_data: Output from the previous step (if any).
            context: Execution context (work_item_id, step_type, etc.).

        Returns:
            ExecutionResult with output, summary, logs, and timing info.
        """
        start = time.monotonic()
        handler = execution_type.upper()

        try:
            if handler == "PLUGIN":
                result = await self._execute_plugin(execution_ref, config, input_data, context)
            elif handler == "SCRIPT":
                result = await self._execute_script(execution_ref, config, input_data, context)
            elif handler == "HTTP":
                result = await self._execute_http(execution_ref, config, input_data, context)
            elif handler == "NIFI_FLOW":
                result = await self._execute_nifi_flow(execution_ref, config, input_data, context)
            else:
                result = ExecutionResult(
                    success=False,
                    summary={"error": f"Unknown execution_type: {execution_type}"},
                    logs=[{"level": "ERROR", "message": f"Unknown execution_type: {execution_type}"}],
                )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            logger.exception("Execution failed: %s", exc)
            result = ExecutionResult(
                success=False,
                duration_ms=elapsed,
                summary={"error": str(exc)},
                logs=[{"level": "ERROR", "message": str(exc)}],
            )
            return result

        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    async def _execute_plugin(
        self,
        execution_ref: str | None,
        config: dict[str, Any],
        input_data: Any,
        context: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Execute a Hermes plugin via subprocess and JSON line protocol."""
        from hermes.plugins.executor import PluginExecutor
        from hermes.plugins.registry import PluginRegistry

        # execution_ref format: "TYPE:name" e.g. "COLLECTOR:rest-api-collector"
        if not execution_ref:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": "No execution_ref provided for PLUGIN"}],
            )

        executor = PluginExecutor(timeout=config.get("timeout", 300))

        # Try to find plugin from registry (in a real app, registry would be injected)
        registry = PluginRegistry()
        parts = execution_ref.split(":", 1)
        if len(parts) == 2:
            plugin = registry.get_plugin(parts[0], parts[1])
        else:
            plugin = registry.get_plugin("COLLECTOR", execution_ref)

        if plugin is None:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": f"Plugin not found: {execution_ref}"}],
            )

        plugin_result = await executor.execute(
            plugin=plugin,
            config=config,
            input_data=input_data,
            context=context,
        )

        return ExecutionResult(
            success=plugin_result.success,
            output={"data": plugin_result.outputs},
            summary=plugin_result.summary,
            logs=[
                {"level": entry.level, "message": entry.message}
                for entry in plugin_result.logs
            ],
        )

    async def _execute_script(
        self,
        execution_ref: str | None,
        config: dict[str, Any],
        input_data: Any,
        context: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Execute an arbitrary script (bash, python, etc.)."""
        if not execution_ref:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": "No script path provided"}],
            )

        env = {
            "VESSEL_CONFIG": json.dumps(config),
            "VESSEL_CONTEXT": json.dumps(context or {}),
        }

        input_bytes = json.dumps(input_data or {}).encode("utf-8")
        timeout = config.get("timeout", 300)

        try:
            proc = await asyncio.create_subprocess_exec(
                execution_ref,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**dict(__import__("os").environ), **env},
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=input_bytes),
                timeout=timeout,
            )

            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            logs: list[dict[str, Any]] = []
            if stderr_text:
                logs.append({"level": "STDERR", "message": stderr_text})

            # Try to parse stdout as JSON
            try:
                output = json.loads(stdout_text) if stdout_text else {}
            except json.JSONDecodeError:
                output = {"raw_output": stdout_text}

            return ExecutionResult(
                success=proc.returncode == 0,
                output=output if isinstance(output, dict) else {"data": output},
                summary={"exit_code": proc.returncode},
                logs=logs,
            )

        except TimeoutError:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": f"Script timed out after {timeout}s"}],
            )

    async def _execute_http(
        self,
        execution_ref: str | None,
        config: dict[str, Any],
        input_data: Any,
        context: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Execute an HTTP request to an external service."""
        url = execution_ref or config.get("url", "")
        if not url:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": "No URL provided for HTTP execution"}],
            )

        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        timeout = config.get("timeout", 30)

        logs: list[dict[str, Any]] = []
        logs.append({"level": "INFO", "message": f"HTTP {method} {url}"})

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                kwargs: dict[str, Any] = {"headers": headers}
                if method in ("POST", "PUT", "PATCH"):
                    kwargs["json"] = input_data
                elif input_data:
                    kwargs["params"] = (
                        input_data if isinstance(input_data, dict) else {"data": str(input_data)}
                    )

                resp = await client.request(method, url, **kwargs)

                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text}

                success = 200 <= resp.status_code < 400
                return ExecutionResult(
                    success=success,
                    output=body if isinstance(body, dict) else {"data": body},
                    summary={
                        "status_code": resp.status_code,
                        "url": url,
                    },
                    logs=logs,
                )

        except httpx.TimeoutException:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": f"HTTP request timed out after {timeout}s"}],
            )
        except httpx.HTTPError as exc:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": f"HTTP error: {exc}"}],
            )

    async def _execute_nifi_flow(
        self,
        execution_ref: str | None,
        config: dict[str, Any],
        input_data: Any,
        context: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Trigger a NiFi process group via REST API."""
        if not self.nifi_config.enabled:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": "NiFi integration is not enabled"}],
            )

        process_group_id = execution_ref or config.get("process_group_id", "")
        if not process_group_id:
            return ExecutionResult(
                success=False,
                logs=[{"level": "ERROR", "message": "No NiFi process group ID provided"}],
            )

        base_url = self.nifi_config.base_url.rstrip("/")
        headers: dict[str, str] = {}
        if self.nifi_config.token:
            headers["Authorization"] = f"Bearer {self.nifi_config.token}"

        logs: list[dict[str, Any]] = []
        logs.append({
            "level": "INFO",
            "message": f"Triggering NiFi process group {process_group_id}",
        })

        try:
            async with httpx.AsyncClient(
                timeout=self.nifi_config.request_timeout,
                headers=headers,
            ) as client:
                # 1. Get process group status
                pg_url = f"{base_url}/process-groups/{process_group_id}"
                resp = await client.get(pg_url)
                resp.raise_for_status()

                # 2. Start the process group (set state to RUNNING)
                schedule_url = f"{base_url}/flow/process-groups/{process_group_id}"
                resp = await client.put(
                    schedule_url,
                    json={
                        "id": process_group_id,
                        "state": "RUNNING",
                        "disconnectedNodeAcknowledged": False,
                    },
                )
                resp.raise_for_status()
                logs.append({"level": "INFO", "message": "NiFi process group started"})

                # 3. Poll for completion (simplified: check for queued flowfiles)
                poll_interval = self.nifi_config.provenance_poll_interval
                max_wait = self.nifi_config.provenance_max_wait
                elapsed = 0.0

                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    status_url = f"{base_url}/process-groups/{process_group_id}/status"
                    status_resp = await client.get(status_url)
                    status_resp.raise_for_status()
                    status_data = status_resp.json()

                    queued = (
                        status_data.get("processGroupStatus", {})
                        .get("aggregateSnapshot", {})
                        .get("queued", "0 / 0 bytes")
                    )
                    if queued.startswith("0 "):
                        logs.append({"level": "INFO", "message": "NiFi flow completed"})
                        break
                else:
                    logs.append({
                        "level": "WARN",
                        "message": f"NiFi flow did not complete within {max_wait}s",
                    })

                # 4. Stop the process group
                resp = await client.put(
                    schedule_url,
                    json={
                        "id": process_group_id,
                        "state": "STOPPED",
                        "disconnectedNodeAcknowledged": False,
                    },
                )

                return ExecutionResult(
                    success=True,
                    output={"process_group_id": process_group_id},
                    summary={"nifi_process_group": process_group_id},
                    logs=logs,
                )

        except httpx.HTTPError as exc:
            return ExecutionResult(
                success=False,
                logs=[*logs, {"level": "ERROR", "message": f"NiFi API error: {exc}"}],
            )
