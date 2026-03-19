"""Plugin Executor - Subprocess-based plugin execution.

Spawns plugin processes, communicates via the Hermes JSON line protocol,
handles timeouts, errors, and progress reporting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from hermes.plugins.protocol import MessageType, PluginProtocol, HermesMessage
from hermes.plugins.registry import PluginManifest

logger = logging.getLogger(__name__)

# Default timeout for plugin execution (seconds)
DEFAULT_TIMEOUT = 300

# Runtime -> command mapping
RUNTIME_COMMANDS: dict[str, list[str]] = {
    "python": ["python3"],
    "python3": ["python3"],
    "node": ["node"],
    "bash": ["bash"],
    "sh": ["sh"],
}


@dataclass
class PluginLogEntry:
    """A single log entry from a plugin execution."""

    timestamp: float
    level: str
    message: str


@dataclass
class PluginResult:
    """Result of a plugin execution."""

    success: bool
    outputs: list[Any] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    logs: list[PluginLogEntry] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    duration_seconds: float = 0.0
    last_progress: float = 0.0


class PluginExecutor:
    """Executes Hermes plugins as subprocesses using the JSON line protocol.

    Usage:
        executor = PluginExecutor()
        result = await executor.execute(
            plugin=manifest,
            config={"url": "https://api.example.com/data"},
            input_data={"records": [...]},
            context={"pipeline_id": "abc123"},
        )
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        on_progress: Optional[Any] = None,
        on_log: Optional[Any] = None,
    ) -> None:
        """Initialize the executor.

        Args:
            timeout: Maximum execution time in seconds.
            on_progress: Optional async callback(progress: float) for STATUS messages.
            on_log: Optional async callback(entry: PluginLogEntry) for LOG messages.
        """
        self.timeout = timeout
        self.on_progress = on_progress
        self.on_log = on_log

    async def execute(
        self,
        plugin: PluginManifest,
        config: dict[str, Any],
        input_data: Any = None,
        context: Optional[dict[str, Any]] = None,
    ) -> PluginResult:
        """Execute a plugin subprocess and return the result.

        Sends CONFIGURE, then EXECUTE messages. Reads OUTPUT, LOG, ERROR,
        STATUS, and DONE messages from the plugin until completion or timeout.

        Args:
            plugin: The plugin manifest describing what to run.
            config: Configuration values for the plugin (matches inputSchema).
            input_data: Input data to process (sent via EXECUTE message).
            context: Execution context (pipeline_id, step_id, etc.).

        Returns:
            PluginResult with outputs, errors, logs, and summary.
        """
        cmd = self._build_command(plugin)
        start_time = time.monotonic()

        logger.info(
            "Executing plugin %s (v%s): %s",
            plugin.name,
            plugin.version,
            " ".join(cmd),
        )

        result = PluginResult(success=False)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(plugin.plugin_dir),
            )

            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None

            # Send CONFIGURE message
            configure_msg = HermesMessage.configure(config, context or {})
            await self._write_message(process.stdin, configure_msg)

            # Send EXECUTE message
            execute_msg = HermesMessage.execute(input_data)
            await self._write_message(process.stdin, execute_msg)

            # Close stdin to signal no more input
            process.stdin.close()
            await process.stdin.wait_closed()

            # Read stdout messages with timeout
            try:
                result = await asyncio.wait_for(
                    self._read_output(process, result),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Plugin %s timed out after %d seconds",
                    plugin.name,
                    self.timeout,
                )
                result.errors.append({
                    "code": "TIMEOUT",
                    "message": f"Plugin execution timed out after {self.timeout}s",
                })
                process.kill()
                await process.wait()

            # Capture stderr
            stderr_data = await process.stderr.read()
            if stderr_data:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                if stderr_text:
                    result.logs.append(
                        PluginLogEntry(
                            timestamp=time.time(),
                            level="STDERR",
                            message=stderr_text,
                        )
                    )

            result.exit_code = process.returncode
            if result.exit_code == 0 and not result.errors:
                result.success = True
            elif result.exit_code == 2:
                result.errors.append({
                    "code": "CONFIG_ERROR",
                    "message": "Plugin reported configuration error (exit code 2)",
                })

        except FileNotFoundError:
            result.errors.append({
                "code": "RUNTIME_NOT_FOUND",
                "message": f"Runtime '{plugin.runtime}' not found. "
                f"Ensure it is installed and in PATH.",
            })
        except OSError as exc:
            result.errors.append({
                "code": "SPAWN_ERROR",
                "message": f"Failed to spawn plugin process: {exc}",
            })
        except Exception as exc:
            result.errors.append({
                "code": "UNEXPECTED_ERROR",
                "message": f"Unexpected error during plugin execution: {exc}",
            })
            logger.exception("Unexpected error executing plugin %s", plugin.name)

        result.duration_seconds = time.monotonic() - start_time
        logger.info(
            "Plugin %s completed: success=%s, outputs=%d, errors=%d, %.2fs",
            plugin.name,
            result.success,
            len(result.outputs),
            len(result.errors),
            result.duration_seconds,
        )

        return result

    async def _read_output(
        self,
        process: asyncio.subprocess.Process,
        result: PluginResult,
    ) -> PluginResult:
        """Read and process all stdout messages from the plugin process."""
        assert process.stdout is not None

        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break  # EOF

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                msg = HermesMessage.from_json(line)
            except ValueError as exc:
                logger.warning(
                    "Ignoring invalid plugin output line: %s (%s)",
                    line[:200],
                    exc,
                )
                continue

            if msg.type == MessageType.OUTPUT:
                result.outputs.append(msg.data.get("data"))

            elif msg.type == MessageType.LOG:
                entry = PluginLogEntry(
                    timestamp=time.time(),
                    level=msg.data.get("level", "INFO"),
                    message=msg.data.get("message", ""),
                )
                result.logs.append(entry)
                if self.on_log is not None:
                    await self.on_log(entry)

            elif msg.type == MessageType.ERROR:
                result.errors.append({
                    "code": msg.data.get("code", "PLUGIN_ERROR"),
                    "message": msg.data.get("message", "Unknown error"),
                })

            elif msg.type == MessageType.STATUS:
                progress = msg.data.get("progress", 0.0)
                result.last_progress = progress
                if self.on_progress is not None:
                    await self.on_progress(progress)

            elif msg.type == MessageType.DONE:
                result.summary = msg.data.get("summary", {})
                break

        # Wait for process to finish
        await process.wait()
        return result

    @staticmethod
    async def _write_message(
        stdin: asyncio.StreamWriter,
        message: HermesMessage,
    ) -> None:
        """Write a protocol message to the process stdin."""
        line = message.to_json() + "\n"
        stdin.write(line.encode("utf-8"))
        await stdin.drain()

    @staticmethod
    def _build_command(plugin: PluginManifest) -> list[str]:
        """Build the subprocess command from the plugin manifest.

        Returns:
            List of command parts, e.g. ["python3", "/path/to/main.py"].

        Raises:
            ValueError: If the runtime is not supported.
        """
        runtime = plugin.runtime.lower()
        cmd_prefix = RUNTIME_COMMANDS.get(runtime)
        if cmd_prefix is None:
            raise ValueError(
                f"Unsupported plugin runtime '{plugin.runtime}'. "
                f"Supported runtimes: {', '.join(RUNTIME_COMMANDS.keys())}"
            )

        # Use just the entrypoint filename since cwd is set to plugin_dir
        return cmd_prefix + [plugin.entrypoint]
