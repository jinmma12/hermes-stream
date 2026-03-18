"""Tests for the Vessel Plugin Protocol (JSON-line communication).

Covers message serialization, the full CONFIGURE -> EXECUTE -> OUTPUT -> DONE
lifecycle, error handling, timeout, progress reporting, logging, invalid JSON,
plugin crash recovery, and concurrent execution.
"""

from __future__ import annotations

import asyncio
import io
import textwrap
from pathlib import Path

import pytest

from vessel.plugins.executor import (
    PluginExecutor,
    PluginLogEntry,
)
from vessel.plugins.protocol import MessageType, PluginProtocol, VesselMessage
from vessel.plugins.registry import PluginManifest, PluginType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(tmp_path: Path, script: str, name: str = "test-plugin") -> PluginManifest:
    """Write a Python script to disk and return a matching PluginManifest."""
    plugin_dir = tmp_path / name
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(script))
    return PluginManifest(
        name=name,
        version="1.0.0",
        type=PluginType.COLLECTOR,
        description="test",
        author="test",
        license="MIT",
        runtime="python3",
        entrypoint="main.py",
        input_schema={},
        plugin_dir=plugin_dir,
    )


# ---------------------------------------------------------------------------
# Message serialization
# ---------------------------------------------------------------------------


class TestMessageSerialization:
    """VesselMessage JSON round-trip tests."""

    def test_message_serialization_roundtrip(self):
        """VesselMessage -> JSON string -> VesselMessage preserves all fields."""
        original = VesselMessage.configure(
            config={"url": "https://example.com", "timeout": 30},
            context={"pipeline_id": "abc-123"},
        )
        json_str = original.to_json()
        restored = VesselMessage.from_json(json_str)

        assert restored.type == MessageType.CONFIGURE, "Message type must survive round-trip"
        assert restored.data["config"] == original.data["config"]
        assert restored.data["context"] == original.data["context"]

    def test_output_message_roundtrip(self):
        """OUTPUT message with nested data survives serialization."""
        original = VesselMessage.output({"records": [{"id": 1}, {"id": 2}]})
        restored = VesselMessage.from_json(original.to_json())
        assert restored.type == MessageType.OUTPUT
        assert restored.data["data"]["records"] == [{"id": 1}, {"id": 2}]

    def test_done_message_roundtrip(self):
        """DONE message with summary survives serialization."""
        original = VesselMessage.done({"processed": 42, "skipped": 3})
        restored = VesselMessage.from_json(original.to_json())
        assert restored.type == MessageType.DONE
        assert restored.data["summary"]["processed"] == 42

    def test_status_message_clamps_progress(self):
        """STATUS message clamps progress to [0.0, 1.0]."""
        msg_low = VesselMessage.status(-0.5)
        assert msg_low.data["progress"] == 0.0, "Progress below 0.0 must be clamped"

        msg_high = VesselMessage.status(1.5)
        assert msg_high.data["progress"] == 1.0, "Progress above 1.0 must be clamped"

    def test_error_message_roundtrip(self):
        """ERROR message preserves code and message."""
        original = VesselMessage.error("Something broke", code="DATA_ERROR")
        restored = VesselMessage.from_json(original.to_json())
        assert restored.data["code"] == "DATA_ERROR"
        assert restored.data["message"] == "Something broke"


# ---------------------------------------------------------------------------
# Protocol stream reading/writing
# ---------------------------------------------------------------------------


class TestPluginProtocolStreams:
    """Tests for PluginProtocol read/write over in-memory streams."""

    def test_send_and_read_message(self):
        """Write a message to a stream and read it back via PluginProtocol."""
        buf = io.StringIO()
        msg = VesselMessage.log("hello world", level="DEBUG")
        PluginProtocol.send_message(msg, stream=buf)

        buf.seek(0)
        read_back = PluginProtocol.read_message(stream=buf)
        assert read_back is not None
        assert read_back.type == MessageType.LOG
        assert read_back.data["message"] == "hello world"

    def test_read_message_eof(self):
        """read_message returns None on EOF (empty stream)."""
        buf = io.StringIO("")
        result = PluginProtocol.read_message(stream=buf)
        assert result is None, "EOF should return None"

    def test_read_all_messages(self):
        """read_all_messages collects multiple messages until EOF."""
        buf = io.StringIO()
        PluginProtocol.send_message(VesselMessage.status(0.25), stream=buf)
        PluginProtocol.send_message(VesselMessage.status(0.75), stream=buf)
        PluginProtocol.send_message(VesselMessage.done(), stream=buf)
        buf.seek(0)

        messages = PluginProtocol.read_all_messages(stream=buf)
        assert len(messages) == 3
        assert messages[0].type == MessageType.STATUS
        assert messages[2].type == MessageType.DONE


# ---------------------------------------------------------------------------
# Plugin execution via PluginExecutor
# ---------------------------------------------------------------------------


class TestPluginExecution:
    """Integration-style tests that run real Python subprocesses."""

    @pytest.mark.asyncio
    async def test_configure_execute_flow(self, tmp_path: Path):
        """Full CONFIGURE -> EXECUTE -> OUTPUT -> DONE cycle via subprocess."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "CONFIGURE":
                    pass
                elif msg["type"] == "EXECUTE":
                    data = msg.get("input", {})
                    out = {"type": "OUTPUT", "data": {"result": "ok"}}
                    print(json.dumps(out), flush=True)
                    done = {"type": "DONE", "summary": {"count": 1}}
                    print(json.dumps(done), flush=True)
        '''
        manifest = _make_manifest(tmp_path, script)
        executor = PluginExecutor(timeout=10)
        result = await executor.execute(
            plugin=manifest,
            config={"key": "val"},
            input_data={"records": []},
        )

        assert result.success, f"Expected success, got errors: {result.errors}"
        assert len(result.outputs) == 1
        assert result.outputs[0]["result"] == "ok"
        assert result.summary.get("count") == 1

    @pytest.mark.asyncio
    async def test_plugin_error_handling(self, tmp_path: Path):
        """Plugin sends ERROR message -> result.success is False."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "EXECUTE":
                    err = {"type": "ERROR", "code": "BAD_DATA", "message": "invalid format"}
                    print(json.dumps(err), flush=True)
                    done = {"type": "DONE", "summary": {}}
                    print(json.dumps(done), flush=True)
        '''
        manifest = _make_manifest(tmp_path, script, name="error-plugin")
        executor = PluginExecutor(timeout=10)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert not result.success, "Plugin that sends ERROR should not succeed"
        assert any(e["code"] == "BAD_DATA" for e in result.errors)

    @pytest.mark.asyncio
    async def test_plugin_timeout(self, tmp_path: Path):
        """Plugin exceeds timeout -> killed, result has TIMEOUT error."""
        script = '''\
            import sys, time, json
            for line in sys.stdin:
                pass
            time.sleep(30)  # hang forever
        '''
        manifest = _make_manifest(tmp_path, script, name="slow-plugin")
        executor = PluginExecutor(timeout=1)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert not result.success
        assert any(e["code"] == "TIMEOUT" for e in result.errors), (
            "Timeout error should be recorded"
        )

    @pytest.mark.asyncio
    async def test_plugin_progress_reporting(self, tmp_path: Path):
        """STATUS messages with progress values are captured in result."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "EXECUTE":
                    for p in [0.0, 0.25, 0.5, 0.75, 1.0]:
                        print(json.dumps({"type": "STATUS", "progress": p}), flush=True)
                    print(json.dumps({"type": "DONE", "summary": {}}), flush=True)
        '''
        progress_values: list[float] = []

        async def on_progress(p: float):
            progress_values.append(p)

        manifest = _make_manifest(tmp_path, script, name="progress-plugin")
        executor = PluginExecutor(timeout=10, on_progress=on_progress)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert result.success
        assert result.last_progress == 1.0
        assert len(progress_values) == 5, "All 5 progress callbacks should have fired"

    @pytest.mark.asyncio
    async def test_plugin_logging(self, tmp_path: Path):
        """LOG messages are captured in result.logs."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "EXECUTE":
                    print(json.dumps({"type": "LOG", "level": "INFO", "message": "Starting..."}), flush=True)
                    print(json.dumps({"type": "LOG", "level": "DEBUG", "message": "Processing row 1"}), flush=True)
                    print(json.dumps({"type": "DONE", "summary": {}}), flush=True)
        '''
        log_entries: list[PluginLogEntry] = []

        async def on_log(entry: PluginLogEntry):
            log_entries.append(entry)

        manifest = _make_manifest(tmp_path, script, name="log-plugin")
        executor = PluginExecutor(timeout=10, on_log=on_log)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert result.success
        assert len(result.logs) >= 2, "At least 2 log entries expected"
        assert any(e.message == "Starting..." for e in result.logs)
        assert len(log_entries) == 2, "on_log callback should have been called twice"

    @pytest.mark.asyncio
    async def test_invalid_json_handling(self, tmp_path: Path):
        """Plugin sends invalid JSON -> line is skipped, execution continues."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "EXECUTE":
                    print("THIS IS NOT JSON", flush=True)
                    print(json.dumps({"type": "OUTPUT", "data": {"ok": True}}), flush=True)
                    print(json.dumps({"type": "DONE", "summary": {}}), flush=True)
        '''
        manifest = _make_manifest(tmp_path, script, name="invalid-json-plugin")
        executor = PluginExecutor(timeout=10)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert result.success, "Invalid JSON lines should be skipped, not cause failure"
        assert len(result.outputs) == 1

    @pytest.mark.asyncio
    async def test_plugin_crash_recovery(self, tmp_path: Path):
        """Plugin process dies unexpectedly -> result has non-zero exit code."""
        script = '''\
            import sys, json
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "EXECUTE":
                    print(json.dumps({"type": "OUTPUT", "data": {"partial": True}}), flush=True)
                    sys.exit(1)  # crash
        '''
        manifest = _make_manifest(tmp_path, script, name="crash-plugin")
        executor = PluginExecutor(timeout=10)
        result = await executor.execute(plugin=manifest, config={}, input_data={})

        assert not result.success, "Crashed plugin should not be marked successful"
        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_concurrent_plugin_execution(self, tmp_path: Path):
        """Multiple plugins can run simultaneously without interference."""
        script = '''\
            import sys, json, time
            for line in sys.stdin:
                msg = json.loads(line)
                if msg["type"] == "CONFIGURE":
                    config = msg.get("config", {})
                elif msg["type"] == "EXECUTE":
                    plugin_id = config.get("id", "unknown")
                    time.sleep(0.1)  # simulate work
                    print(json.dumps({"type": "OUTPUT", "data": {"id": plugin_id}}), flush=True)
                    print(json.dumps({"type": "DONE", "summary": {"id": plugin_id}}), flush=True)
        '''
        manifests = []
        for i in range(3):
            manifests.append(_make_manifest(tmp_path, script, name=f"concurrent-{i}"))

        executor = PluginExecutor(timeout=10)
        tasks = [
            executor.execute(plugin=m, config={"id": f"p{i}"}, input_data={})
            for i, m in enumerate(manifests)
        ]
        results = await asyncio.gather(*tasks)

        assert all(r.success for r in results), "All concurrent plugins should succeed"
        ids = {r.outputs[0]["id"] for r in results}
        assert ids == {"p0", "p1", "p2"}, "Each plugin should return its own id"
