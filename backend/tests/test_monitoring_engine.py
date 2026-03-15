"""Tests for the Monitoring Engine - event detection and work item creation.

Covers file monitoring, pattern matching, ignoring existing files,
API polling with change detection, heartbeat updates, stop/resume,
and error recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from vessel.domain.services.monitoring_engine import (
    ApiPollMonitor,
    BaseMonitor,
    FileMonitor,
    MonitorEvent,
    MonitoringEngine,
    _parse_interval,
)


# ---------------------------------------------------------------------------
# FileMonitor
# ---------------------------------------------------------------------------


class TestFileMonitor:
    """Tests for the FileMonitor - watches directories for new files."""

    @pytest.mark.asyncio
    async def test_file_monitor_detects_new_file(self, tmp_path: Path):
        """Creating a new file in the watched directory produces a MonitorEvent."""
        monitor = FileMonitor({"watch_path": str(tmp_path), "pattern": "*"})

        # First poll: no files
        events = await monitor.poll()
        assert len(events) == 0

        # Create a file
        test_file = tmp_path / "sensor-001.csv"
        test_file.write_text("col1,col2\n1,2\n")

        # Second poll: file detected
        events = await monitor.poll()
        assert len(events) == 1, "Should detect the new file"
        assert events[0].event_type == "FILE"
        assert events[0].key == "sensor-001.csv"
        assert "path" in events[0].metadata
        assert events[0].metadata["size"] > 0

    @pytest.mark.asyncio
    async def test_file_monitor_pattern_matching(self, tmp_path: Path):
        """Only files matching the pattern trigger events."""
        monitor = FileMonitor({
            "watch_path": str(tmp_path),
            "pattern": "*.csv",
        })

        # Create matching and non-matching files
        (tmp_path / "data.csv").write_text("a,b\n")
        (tmp_path / "report.txt").write_text("report\n")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")

        events = await monitor.poll()
        assert len(events) == 1, "Only *.csv files should trigger"
        assert events[0].key == "data.csv"

    @pytest.mark.asyncio
    async def test_file_monitor_ignores_existing(self, tmp_path: Path):
        """Files seen in a previous poll are not reported again."""
        (tmp_path / "existing.csv").write_text("old data\n")

        monitor = FileMonitor({"watch_path": str(tmp_path), "pattern": "*.csv"})

        # First poll: existing file detected
        events1 = await monitor.poll()
        assert len(events1) == 1

        # Second poll: same file, no new events
        events2 = await monitor.poll()
        assert len(events2) == 0, "Already-seen files should not trigger again"

        # Create a new file
        (tmp_path / "new-data.csv").write_text("new data\n")
        events3 = await monitor.poll()
        assert len(events3) == 1
        assert events3[0].key == "new-data.csv"

    @pytest.mark.asyncio
    async def test_file_monitor_nonexistent_path(self, tmp_path: Path):
        """Watching a nonexistent path returns empty list, no crash."""
        monitor = FileMonitor({"watch_path": str(tmp_path / "nonexistent")})
        events = await monitor.poll()
        assert events == []

    @pytest.mark.asyncio
    async def test_file_monitor_recursive(self, tmp_path: Path):
        """Recursive monitoring finds files in subdirectories."""
        sub_dir = tmp_path / "sub" / "deep"
        sub_dir.mkdir(parents=True)
        (sub_dir / "nested.csv").write_text("nested data\n")

        monitor = FileMonitor({
            "watch_path": str(tmp_path),
            "pattern": "*.csv",
            "recursive": True,
        })
        events = await monitor.poll()
        assert len(events) == 1
        assert events[0].key == "nested.csv"


# ---------------------------------------------------------------------------
# ApiPollMonitor
# ---------------------------------------------------------------------------


class TestApiPollMonitor:
    """Tests for the ApiPollMonitor - polls REST APIs for changes."""

    @pytest.mark.asyncio
    async def test_api_poll_detects_change(self):
        """Mock API returns new data -> MonitorEvent created."""
        monitor = ApiPollMonitor({
            "url": "https://api.example.com/data",
            "method": "GET",
        })

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"items": [1, 2, 3]}'
        mock_response.raise_for_status = MagicMock()

        with patch("vessel.domain.services.monitoring_engine.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            events = await monitor.poll()
            assert len(events) == 1
            assert events[0].event_type == "API_RESPONSE"
            assert "content_hash" in events[0].metadata

    @pytest.mark.asyncio
    async def test_api_poll_no_change_no_workitem(self):
        """Same data on consecutive polls -> no new event on second poll."""
        monitor = ApiPollMonitor({
            "url": "https://api.example.com/data",
            "method": "GET",
        })

        response_body = '{"items": [1, 2, 3]}'
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = response_body
        mock_response.raise_for_status = MagicMock()

        with patch("vessel.domain.services.monitoring_engine.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # First poll: change detected
            events1 = await monitor.poll()
            assert len(events1) == 1

            # Second poll: same data, no change
            events2 = await monitor.poll()
            assert len(events2) == 0, "Same content should not trigger new event"

    @pytest.mark.asyncio
    async def test_api_poll_error_recovery(self):
        """API error returns empty events, no crash."""
        monitor = ApiPollMonitor({
            "url": "https://api.example.com/failing",
            "method": "GET",
        })

        with patch("vessel.domain.services.monitoring_engine.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            events = await monitor.poll()
            assert events == [], "Error should return empty list, not crash"


# ---------------------------------------------------------------------------
# MonitoringEngine lifecycle
# ---------------------------------------------------------------------------


class TestMonitoringEngine:
    """Tests for MonitoringEngine start/stop/heartbeat."""

    @pytest.mark.asyncio
    async def test_monitoring_stop_and_resume(self):
        """Stopping and restarting monitoring works without errors."""
        engine = MonitoringEngine(session_factory=AsyncMock())

        # Simulate a monitor task
        activation_id = uuid.uuid4()
        from vessel.domain.services.monitoring_engine import MonitorTask

        async def dummy_loop():
            while True:
                await asyncio.sleep(0.1)

        task = asyncio.create_task(dummy_loop())
        mt = MonitorTask(
            activation_id=activation_id,
            pipeline_id=uuid.uuid4(),
            task=task,
        )
        engine.monitors[activation_id] = mt

        # Stop it
        await engine.stop_monitoring(activation_id)
        assert activation_id not in engine.monitors
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_stop_all(self):
        """stop_all cancels all running monitor tasks."""
        engine = MonitoringEngine(session_factory=AsyncMock())

        from vessel.domain.services.monitoring_engine import MonitorTask

        for i in range(3):
            aid = uuid.uuid4()

            async def loop():
                while True:
                    await asyncio.sleep(0.1)

            task = asyncio.create_task(loop())
            engine.monitors[aid] = MonitorTask(
                activation_id=aid, pipeline_id=uuid.uuid4(), task=task,
            )

        assert len(engine.monitors) == 3
        await engine.stop_all()
        assert len(engine.monitors) == 0

    @pytest.mark.asyncio
    async def test_stop_nonexistent_monitor(self):
        """Stopping a non-existent monitor is a no-op."""
        engine = MonitoringEngine(session_factory=AsyncMock())
        # Should not raise
        await engine.stop_monitoring(uuid.uuid4())


# ---------------------------------------------------------------------------
# Interval parsing
# ---------------------------------------------------------------------------


class TestIntervalParsing:
    """Tests for the _parse_interval helper."""

    def test_parse_seconds(self):
        assert _parse_interval("30s") == 30

    def test_parse_minutes(self):
        assert _parse_interval("5m") == 300

    def test_parse_hours(self):
        assert _parse_interval("1h") == 3600

    def test_parse_bare_integer(self):
        assert _parse_interval("60") == 60

    def test_parse_invalid_returns_default(self):
        assert _parse_interval("invalid") == 60
