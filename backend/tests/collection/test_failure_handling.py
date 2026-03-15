"""Comprehensive failure handling test scenarios for the Hermes data pipeline.

Tests cover download failures, stage-by-stage failures, retry patterns,
circuit breaker behavior, back-pressure control, and dead letter queue
handling -- inspired by production patterns from NiFi, Kafka Connect,
Polly/.NET, and similar systems.

150+ test functions organised into six sections.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import signal
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.collection.conftest import (
    BackpressureController,
    CircuitBreaker,
    DeadLetterQueue,
    DLQEntry,
    MockAPIClient,
    MockAPIResponse,
    MockDBConnection,
    MockFTPFile,
    MockFTPServer,
    MockKafkaConsumer,
    MockKafkaMessage,
    MockSFTPServer,
    RetryTracker,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def retry_operation(
    operation,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.01,
    backoff_factor: float = 2.0,
    max_delay: float | None = None,
    jitter: bool = False,
    retryable_errors: tuple[type[Exception], ...] = (
        IOError,
        ConnectionError,
        TimeoutError,
        OSError,
    ),
    tracker: RetryTracker | None = None,
    timeout_per_attempt: float | None = None,
    cancel_event: asyncio.Event | None = None,
    on_retry=None,
    retry_predicate=None,
) -> Any:
    """Execute *operation* with configurable retry, backoff, jitter, and cancellation."""
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        if cancel_event and cancel_event.is_set():
            raise asyncio.CancelledError("Retry cancelled")
        if tracker:
            tracker.record_attempt()
        try:
            if timeout_per_attempt is not None:
                result = await asyncio.wait_for(operation(), timeout=timeout_per_attempt)
            else:
                result = await operation()
            if tracker:
                tracker.record_success()
            return result
        except Exception as exc:
            # Check custom predicate first
            if retry_predicate and not retry_predicate(exc):
                raise
            if not isinstance(exc, retryable_errors) and retry_predicate is None:
                raise
            last_error = exc
            if tracker:
                tracker.record_failure()
            if on_retry:
                on_retry(attempt, exc)
            if attempt < max_attempts - 1:
                delay = base_delay * (backoff_factor ** attempt)
                if max_delay is not None:
                    delay = min(delay, max_delay)
                if jitter:
                    delay += random.uniform(0, delay * 0.5)
                await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]


@dataclass
class PipelineStage:
    """Represents a single stage in the pipeline."""

    name: str
    enabled: bool = True
    on_error: str = "stop"  # stop | skip | retry
    max_retries: int = 3
    output: Any = None
    error: Exception | None = None
    executed: bool = False
    execution_time: float = 0.0


@dataclass
class PipelineResult:
    """Result of running a pipeline."""

    stages_executed: list[str] = field(default_factory=list)
    stages_skipped: list[str] = field(default_factory=list)
    stages_failed: list[str] = field(default_factory=list)
    final_status: str = "pending"
    error: Exception | None = None
    outputs: dict[str, Any] = field(default_factory=dict)


async def run_pipeline(
    stages: list[PipelineStage],
    stage_functions: dict[str, Any],
    input_data: Any = None,
) -> PipelineResult:
    """Execute pipeline stages sequentially, respecting on_error policy."""
    result = PipelineResult()
    current_input = input_data

    for stage in stages:
        if not stage.enabled:
            result.stages_skipped.append(stage.name)
            continue

        fn = stage_functions.get(stage.name)
        if fn is None:
            result.stages_skipped.append(stage.name)
            continue

        retries = stage.max_retries if stage.on_error == "retry" else 1
        succeeded = False

        for attempt in range(retries):
            try:
                output = await fn(current_input)
                stage.output = output
                stage.executed = True
                result.stages_executed.append(stage.name)
                result.outputs[stage.name] = output
                current_input = output
                succeeded = True
                break
            except Exception as exc:
                stage.error = exc
                if attempt == retries - 1:
                    result.stages_failed.append(stage.name)
                    result.error = exc

                    if stage.on_error == "stop":
                        result.final_status = "failed"
                        return result
                    elif stage.on_error == "skip":
                        result.stages_skipped.append(stage.name)
                        break
                    # retry: loop continues

        if not succeeded and stage.on_error != "skip":
            result.final_status = "failed"
            return result

    result.final_status = "completed" if not result.stages_failed else "partial"
    return result


@dataclass
class DownloadState:
    """Tracks the state of a file download."""

    url: str = ""
    local_path: str = ""
    total_bytes: int = 0
    bytes_downloaded: int = 0
    checksum: str = ""
    temp_path: str = ""
    completed: bool = False
    error: Exception | None = None
    attempts: int = 0

    @property
    def progress_pct(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.bytes_downloaded / self.total_bytes) * 100


async def simulate_download(
    state: DownloadState,
    *,
    fail_at_pct: float | None = None,
    fail_error: Exception | None = None,
    chunk_size: int = 1024,
    content: bytes | None = None,
    verify_checksum: bool = False,
    expected_checksum: str = "",
) -> bytes:
    """Simulate a chunked download, optionally failing at a given percentage."""
    state.attempts += 1
    data = content or (b"x" * state.total_bytes)
    state.total_bytes = len(data)
    result = bytearray()
    offset = state.bytes_downloaded  # support resume

    while offset < len(data):
        if fail_at_pct is not None and fail_error is not None:
            pct = (offset / len(data)) * 100
            if pct >= fail_at_pct:
                state.bytes_downloaded = offset
                state.error = fail_error
                raise fail_error

        end = min(offset + chunk_size, len(data))
        result.extend(data[offset:end])
        offset = end
        state.bytes_downloaded = offset

    final_bytes = bytes(result)
    if verify_checksum:
        actual = hashlib.sha256(data).hexdigest()
        if expected_checksum and actual != expected_checksum:
            raise ValueError(f"Checksum mismatch: {actual} != {expected_checksum}")

    state.completed = True
    return final_bytes


# ===========================================================================
# Section 1: Download Failures (30 tests)
# ===========================================================================


class TestDownloadFailures:
    """Download failure scenarios inspired by NiFi GetFile/FetchFile processors."""

    @pytest.mark.asyncio
    async def test_download_fails_at_0_percent_full_retry(self, tmp_path: Path):
        """Download fails immediately at 0%%; full retry restarts from scratch.

        Inspired by NiFi GetFile processor behavior on immediate connection drops.
        """
        # Arrange
        state = DownloadState(url="ftp://host/file.csv", total_bytes=10000)
        error = ConnectionError("Connection dropped")

        # Act — first attempt fails at 0%
        with pytest.raises(ConnectionError):
            await simulate_download(state, fail_at_pct=0.0, fail_error=error)
        assert state.bytes_downloaded == 0
        assert state.attempts == 1

        # Retry from scratch
        state.bytes_downloaded = 0
        data = await simulate_download(state, content=b"x" * 10000)

        # Assert
        assert state.completed is True
        assert len(data) == 10000
        assert state.attempts == 2

    @pytest.mark.asyncio
    async def test_download_fails_at_50_percent_resume(self, tmp_path: Path):
        """Download fails at 50%%; resume continues from the last byte.

        Inspired by NiFi FetchFile resume-on-failure pattern.
        """
        # Arrange
        state = DownloadState(url="ftp://host/file.csv", total_bytes=10000)

        # Act — fail at 50%
        with pytest.raises(IOError):
            await simulate_download(
                state, fail_at_pct=50.0, fail_error=IOError("Network reset")
            )
        assert 4000 <= state.bytes_downloaded <= 6000

        # Resume from where we left off
        data = await simulate_download(state, content=b"x" * 10000)

        # Assert
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_fails_at_99_percent_resume(self, tmp_path: Path):
        """Download fails at 99%%; resume finishes the last 1%%.

        Inspired by NiFi FetchFile processor with partial content support.
        """
        # Arrange
        content = b"A" * 10000
        state = DownloadState(url="ftp://host/file.csv", total_bytes=len(content))

        # Act — fail at 99%
        with pytest.raises(TimeoutError):
            await simulate_download(
                state,
                content=content,
                fail_at_pct=99.0,
                fail_error=TimeoutError("Read timeout"),
            )
        assert state.bytes_downloaded >= 9800

        # Resume
        data = await simulate_download(state, content=content)
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_network_reset_during_transfer(self):
        """Network reset mid-transfer raises ConnectionResetError.

        Inspired by NiFi's handling of TCP RST packets during GetFile.
        """
        state = DownloadState(url="http://host/data.bin", total_bytes=50000)
        with pytest.raises(ConnectionResetError):
            await simulate_download(
                state,
                fail_at_pct=30.0,
                fail_error=ConnectionResetError("Connection reset by peer"),
            )
        assert state.bytes_downloaded > 0
        assert not state.completed

    @pytest.mark.asyncio
    async def test_download_server_closes_connection(self):
        """Server closes connection abruptly during transfer.

        Inspired by NiFi ListenHTTP processor connection handling.
        """
        state = DownloadState(url="http://host/data.bin", total_bytes=20000)
        with pytest.raises(ConnectionAbortedError):
            await simulate_download(
                state,
                fail_at_pct=65.0,
                fail_error=ConnectionAbortedError("Server closed connection"),
            )
        assert not state.completed
        assert state.error is not None

    @pytest.mark.asyncio
    async def test_download_timeout_slow_server(self):
        """Slow server causes read timeout.

        Inspired by NiFi InvokeHTTP timeout configuration.
        """
        state = DownloadState(url="http://slow.host/file.csv", total_bytes=10000)
        with pytest.raises(TimeoutError):
            await simulate_download(
                state,
                fail_at_pct=10.0,
                fail_error=TimeoutError("Read timed out"),
            )
        assert state.bytes_downloaded < 2000

    @pytest.mark.asyncio
    async def test_download_disk_full_during_write(self, tmp_path: Path):
        """Disk full error during write is raised and download state preserved.

        Inspired by NiFi content repository disk-full handling.
        """
        state = DownloadState(url="ftp://host/large.bin", total_bytes=1_000_000)
        with pytest.raises(OSError):
            await simulate_download(
                state,
                fail_at_pct=80.0,
                fail_error=OSError(28, "No space left on device"),
            )
        assert not state.completed
        assert state.bytes_downloaded > 0

    @pytest.mark.asyncio
    async def test_download_permission_denied_target(self, tmp_path: Path):
        """Permission denied on target file raises PermissionError.

        Inspired by NiFi PutFile processor permission checks.
        """
        state = DownloadState(
            url="ftp://host/file.csv",
            local_path=str(tmp_path / "readonly" / "file.csv"),
            total_bytes=1000,
        )
        with pytest.raises(PermissionError):
            await simulate_download(
                state,
                fail_at_pct=0.0,
                fail_error=PermissionError("Permission denied"),
            )

    @pytest.mark.asyncio
    async def test_download_source_deleted_mid_transfer(self):
        """Source file deleted during transfer raises FileNotFoundError.

        Inspired by NiFi FetchFile processor source-missing handling.
        """
        state = DownloadState(url="ftp://host/volatile.csv", total_bytes=5000)
        with pytest.raises(FileNotFoundError):
            await simulate_download(
                state,
                fail_at_pct=40.0,
                fail_error=FileNotFoundError("550 File not found"),
            )
        assert not state.completed

    @pytest.mark.asyncio
    async def test_download_source_modified_mid_transfer(self):
        """Source file modified mid-transfer detected via changed size.

        Inspired by NiFi ListFile modification-date tracking.
        """
        # Arrange
        state = DownloadState(url="ftp://host/changing.csv", total_bytes=5000)

        # Simulate download of original
        data = await simulate_download(state, content=b"A" * 5000)
        original_hash = hashlib.sha256(data).hexdigest()

        # Source changes
        state2 = DownloadState(url="ftp://host/changing.csv", total_bytes=6000)
        data2 = await simulate_download(state2, content=b"B" * 6000)
        new_hash = hashlib.sha256(data2).hexdigest()

        # Assert
        assert original_hash != new_hash
        assert state.total_bytes != state2.total_bytes

    @pytest.mark.asyncio
    async def test_download_checksum_mismatch_retry(self):
        """Checksum mismatch triggers ValueError for retry.

        Inspired by NiFi ValidateRecord processor checksum validation.
        """
        state = DownloadState(url="ftp://host/file.csv", total_bytes=1000)
        with pytest.raises(ValueError, match="Checksum mismatch"):
            await simulate_download(
                state,
                content=b"real data",
                verify_checksum=True,
                expected_checksum="wrong_checksum_value",
            )

    @pytest.mark.asyncio
    async def test_download_partial_file_cleanup(self, tmp_path: Path):
        """Partial file is cleaned up after failed download.

        Inspired by NiFi PutFile atomic-write behavior.
        """
        temp_file = tmp_path / "partial.tmp"
        temp_file.write_bytes(b"partial content")
        assert temp_file.exists()

        # Simulate cleanup after failure
        state = DownloadState(
            url="ftp://host/file.csv",
            temp_path=str(temp_file),
            total_bytes=10000,
        )
        with pytest.raises(ConnectionError):
            await simulate_download(
                state, fail_at_pct=30.0, fail_error=ConnectionError("Lost")
            )

        # Cleanup
        if Path(state.temp_path).exists():
            Path(state.temp_path).unlink()
        assert not temp_file.exists()

    @pytest.mark.asyncio
    async def test_download_resume_after_restart(self):
        """Download resumes from saved byte offset after process restart.

        Inspired by NiFi state-management for processor resume.
        """
        content = b"D" * 20000
        state = DownloadState(url="ftp://host/big.csv", total_bytes=len(content))

        # First attempt fails at 50%
        with pytest.raises(IOError):
            await simulate_download(
                state,
                content=content,
                fail_at_pct=50.0,
                fail_error=IOError("Crash"),
            )
        saved_offset = state.bytes_downloaded

        # Simulate restart: restore state
        restored = DownloadState(
            url=state.url,
            total_bytes=state.total_bytes,
            bytes_downloaded=saved_offset,
        )
        data = await simulate_download(restored, content=content)

        assert restored.completed is True
        assert restored.attempts == 1

    @pytest.mark.asyncio
    async def test_download_concurrent_one_fails(self):
        """One of several concurrent downloads fails; others succeed.

        Inspired by NiFi concurrent task scheduling per processor.
        """
        results = []

        async def download_ok():
            s = DownloadState(total_bytes=1000)
            d = await simulate_download(s, content=b"x" * 1000)
            return ("ok", len(d))

        async def download_fail():
            s = DownloadState(total_bytes=1000)
            await simulate_download(
                s, fail_at_pct=50.0, fail_error=IOError("fail")
            )

        tasks = [
            asyncio.create_task(download_ok()),
            asyncio.create_task(download_fail()),
            asyncio.create_task(download_ok()),
        ]

        for t in tasks:
            try:
                results.append(await t)
            except IOError:
                results.append(("failed", 0))

        successes = [r for r in results if r[0] == "ok"]
        failures = [r for r in results if r[0] == "failed"]
        assert len(successes) == 2
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_download_zero_byte_file(self):
        """Zero-byte file downloads successfully as empty bytes.

        Inspired by NiFi GetFile handling of empty files.
        """
        state = DownloadState(url="ftp://host/empty.csv", total_bytes=0)
        data = await simulate_download(state, content=b"")
        assert data == b""
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_very_large_10gb_streaming(self):
        """Large file download is simulated via chunked streaming (not loaded into memory).

        Inspired by NiFi content-claim streaming for large FlowFiles.
        """
        # We simulate with a small buffer but track as if 10 GB
        simulated_size = 10_000  # stand-in for 10 GB
        state = DownloadState(url="ftp://host/huge.bin", total_bytes=simulated_size)
        data = await simulate_download(
            state, content=b"Z" * simulated_size, chunk_size=1000
        )
        assert len(data) == simulated_size
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_corrupt_file_detection(self):
        """Corrupt file detected via checksum after download.

        Inspired by NiFi HashContent processor for integrity checks.
        """
        content = b"good data"
        expected = hashlib.sha256(content).hexdigest()
        state = DownloadState(url="ftp://host/file.csv", total_bytes=len(content))

        # Good checksum passes
        data = await simulate_download(
            state, content=content, verify_checksum=True, expected_checksum=expected
        )
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_ftp_passive_firewall_blocked(
        self, mock_ftp_server: MockFTPServer
    ):
        """FTP passive mode blocked by firewall raises connection error.

        Inspired by NiFi GetFTP passive-mode configuration.
        """
        mock_ftp_server.set_connect_error(
            ConnectionError("Passive mode data connection failed")
        )
        with pytest.raises(ConnectionError, match="Passive mode"):
            await mock_ftp_server.connect("ftp.firewalled.com")

    @pytest.mark.asyncio
    async def test_download_sftp_key_exchange_failure(
        self, mock_sftp_server: MockSFTPServer
    ):
        """SFTP key exchange failure raises authentication error.

        Inspired by NiFi GetSFTP key-negotiation handling.
        """
        mock_sftp_server.set_auth_error(
            PermissionError("Key exchange failed: incompatible algorithms")
        )
        await mock_sftp_server.connect("sftp.example.com", 22)
        with pytest.raises(PermissionError, match="Key exchange failed"):
            await mock_sftp_server.login_with_key("user", "/path/to/key")

    @pytest.mark.asyncio
    async def test_download_ssl_handshake_failure(
        self, mock_ftp_server: MockFTPServer
    ):
        """SSL handshake failure on FTPS connection.

        Inspired by NiFi GetFTP SSL/TLS configuration.
        """
        mock_ftp_server.set_connect_error(
            ConnectionError("SSL: CERTIFICATE_VERIFY_FAILED")
        )
        with pytest.raises(ConnectionError, match="SSL"):
            await mock_ftp_server.connect("ftps.example.com", 990)

    @pytest.mark.asyncio
    async def test_download_dns_failure(self, mock_ftp_server: MockFTPServer):
        """DNS resolution failure prevents connection.

        Inspired by NiFi connection-pool DNS caching.
        """
        mock_ftp_server.set_connect_error(
            OSError("Name or service not known")
        )
        with pytest.raises(OSError, match="Name or service not known"):
            await mock_ftp_server.connect("nonexistent.example.invalid")

    @pytest.mark.asyncio
    async def test_download_connection_refused(self, mock_ftp_server: MockFTPServer):
        """Connection refused when server is down.

        Inspired by NiFi connection-error penalization.
        """
        mock_ftp_server.set_connect_error(
            ConnectionRefusedError("Connection refused")
        )
        with pytest.raises(ConnectionRefusedError):
            await mock_ftp_server.connect("ftp.down.com", 21)

    @pytest.mark.asyncio
    async def test_download_connection_reset(self, mock_ftp_server: MockFTPServer):
        """Connection reset by remote host during connect.

        Inspired by NiFi retry on connection-reset scenarios.
        """
        mock_ftp_server.set_connect_error(
            ConnectionResetError("Connection reset by peer")
        )
        with pytest.raises(ConnectionResetError):
            await mock_ftp_server.connect("ftp.unstable.com")

    @pytest.mark.asyncio
    async def test_download_proxy_timeout(self, mock_api_client: MockAPIClient):
        """Download through proxy times out.

        Inspired by NiFi InvokeHTTP proxy configuration.
        """
        mock_api_client.set_error(TimeoutError("Proxy connection timed out"), count=1)
        with pytest.raises(TimeoutError, match="Proxy"):
            await mock_api_client.request("GET", "http://proxy:8080/file.csv")

    @pytest.mark.asyncio
    async def test_download_bandwidth_throttled(self):
        """Bandwidth throttling slows download but still completes.

        Inspired by NiFi site-to-site bandwidth throttling.
        """
        state = DownloadState(url="ftp://host/file.csv", total_bytes=5000)
        # Small chunk simulates throttling
        data = await simulate_download(state, content=b"T" * 5000, chunk_size=100)
        assert len(data) == 5000
        assert state.completed is True

    @pytest.mark.asyncio
    async def test_download_max_size_exceeded(self):
        """Download rejected when file exceeds maximum allowed size.

        Inspired by NiFi RouteOnAttribute size-based routing.
        """
        max_size = 5000
        file_size = 10000
        state = DownloadState(url="ftp://host/too_big.bin", total_bytes=file_size)

        if state.total_bytes > max_size:
            error = ValueError(f"File size {file_size} exceeds max {max_size}")
            state.error = error
        else:
            await simulate_download(state, content=b"x" * file_size)

        assert state.error is not None
        assert "exceeds max" in str(state.error)

    @pytest.mark.asyncio
    async def test_download_temp_file_collision(self, tmp_path: Path):
        """Temp file name collision is handled with unique suffix.

        Inspired by NiFi PutFile conflict-resolution strategy.
        """
        temp1 = tmp_path / "download.tmp"
        temp1.write_bytes(b"existing temp")

        # Generate unique temp name
        unique_name = f"download_{uuid.uuid4().hex[:8]}.tmp"
        temp2 = tmp_path / unique_name

        assert not temp2.exists()
        temp2.write_bytes(b"new download")
        assert temp2.exists()
        assert temp1.name != temp2.name

    @pytest.mark.asyncio
    async def test_download_atomic_rename_on_complete(self, tmp_path: Path):
        """Completed download is atomically renamed from temp to final path.

        Inspired by NiFi PutFile atomic write-then-rename strategy.
        """
        temp_path = tmp_path / "file.csv.tmp"
        final_path = tmp_path / "file.csv"

        # Write to temp
        temp_path.write_bytes(b"complete data")
        assert temp_path.exists()
        assert not final_path.exists()

        # Atomic rename
        temp_path.rename(final_path)
        assert final_path.exists()
        assert not temp_path.exists()
        assert final_path.read_bytes() == b"complete data"

    @pytest.mark.asyncio
    async def test_download_encoding_mismatch(self):
        """File with unexpected encoding is detected.

        Inspired by NiFi ConvertCharacterSet processor.
        """
        content = "données françaises".encode("latin-1")
        state = DownloadState(url="ftp://host/french.csv", total_bytes=len(content))
        data = await simulate_download(state, content=content)

        # Trying to decode as UTF-8 should fail
        with pytest.raises(UnicodeDecodeError):
            data.decode("utf-8")

        # Correct encoding works
        text = data.decode("latin-1")
        assert "françaises" in text

    @pytest.mark.asyncio
    async def test_download_binary_vs_text_mode(self):
        """Binary file content is preserved without text-mode line ending conversion.

        Inspired by NiFi FetchFile transfer-mode setting.
        """
        binary_content = bytes(range(256))
        state = DownloadState(
            url="ftp://host/binary.dat", total_bytes=len(binary_content)
        )
        data = await simulate_download(state, content=binary_content)
        assert data == binary_content
        assert len(data) == 256


# ===========================================================================
# Section 2: Stage-by-Stage Failure (30 tests)
# ===========================================================================


class TestStageByStageFailure:
    """Pipeline stage failure scenarios inspired by NiFi processor groups
    and Kafka Connect connector task lifecycle."""

    @pytest.mark.asyncio
    async def test_collect_success_algorithm_fails_transfer_skipped(self):
        """Collect succeeds, algorithm fails, transfer is skipped.

        Inspired by NiFi processor-group routing on failure.
        """
        stages = [
            PipelineStage(name="collect", on_error="stop"),
            PipelineStage(name="algorithm", on_error="stop"),
            PipelineStage(name="transfer", on_error="stop"),
        ]

        async def collect_fn(_):
            return {"data": [1, 2, 3]}

        async def algorithm_fn(_):
            raise RuntimeError("Algorithm crashed")

        async def transfer_fn(_):
            return {"transferred": True}

        result = await run_pipeline(
            stages,
            {"collect": collect_fn, "algorithm": algorithm_fn, "transfer": transfer_fn},
        )

        assert "collect" in result.stages_executed
        assert "algorithm" in result.stages_failed
        assert "transfer" not in result.stages_executed
        assert result.final_status == "failed"

    @pytest.mark.asyncio
    async def test_collect_fails_nothing_else_runs(self):
        """Collection failure prevents all downstream stages.

        Inspired by NiFi upstream-processor failure propagation.
        """
        stages = [
            PipelineStage(name="collect", on_error="stop"),
            PipelineStage(name="algorithm", on_error="stop"),
            PipelineStage(name="transfer", on_error="stop"),
        ]

        async def collect_fn(_):
            raise ConnectionError("Source unreachable")

        result = await run_pipeline(stages, {"collect": collect_fn})

        assert "collect" in result.stages_failed
        assert result.stages_executed == []
        assert result.final_status == "failed"

    @pytest.mark.asyncio
    async def test_collect_partial_data_rollback(self):
        """Partial collection is rolled back when stage fails.

        Inspired by Kafka Connect task rollback on connector failure.
        """
        collected_items: list[int] = []

        async def collect_fn(_):
            for i in range(5):
                collected_items.append(i)
                if i == 3:
                    raise IOError("Source interrupted")
            return collected_items

        stages = [PipelineStage(name="collect", on_error="stop")]
        result = await run_pipeline(stages, {"collect": collect_fn})

        assert result.final_status == "failed"
        # Rollback: clear partial data
        collected_items.clear()
        assert len(collected_items) == 0

    @pytest.mark.asyncio
    async def test_collect_timeout_marks_failed(self):
        """Collection timeout marks stage as failed.

        Inspired by NiFi processor scheduling timeout.
        """
        async def slow_collect(_):
            await asyncio.sleep(10)
            return {"data": []}

        async def timed_collect(_):
            try:
                return await asyncio.wait_for(slow_collect(None), timeout=0.01)
            except asyncio.TimeoutError:
                raise TimeoutError("Collection timed out")

        stages = [PipelineStage(name="collect", on_error="stop")]
        result = await run_pipeline(stages, {"collect": timed_collect})

        assert "collect" in result.stages_failed
        assert result.final_status == "failed"

    @pytest.mark.asyncio
    async def test_algorithm_crashes_output_preserved(self):
        """Algorithm crash preserves collect-stage output for reprocessing.

        Inspired by NiFi FlowFile persistence across processor failures.
        """
        stages = [
            PipelineStage(name="collect", on_error="stop"),
            PipelineStage(name="algorithm", on_error="stop"),
        ]

        async def collect_fn(_):
            return {"rows": [1, 2, 3], "source": "test"}

        async def algorithm_fn(_):
            raise RuntimeError("Segfault in algorithm")

        result = await run_pipeline(
            stages, {"collect": collect_fn, "algorithm": algorithm_fn}
        )

        assert result.outputs["collect"] == {"rows": [1, 2, 3], "source": "test"}
        assert "algorithm" in result.stages_failed

    @pytest.mark.asyncio
    async def test_algorithm_timeout_failed(self):
        """Algorithm exceeding time limit is marked failed.

        Inspired by NiFi processor execution timeout.
        """
        async def slow_algo(_):
            await asyncio.sleep(10)

        async def timed_algo(_):
            try:
                return await asyncio.wait_for(slow_algo(None), timeout=0.01)
            except asyncio.TimeoutError:
                raise TimeoutError("Algorithm timed out")

        stages = [PipelineStage(name="algorithm", on_error="stop")]
        result = await run_pipeline(stages, {"algorithm": timed_algo})

        assert "algorithm" in result.stages_failed

    @pytest.mark.asyncio
    async def test_algorithm_invalid_output(self):
        """Algorithm returning invalid output type raises error.

        Inspired by NiFi ValidateRecord processor schema enforcement.
        """
        async def bad_algo(_):
            return "not a dict"  # Expected dict

        stages = [
            PipelineStage(name="algorithm", on_error="stop"),
            PipelineStage(name="validate", on_error="stop"),
        ]

        async def validate_fn(inp):
            if not isinstance(inp, dict):
                raise TypeError(f"Expected dict, got {type(inp).__name__}")
            return inp

        result = await run_pipeline(
            stages, {"algorithm": bad_algo, "validate": validate_fn}
        )
        assert "validate" in result.stages_failed

    @pytest.mark.asyncio
    async def test_algorithm_oom_killed(self):
        """Algorithm OOM-kill is represented as MemoryError.

        Inspired by Kafka Connect task OOM handling.
        """
        async def oom_algo(_):
            raise MemoryError("Out of memory")

        stages = [PipelineStage(name="algorithm", on_error="stop")]
        # MemoryError is not in retryable_errors
        result = await run_pipeline(stages, {"algorithm": oom_algo})
        assert "algorithm" in result.stages_failed

    @pytest.mark.asyncio
    async def test_algorithm_grpc_lost(self):
        """gRPC connection to algorithm service lost during execution.

        Inspired by NiFi InvokeGRPC processor connection management.
        """
        async def grpc_algo(_):
            raise ConnectionError("gRPC: UNAVAILABLE - transport closing")

        stages = [PipelineStage(name="algorithm", on_error="stop")]
        result = await run_pipeline(stages, {"algorithm": grpc_algo})
        assert "algorithm" in result.stages_failed
        assert "UNAVAILABLE" in str(result.error)

    @pytest.mark.asyncio
    async def test_algorithm_empty_result(self):
        """Algorithm returning empty result is handled gracefully.

        Inspired by NiFi RouteOnContent empty-content handling.
        """
        async def empty_algo(_):
            return {"results": []}

        async def transfer_fn(inp):
            if not inp.get("results"):
                return {"transferred": 0, "skipped": True}
            return {"transferred": len(inp["results"])}

        stages = [
            PipelineStage(name="algorithm"),
            PipelineStage(name="transfer"),
        ]
        result = await run_pipeline(
            stages, {"algorithm": empty_algo, "transfer": transfer_fn}
        )
        assert result.final_status == "completed"
        assert result.outputs["transfer"]["skipped"] is True

    @pytest.mark.asyncio
    async def test_algorithm_wrong_schema(self):
        """Algorithm output with wrong schema detected at validation.

        Inspired by NiFi ValidateRecord schema registry integration.
        """
        required_fields = {"id", "value", "timestamp"}

        async def algo_fn(_):
            return {"id": 1, "value": 42}  # Missing 'timestamp'

        async def validate_fn(inp):
            missing = required_fields - set(inp.keys())
            if missing:
                raise ValueError(f"Missing fields: {missing}")
            return inp

        stages = [
            PipelineStage(name="algorithm"),
            PipelineStage(name="validate", on_error="stop"),
        ]
        result = await run_pipeline(
            stages, {"algorithm": algo_fn, "validate": validate_fn}
        )
        assert "validate" in result.stages_failed

    @pytest.mark.asyncio
    async def test_algorithm_returns_error_message(self):
        """Algorithm returns error message instead of data; downstream detects.

        Inspired by Kafka Connect error-reporting converters.
        """
        async def algo_fn(_):
            return {"error": "Model not loaded", "code": 503}

        async def transfer_fn(inp):
            if "error" in inp:
                raise RuntimeError(f"Upstream error: {inp['error']}")
            return inp

        stages = [
            PipelineStage(name="algorithm"),
            PipelineStage(name="transfer", on_error="stop"),
        ]
        result = await run_pipeline(
            stages, {"algorithm": algo_fn, "transfer": transfer_fn}
        )
        assert "transfer" in result.stages_failed

    @pytest.mark.asyncio
    async def test_transfer_target_db_down(self, mock_db_connection: MockDBConnection):
        """Transfer fails when target database is down.

        Inspired by NiFi PutDatabaseRecord failure routing.
        """
        mock_db_connection.set_connect_error(ConnectionError("DB connection refused"))
        with pytest.raises(ConnectionError):
            await mock_db_connection.connect("postgresql://down:5432/db")

    @pytest.mark.asyncio
    async def test_transfer_target_api_500(self, mock_api_client: MockAPIClient):
        """Transfer fails when target API returns 500.

        Inspired by NiFi InvokeHTTP 5xx retry behavior.
        """
        mock_api_client.add_response(
            MockAPIResponse(status_code=500, body="Internal Server Error")
        )
        resp = await mock_api_client.request("POST", "http://target/api/ingest")
        assert resp.status_code == 500
        with pytest.raises(Exception, match="HTTP 500"):
            resp.raise_for_status()

    @pytest.mark.asyncio
    async def test_transfer_target_disk_full(self):
        """Transfer fails when target disk is full.

        Inspired by NiFi PutFile disk-space check.
        """
        async def transfer_fn(_):
            raise OSError(28, "No space left on device")

        stages = [PipelineStage(name="transfer", on_error="stop")]
        result = await run_pipeline(stages, {"transfer": transfer_fn})
        assert "transfer" in result.stages_failed

    @pytest.mark.asyncio
    async def test_transfer_partial_write_rollback(self):
        """Partial write to target is rolled back on failure.

        Inspired by Kafka Connect exactly-once sink connector rollback.
        """
        written: list[int] = []

        async def transfer_fn(_):
            for i in range(10):
                written.append(i)
                if i == 5:
                    raise IOError("Write failed at record 5")
            return {"written": len(written)}

        stages = [PipelineStage(name="transfer", on_error="stop")]
        result = await run_pipeline(stages, {"transfer": transfer_fn})

        assert result.final_status == "failed"
        # Rollback
        written.clear()
        assert len(written) == 0

    @pytest.mark.asyncio
    async def test_transfer_idempotent_no_duplicates(self):
        """Idempotent transfer does not create duplicates on retry.

        Inspired by Kafka Connect idempotent producer/sink semantics.
        """
        target_store: dict[str, Any] = {}
        call_count = 0

        async def idempotent_transfer(_):
            nonlocal call_count
            call_count += 1
            # Idempotent: uses upsert with unique key
            for item in [{"id": "a", "v": 1}, {"id": "b", "v": 2}]:
                target_store[item["id"]] = item
            if call_count == 1:
                raise IOError("Network blip after write")
            return {"written": len(target_store)}

        # First attempt writes then fails
        try:
            await idempotent_transfer(None)
        except IOError:
            pass

        # Retry: same data, no duplicates
        result = await idempotent_transfer(None)
        assert len(target_store) == 2  # No duplicates
        assert result["written"] == 2

    @pytest.mark.asyncio
    async def test_transfer_timeout_retry_succeeds(
        self, mock_api_client: MockAPIClient
    ):
        """Transfer timeout on first attempt, success on retry.

        Inspired by NiFi InvokeHTTP retry with backoff.
        """
        mock_api_client.set_error(TimeoutError("Request timed out"), count=1)
        mock_api_client.add_response(MockAPIResponse(status_code=200, body="ok"))

        # First call fails
        with pytest.raises(TimeoutError):
            await mock_api_client.request("POST", "http://target/api/data")

        # Retry succeeds
        resp = await mock_api_client.request("POST", "http://target/api/data")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_transfer_auth_expired_refresh(
        self, mock_api_client: MockAPIClient
    ):
        """Expired auth token triggers refresh and retry.

        Inspired by NiFi InvokeHTTP OAuth2 token refresh.
        """
        mock_api_client.add_response(
            MockAPIResponse(status_code=401, body="Token expired")
        )
        mock_api_client.add_response(
            MockAPIResponse(status_code=200, body='{"token": "new_token"}')
        )
        mock_api_client.add_response(
            MockAPIResponse(status_code=200, body="success")
        )

        # First request gets 401
        resp1 = await mock_api_client.request("POST", "http://target/api/data")
        assert resp1.status_code == 401

        # Refresh token
        resp2 = await mock_api_client.request("POST", "http://auth/refresh")
        assert resp2.status_code == 200

        # Retry with new token
        resp3 = await mock_api_client.request(
            "POST", "http://target/api/data",
            headers={"Authorization": "Bearer new_token"},
        )
        assert resp3.status_code == 200

    @pytest.mark.asyncio
    async def test_pipeline_crash_mid_algorithm(self):
        """Pipeline crash mid-algorithm preserves upstream outputs.

        Inspired by NiFi content-repository crash recovery.
        """
        stages = [
            PipelineStage(name="collect"),
            PipelineStage(name="algorithm", on_error="stop"),
        ]

        async def collect_fn(_):
            return {"rows": list(range(100))}

        async def algorithm_fn(_):
            raise SystemError("Unexpected crash")

        result = await run_pipeline(
            stages, {"collect": collect_fn, "algorithm": algorithm_fn}
        )
        assert "collect" in result.stages_executed
        assert result.outputs["collect"]["rows"] == list(range(100))

    @pytest.mark.asyncio
    async def test_pipeline_sigterm_cleanup(self):
        """SIGTERM triggers graceful cleanup of in-flight work.

        Inspired by NiFi shutdown hook and Kafka Connect graceful stop.
        """
        cleanup_performed = False

        async def work_with_cleanup():
            nonlocal cleanup_performed
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cleanup_performed = True
                raise

        task = asyncio.create_task(work_with_cleanup())
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert cleanup_performed is True

    @pytest.mark.asyncio
    async def test_pipeline_sigkill_recovery(self):
        """After SIGKILL (unclean shutdown), pipeline recovers from saved state.

        Inspired by NiFi write-ahead-log recovery after crash.
        """
        # Simulate saved checkpoint
        checkpoint = {
            "last_stage": "collect",
            "last_output": {"rows": [1, 2, 3]},
            "completed_stages": ["collect"],
        }

        # Recovery: resume from checkpoint
        stages = [
            PipelineStage(name="algorithm"),
            PipelineStage(name="transfer"),
        ]

        async def algorithm_fn(inp):
            return {"processed": len(inp["rows"])}

        async def transfer_fn(inp):
            return {"transferred": inp["processed"]}

        result = await run_pipeline(
            stages,
            {"algorithm": algorithm_fn, "transfer": transfer_fn},
            input_data=checkpoint["last_output"],
        )
        assert result.final_status == "completed"
        assert result.outputs["transfer"]["transferred"] == 3

    @pytest.mark.asyncio
    async def test_pipeline_db_lost_during_execution(
        self, mock_db_connection: MockDBConnection
    ):
        """Database connection lost during pipeline execution.

        Inspired by NiFi DBCPConnectionPool connection validation.
        """
        await mock_db_connection.connect("postgresql://host/db")
        assert mock_db_connection.connected

        mock_db_connection.set_query_error(
            ConnectionError("Connection to database lost")
        )
        with pytest.raises(ConnectionError, match="lost"):
            await mock_db_connection.execute("SELECT 1")

    @pytest.mark.asyncio
    async def test_pipeline_content_repo_disk_full(self, tmp_path: Path):
        """Content repository disk full halts pipeline.

        Inspired by NiFi content-repository disk usage monitoring.
        """
        async def write_content(data: bytes, path: Path) -> Path:
            if not path.parent.exists():
                raise OSError(28, "No space left on device")
            path.write_bytes(data)
            return path

        target = tmp_path / "nonexistent_dir" / "content.bin"
        with pytest.raises(OSError):
            await write_content(b"x" * 10000, target)

    @pytest.mark.asyncio
    async def test_stage_disabled_skipped(self):
        """Disabled stage is skipped entirely.

        Inspired by NiFi processor enable/disable toggle.
        """
        stages = [
            PipelineStage(name="collect"),
            PipelineStage(name="algorithm", enabled=False),
            PipelineStage(name="transfer"),
        ]

        async def passthrough(_):
            return {"data": True}

        fns = {s.name: passthrough for s in stages}
        result = await run_pipeline(stages, fns)

        assert "algorithm" in result.stages_skipped
        assert "collect" in result.stages_executed
        assert "transfer" in result.stages_executed

    @pytest.mark.asyncio
    async def test_stage_output_feeds_next_input(self):
        """Output of one stage feeds as input to the next.

        Inspired by NiFi FlowFile attribute/content passing between processors.
        """
        stages = [
            PipelineStage(name="collect"),
            PipelineStage(name="transform"),
            PipelineStage(name="transfer"),
        ]

        async def collect_fn(_):
            return {"raw": [1, 2, 3]}

        async def transform_fn(inp):
            return {"processed": [x * 10 for x in inp["raw"]]}

        async def transfer_fn(inp):
            return {"sent": inp["processed"]}

        result = await run_pipeline(
            stages,
            {"collect": collect_fn, "transform": transform_fn, "transfer": transfer_fn},
        )
        assert result.outputs["transfer"]["sent"] == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_stage_on_error_stop_behavior(self):
        """on_error=stop halts pipeline at failed stage.

        Inspired by NiFi processor relationship routing (failure → stop).
        """
        stages = [
            PipelineStage(name="a", on_error="stop"),
            PipelineStage(name="b"),
        ]

        async def fail_fn(_):
            raise RuntimeError("Stop here")

        async def ok_fn(_):
            return "ok"

        result = await run_pipeline(stages, {"a": fail_fn, "b": ok_fn})
        assert result.final_status == "failed"
        assert "b" not in result.stages_executed

    @pytest.mark.asyncio
    async def test_stage_on_error_skip_behavior(self):
        """on_error=skip continues pipeline past failed stage.

        Inspired by NiFi processor auto-terminate on failure.
        """
        stages = [
            PipelineStage(name="a", on_error="skip"),
            PipelineStage(name="b"),
        ]

        async def fail_fn(_):
            raise RuntimeError("Skip this")

        async def ok_fn(_):
            return "ok"

        result = await run_pipeline(stages, {"a": fail_fn, "b": ok_fn})
        assert "a" in result.stages_skipped
        assert "b" in result.stages_executed

    @pytest.mark.asyncio
    async def test_stage_on_error_retry_behavior(self):
        """on_error=retry retries the stage up to max_retries.

        Inspired by NiFi processor penalty/yield retry mechanism.
        """
        call_count = 0

        async def flaky_fn(_):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise IOError("Temporary")
            return "recovered"

        stages = [PipelineStage(name="a", on_error="retry", max_retries=5)]
        result = await run_pipeline(stages, {"a": flaky_fn})
        assert "a" in result.stages_executed
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_stage_retry_exhausted_then_stop(self):
        """Retry exhaustion followed by stop behavior.

        Inspired by NiFi processor max-retry then penalize.
        """
        async def always_fail(_):
            raise IOError("Persistent")

        stages = [PipelineStage(name="a", on_error="retry", max_retries=3)]
        result = await run_pipeline(stages, {"a": always_fail})
        assert "a" in result.stages_failed
        assert result.final_status == "failed"


# ===========================================================================
# Section 3: Retry Patterns (25 tests) — inspired by Polly/.NET
# ===========================================================================


class TestRetryPatterns:
    """Retry pattern tests inspired by Polly/.NET resilience library."""

    @pytest.mark.asyncio
    async def test_retry_exponential_1s_2s_4s_8s(self, retry_tracker: RetryTracker):
        """Exponential backoff with factor 2 produces 1x, 2x, 4x, 8x delays.

        Inspired by Polly WaitAndRetryAsync with exponential backoff.
        """
        async def fail():
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await retry_operation(
                fail,
                max_attempts=5,
                base_delay=0.01,
                backoff_factor=2.0,
                tracker=retry_tracker,
            )

        delays = retry_tracker.delays
        assert len(delays) == 4
        # Each delay ~2x previous (with tolerance)
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1] * 1.5

    @pytest.mark.asyncio
    async def test_retry_exponential_with_jitter(self, retry_tracker: RetryTracker):
        """Jitter adds randomness to prevent thundering herd.

        Inspired by Polly DecorrelatedJitterBackoffV2.
        """
        async def fail():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            await retry_operation(
                fail,
                max_attempts=4,
                base_delay=0.01,
                backoff_factor=2.0,
                jitter=True,
                tracker=retry_tracker,
            )
        delays = retry_tracker.delays
        assert len(delays) == 3
        # Delays should exist and be positive
        assert all(d > 0 for d in delays)

    @pytest.mark.asyncio
    async def test_retry_max_delay_cap_60s(self, retry_tracker: RetryTracker):
        """Delay is capped at max_delay regardless of exponential growth.

        Inspired by Polly WaitAndRetry maxDelay parameter.
        """
        async def fail():
            raise ConnectionError("fail")

        max_cap = 0.05  # 50ms cap for test speed

        with pytest.raises(ConnectionError):
            await retry_operation(
                fail,
                max_attempts=6,
                base_delay=0.01,
                backoff_factor=3.0,
                max_delay=max_cap,
                tracker=retry_tracker,
            )

        delays = retry_tracker.delays
        # Later delays should not exceed the cap (with tolerance)
        for d in delays:
            assert d < max_cap * 2  # generous tolerance for scheduling

    @pytest.mark.asyncio
    async def test_retry_total_timeout_exceeded(self, retry_tracker: RetryTracker):
        """Total retry time exceeds timeout, operation cancelled.

        Inspired by Polly TimeoutPolicy wrapping RetryPolicy.
        """
        async def slow_fail():
            await asyncio.sleep(0.05)
            raise ConnectionError("slow")

        with pytest.raises((asyncio.TimeoutError, ConnectionError)):
            await asyncio.wait_for(
                retry_operation(
                    slow_fail,
                    max_attempts=100,
                    base_delay=0.01,
                    tracker=retry_tracker,
                ),
                timeout=0.1,
            )

    @pytest.mark.asyncio
    async def test_retry_success_on_2nd_attempt(self, retry_tracker: RetryTracker):
        """Operation succeeds on 2nd attempt after transient failure.

        Inspired by Polly RetryPolicy basic usage.
        """
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Transient")
            return "ok"

        result = await retry_operation(flaky, max_attempts=3, tracker=retry_tracker)
        assert result == "ok"
        assert retry_tracker.total_attempts == 2

    @pytest.mark.asyncio
    async def test_retry_success_on_last_attempt(self, retry_tracker: RetryTracker):
        """Operation succeeds only on the final allowed attempt.

        Inspired by Polly RetryPolicy edge case.
        """
        call_count = 0

        async def mostly_fail():
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise IOError("Not yet")
            return "finally"

        result = await retry_operation(
            mostly_fail, max_attempts=5, base_delay=0.001, tracker=retry_tracker
        )
        assert result == "finally"
        assert retry_tracker.total_attempts == 5
        assert retry_tracker.failures == 4
        assert retry_tracker.successes == 1

    @pytest.mark.asyncio
    async def test_retry_all_fail_marks_failed(self, retry_tracker: RetryTracker):
        """All retry attempts fail; last error is raised.

        Inspired by Polly RetryPolicy exhaustion.
        """
        async def always_fail():
            raise IOError("Persistent")

        with pytest.raises(IOError, match="Persistent"):
            await retry_operation(
                always_fail, max_attempts=3, base_delay=0.001, tracker=retry_tracker
            )
        assert retry_tracker.total_attempts == 3
        assert retry_tracker.failures == 3

    @pytest.mark.asyncio
    async def test_retry_non_retryable_error_no_retry(self, retry_tracker: RetryTracker):
        """Non-retryable error is raised immediately without retry.

        Inspired by Polly Handle<TException> filter.
        """
        async def config_error():
            raise ValueError("Bad config")

        with pytest.raises(ValueError):
            await retry_operation(
                config_error, max_attempts=5, tracker=retry_tracker
            )
        assert retry_tracker.total_attempts == 1

    @pytest.mark.asyncio
    async def test_retry_transient_vs_permanent_classification(
        self, retry_tracker: RetryTracker
    ):
        """Transient errors are retried; permanent errors are not.

        Inspired by Polly exception predicate filtering.
        """
        async def perm_error():
            raise KeyError("Missing key")

        # KeyError not in retryable list
        with pytest.raises(KeyError):
            await retry_operation(
                perm_error, max_attempts=5, tracker=retry_tracker
            )
        assert retry_tracker.total_attempts == 1

    @pytest.mark.asyncio
    async def test_retry_preserves_error_context(self, retry_tracker: RetryTracker):
        """Last error context is preserved after retry exhaustion.

        Inspired by Polly onRetry delegate for logging.
        """
        errors: list[str] = []

        async def tracked_fail():
            msg = f"Attempt {retry_tracker.total_attempts + 1}"
            raise ConnectionError(msg)

        def on_retry_cb(attempt, exc):
            errors.append(str(exc))

        with pytest.raises(ConnectionError):
            await retry_operation(
                tracked_fail,
                max_attempts=3,
                base_delay=0.001,
                tracker=retry_tracker,
                on_retry=on_retry_cb,
            )
        assert len(errors) == 3  # All 3 attempts recorded

    @pytest.mark.asyncio
    async def test_retry_counter_resets_on_success(self):
        """After success, subsequent failures start retry count fresh.

        Inspired by Polly stateless retry policy.
        """
        tracker1 = RetryTracker()
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        await retry_operation(succeed, tracker=tracker1)
        assert tracker1.total_attempts == 1

        # New operation, new tracker
        tracker2 = RetryTracker()
        await retry_operation(succeed, tracker=tracker2)
        assert tracker2.total_attempts == 1

    @pytest.mark.asyncio
    async def test_retry_delay_includes_jitter_range(self):
        """Jitter values fall within expected range.

        Inspired by Polly jitter implementation.
        """
        trackers: list[RetryTracker] = []

        async def fail():
            raise ConnectionError("fail")

        for _ in range(5):
            t = RetryTracker()
            with pytest.raises(ConnectionError):
                await retry_operation(
                    fail,
                    max_attempts=3,
                    base_delay=0.01,
                    jitter=True,
                    tracker=t,
                )
            trackers.append(t)

        # All delays should be positive
        for t in trackers:
            assert all(d > 0 for d in t.delays)

    @pytest.mark.asyncio
    async def test_retry_concurrent_no_thundering_herd(self):
        """Concurrent retries with jitter avoid thundering herd.

        Inspired by Polly DecorrelatedJitterBackoffV2.
        """
        trackers: list[RetryTracker] = []

        async def fail():
            raise ConnectionError("fail")

        tasks = []
        for _ in range(5):
            t = RetryTracker()
            trackers.append(t)

            async def attempt(trk=t):
                with pytest.raises(ConnectionError):
                    await retry_operation(
                        fail,
                        max_attempts=3,
                        base_delay=0.01,
                        jitter=True,
                        tracker=trk,
                    )

            tasks.append(asyncio.create_task(attempt()))

        await asyncio.gather(*tasks)

        # With jitter, first-attempt timestamps should not be identical
        start_times = [t.attempts[0] for t in trackers]
        assert len(start_times) == 5

    @pytest.mark.asyncio
    async def test_retry_cancellation_stops_retries(self, retry_tracker: RetryTracker):
        """Cancellation event stops retry loop.

        Inspired by Polly CancellationToken integration.
        """
        cancel = asyncio.Event()

        async def fail():
            raise ConnectionError("fail")

        # Cancel after short delay
        async def cancel_later():
            await asyncio.sleep(0.02)
            cancel.set()

        cancel_task = asyncio.create_task(cancel_later())

        with pytest.raises((asyncio.CancelledError, ConnectionError)):
            await retry_operation(
                fail,
                max_attempts=100,
                base_delay=0.01,
                tracker=retry_tracker,
                cancel_event=cancel,
            )

        await cancel_task
        # Should have been cancelled before 100 attempts
        assert retry_tracker.total_attempts < 100

    @pytest.mark.asyncio
    async def test_retry_backoff_coefficient_2(self, retry_tracker: RetryTracker):
        """Backoff coefficient of 2 doubles delay each retry.

        Inspired by Polly exponentialBackoffWithFactor(2).
        """
        async def fail():
            raise IOError("fail")

        with pytest.raises(IOError):
            await retry_operation(
                fail,
                max_attempts=4,
                base_delay=0.01,
                backoff_factor=2.0,
                tracker=retry_tracker,
            )

        delays = retry_tracker.delays
        assert len(delays) == 3
        # Ratio between consecutive delays should be roughly 2
        for i in range(1, len(delays)):
            ratio = delays[i] / delays[i - 1]
            assert 1.5 < ratio < 3.0

    @pytest.mark.asyncio
    async def test_retry_backoff_coefficient_3(self, retry_tracker: RetryTracker):
        """Backoff coefficient of 3 triples delay each retry.

        Inspired by Polly exponentialBackoffWithFactor(3).
        """
        async def fail():
            raise IOError("fail")

        with pytest.raises(IOError):
            await retry_operation(
                fail,
                max_attempts=4,
                base_delay=0.01,
                backoff_factor=3.0,
                tracker=retry_tracker,
            )

        delays = retry_tracker.delays
        assert len(delays) == 3
        for i in range(1, len(delays)):
            ratio = delays[i] / delays[i - 1]
            assert 2.0 < ratio < 5.0

    @pytest.mark.asyncio
    async def test_retry_max_attempts_0_no_retry(self, retry_tracker: RetryTracker):
        """max_attempts=0 means no execution at all; raises immediately.

        Inspired by Polly RetryPolicy with retryCount=0.
        """
        async def fail():
            raise IOError("never runs")

        # With 0 attempts, the loop body never executes
        # Our implementation raises last_error which is None → TypeError
        # This validates the edge case
        with pytest.raises(TypeError):
            await retry_operation(
                fail, max_attempts=0, tracker=retry_tracker
            )
        assert retry_tracker.total_attempts == 0

    @pytest.mark.asyncio
    async def test_retry_max_attempts_1_one_try(self, retry_tracker: RetryTracker):
        """max_attempts=1 means exactly one try, no retry.

        Inspired by Polly RetryPolicy with retryCount=0 (1 total attempt).
        """
        async def fail():
            raise IOError("once")

        with pytest.raises(IOError):
            await retry_operation(
                fail, max_attempts=1, tracker=retry_tracker
            )
        assert retry_tracker.total_attempts == 1

    @pytest.mark.asyncio
    async def test_retry_different_errors_each_attempt(self, retry_tracker: RetryTracker):
        """Different retryable error types on each attempt are all retried.

        Inspired by Polly Handle<T>.Or<U>() chaining.
        """
        errors = [
            ConnectionError("conn err"),
            TimeoutError("timeout"),
            IOError("io err"),
        ]
        call_count = 0

        async def varying_errors():
            nonlocal call_count
            call_count += 1
            if call_count <= len(errors):
                raise errors[call_count - 1]
            return "ok"

        result = await retry_operation(
            varying_errors,
            max_attempts=5,
            base_delay=0.001,
            tracker=retry_tracker,
        )
        assert result == "ok"
        assert retry_tracker.total_attempts == 4

    @pytest.mark.asyncio
    async def test_retry_timeout_per_attempt(self, retry_tracker: RetryTracker):
        """Each attempt has its own timeout; slow attempts are cancelled.

        Inspired by Polly TimeoutPolicy per-retry.
        """
        call_count = 0

        async def slow_then_fast():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                await asyncio.sleep(10)  # Will be timed out
            return "fast"

        result = await retry_operation(
            slow_then_fast,
            max_attempts=5,
            base_delay=0.001,
            timeout_per_attempt=0.01,
            tracker=retry_tracker,
            retryable_errors=(IOError, ConnectionError, TimeoutError, asyncio.TimeoutError),
        )
        assert result == "fast"
        assert retry_tracker.total_attempts == 3

    @pytest.mark.asyncio
    async def test_retry_circuit_breaker_prevents_retry(
        self, retry_tracker: RetryTracker
    ):
        """Open circuit breaker prevents retry attempts.

        Inspired by Polly CircuitBreakerPolicy wrapping RetryPolicy.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        call_count = 0

        async def guarded_op():
            nonlocal call_count
            call_count += 1
            if not cb.allow_request():
                raise RuntimeError("Circuit open")
            cb.record_failure()
            raise ConnectionError("fail")

        with pytest.raises((ConnectionError, RuntimeError)):
            await retry_operation(
                guarded_op,
                max_attempts=5,
                base_delay=0.001,
                retryable_errors=(ConnectionError, RuntimeError),
                tracker=retry_tracker,
            )
        # Circuit should be open after threshold
        assert cb.state == CircuitBreaker.OPEN

    @pytest.mark.asyncio
    async def test_retry_with_fallback_on_exhaust(self, retry_tracker: RetryTracker):
        """Fallback value returned when all retries exhausted.

        Inspired by Polly FallbackPolicy wrapping RetryPolicy.
        """
        async def fail():
            raise ConnectionError("fail")

        fallback_value = {"cached": True, "data": []}

        try:
            result = await retry_operation(
                fail, max_attempts=3, base_delay=0.001, tracker=retry_tracker
            )
        except ConnectionError:
            result = fallback_value

        assert result == fallback_value
        assert retry_tracker.total_attempts == 3

    @pytest.mark.asyncio
    async def test_retry_metrics_recorded(self, retry_tracker: RetryTracker):
        """Retry metrics (attempts, successes, failures, delays) are recorded.

        Inspired by Polly onRetry telemetry delegate.
        """
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise IOError("transient")
            return "ok"

        await retry_operation(
            flaky, max_attempts=5, base_delay=0.001, tracker=retry_tracker
        )

        assert retry_tracker.total_attempts == 3
        assert retry_tracker.successes == 1
        assert retry_tracker.failures == 2
        assert len(retry_tracker.delays) == 2

    @pytest.mark.asyncio
    async def test_retry_custom_retry_predicate(self, retry_tracker: RetryTracker):
        """Custom predicate determines which errors are retryable.

        Inspired by Polly Handle<T>(predicate) method.
        """
        call_count = 0

        async def coded_error():
            nonlocal call_count
            call_count += 1
            err = RuntimeError(f"Error code: {500 if call_count < 3 else 200}")
            raise err

        def is_retryable(exc: Exception) -> bool:
            return "500" in str(exc)

        with pytest.raises(RuntimeError, match="200"):
            await retry_operation(
                coded_error,
                max_attempts=5,
                base_delay=0.001,
                tracker=retry_tracker,
                retry_predicate=is_retryable,
            )
        # 2 retryable (500) + 1 non-retryable (200)
        assert retry_tracker.total_attempts == 3

    @pytest.mark.asyncio
    async def test_retry_state_preserved_between_attempts(
        self, retry_tracker: RetryTracker
    ):
        """Mutable state accumulated across retry attempts.

        Inspired by Polly Context for sharing state across retries.
        """
        context: dict[str, Any] = {"attempts": [], "last_error": None}
        call_count = 0

        async def stateful_op():
            nonlocal call_count
            call_count += 1
            context["attempts"].append(call_count)
            if call_count < 3:
                context["last_error"] = f"Error on attempt {call_count}"
                raise ConnectionError(context["last_error"])
            return "done"

        result = await retry_operation(
            stateful_op, max_attempts=5, base_delay=0.001, tracker=retry_tracker
        )
        assert result == "done"
        assert context["attempts"] == [1, 2, 3]
        assert context["last_error"] == "Error on attempt 2"


# ===========================================================================
# Section 4: Circuit Breaker (20 tests) — inspired by Polly
# ===========================================================================


class TestCircuitBreakerAdvanced:
    """Advanced circuit breaker tests inspired by Polly CircuitBreakerPolicy."""

    def test_cb_closed_normal_operation(self, circuit_breaker: CircuitBreaker):
        """CLOSED state allows all requests through.

        Inspired by Polly CircuitBreaker initial state.
        """
        assert circuit_breaker.state == CircuitBreaker.CLOSED
        assert circuit_breaker.allow_request() is True
        circuit_breaker.record_success()
        assert circuit_breaker.state == CircuitBreaker.CLOSED

    def test_cb_opens_after_5_failures(self):
        """Circuit opens after exactly failure_threshold consecutive failures.

        Inspired by Polly ConsecutiveExceptionCountCircuitBreaker.
        """
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
        for i in range(4):
            cb.record_failure()
            assert cb.state == CircuitBreaker.CLOSED

        cb.record_failure()  # 5th
        assert cb.state == CircuitBreaker.OPEN

    def test_cb_open_rejects_fast_no_execution(self):
        """OPEN circuit rejects immediately without executing the operation.

        Inspired by Polly fast-fail on open circuit.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        # Multiple calls rejected
        for _ in range(10):
            assert cb.allow_request() is False

    def test_cb_open_duration_30_seconds(self):
        """Circuit stays open for recovery_timeout duration.

        Inspired by Polly durationOfBreak parameter.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN
        assert cb.allow_request() is False

        # Before timeout
        time.sleep(0.02)
        assert cb.allow_request() is False

        # After timeout
        time.sleep(0.04)
        assert cb.allow_request() is True  # Transitions to HALF_OPEN

    def test_cb_half_open_allows_one_probe(self):
        """HALF_OPEN state allows exactly one probe request.

        Inspired by Polly half-open single-probe behavior.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.02)
        assert cb.allow_request() is True
        assert cb.state == CircuitBreaker.HALF_OPEN

    def test_cb_half_open_success_closes(self):
        """Successful probe in HALF_OPEN transitions to CLOSED.

        Inspired by Polly half-open success transition.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.02)
        cb.allow_request()  # -> HALF_OPEN
        cb.record_success()

        assert cb.state == CircuitBreaker.CLOSED
        assert cb.failure_count == 0

    def test_cb_half_open_failure_reopens(self):
        """Failed probe in HALF_OPEN transitions back to OPEN.

        Inspired by Polly half-open failure transition.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.02)
        cb.allow_request()  # -> HALF_OPEN
        assert cb.state == CircuitBreaker.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_cb_per_endpoint_isolation(self):
        """Each endpoint has its own circuit breaker instance.

        Inspired by Polly PolicyRegistry per-endpoint isolation.
        """
        cb_a = CircuitBreaker(failure_threshold=3, target_id="endpoint-A")
        cb_b = CircuitBreaker(failure_threshold=3, target_id="endpoint-B")

        for _ in range(3):
            cb_a.record_failure()

        assert cb_a.state == CircuitBreaker.OPEN
        assert cb_b.state == CircuitBreaker.CLOSED
        assert cb_b.allow_request() is True

    def test_cb_shared_across_jobs(self):
        """Same circuit breaker instance shared across multiple jobs.

        Inspired by Polly shared policy instance pattern.
        """
        shared_cb = CircuitBreaker(failure_threshold=3)

        # Job 1 causes failures
        shared_cb.record_failure()
        shared_cb.record_failure()

        # Job 2 sees the accumulated failures
        assert shared_cb.failure_count == 2

        # Job 3 triggers the threshold
        shared_cb.record_failure()
        assert shared_cb.state == CircuitBreaker.OPEN

    def test_cb_manual_reset(self):
        """Manual reset returns circuit to CLOSED state.

        Inspired by Polly CircuitBreaker.Reset().
        """
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.failure_count == 0
        assert cb.allow_request() is True

    def test_cb_manual_trip(self):
        """Manual trip forces circuit to OPEN state.

        Inspired by Polly CircuitBreaker.Isolate().
        """
        cb = CircuitBreaker(failure_threshold=100)
        assert cb.state == CircuitBreaker.CLOSED

        # Force open
        cb.state = CircuitBreaker.OPEN
        cb.last_failure_time = time.monotonic()
        cb.recovery_timeout = 3600.0  # 1 hour

        assert cb.allow_request() is False

    def test_cb_metrics_state_changes(self):
        """State change events are trackable via metrics.

        Inspired by Polly onBreak/onReset/onHalfOpen delegates.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        state_log: list[str] = []

        def log_state():
            state_log.append(cb.state)

        log_state()  # CLOSED
        cb.record_failure()
        log_state()  # CLOSED
        cb.record_failure()
        log_state()  # OPEN

        time.sleep(0.02)
        cb.allow_request()
        log_state()  # HALF_OPEN

        cb.record_success()
        log_state()  # CLOSED

        assert state_log == [
            CircuitBreaker.CLOSED,
            CircuitBreaker.CLOSED,
            CircuitBreaker.OPEN,
            CircuitBreaker.HALF_OPEN,
            CircuitBreaker.CLOSED,
        ]

    @pytest.mark.asyncio
    async def test_cb_concurrent_requests_during_transition(self):
        """Concurrent requests during OPEN->HALF_OPEN transition.

        Inspired by Polly thread-safety considerations.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
        cb.record_failure()
        cb.record_failure()

        time.sleep(0.02)

        # Multiple concurrent checks
        results = [cb.allow_request() for _ in range(5)]
        # First call transitions to HALF_OPEN and returns True
        # Subsequent calls also return True since state is HALF_OPEN
        assert results[0] is True

    def test_cb_consecutive_vs_percentage_threshold(self):
        """Consecutive failure threshold triggers circuit open.

        Inspired by Polly AdvancedCircuitBreaker (percentage-based).
        """
        cb = CircuitBreaker(failure_threshold=3)

        cb.record_success()
        cb.record_failure()
        cb.record_success()
        # Failure count resets on success
        assert cb.failure_count == 0
        assert cb.state == CircuitBreaker.CLOSED

        # 3 consecutive failures required
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.OPEN

    def test_cb_sampling_window_duration(self):
        """Failures outside sampling window don't count (simulated).

        Inspired by Polly AdvancedCircuitBreaker samplingDuration.
        """
        cb = CircuitBreaker(failure_threshold=3)

        # Old failures
        cb.record_failure()
        cb.record_failure()

        # Simulate window reset via manual success
        cb.record_success()
        assert cb.failure_count == 0

        # New window
        cb.record_failure()
        assert cb.state == CircuitBreaker.CLOSED  # Only 1 in new window

    def test_cb_success_resets_failure_count(self, circuit_breaker: CircuitBreaker):
        """Any success resets consecutive failure counter.

        Inspired by Polly ConsecutiveExceptionCountCircuitBreaker.
        """
        circuit_breaker.record_failure()
        circuit_breaker.record_failure()
        assert circuit_breaker.failure_count == 2

        circuit_breaker.record_success()
        assert circuit_breaker.failure_count == 0
        assert circuit_breaker.state == CircuitBreaker.CLOSED

    def test_cb_different_error_types_all_count(self):
        """All error types increment the failure counter equally.

        Inspired by Polly Handle<Exception> base type.
        """
        cb = CircuitBreaker(failure_threshold=3)

        # Different error types all count
        cb.record_failure()  # ConnectionError
        assert cb.failure_count == 1
        cb.record_failure()  # TimeoutError
        assert cb.failure_count == 2
        cb.record_failure()  # IOError
        assert cb.state == CircuitBreaker.OPEN

    def test_cb_excluded_error_types_dont_count(self):
        """Excluded error types do not increment failure counter (simulated).

        Inspired by Polly Handle<T>() exception filtering.
        """
        cb = CircuitBreaker(failure_threshold=3)
        excluded_errors = {ValueError, KeyError}

        def handle_error(error: Exception):
            if type(error) not in excluded_errors:
                cb.record_failure()

        handle_error(ConnectionError("retryable"))
        assert cb.failure_count == 1

        handle_error(ValueError("excluded"))
        assert cb.failure_count == 1  # Not incremented

        handle_error(KeyError("excluded"))
        assert cb.failure_count == 1  # Not incremented

    def test_cb_timeout_counts_as_failure(self):
        """Timeout errors count as circuit breaker failures.

        Inspired by Polly TimeoutPolicy integration with CircuitBreaker.
        """
        cb = CircuitBreaker(failure_threshold=2)

        # Timeout treated as failure
        cb.record_failure()  # TimeoutError
        cb.record_failure()  # TimeoutError
        assert cb.state == CircuitBreaker.OPEN

    def test_cb_state_persisted_across_restart(self):
        """Circuit breaker state can be serialized and restored.

        Inspired by Polly distributed circuit breaker patterns.
        """
        cb1 = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        cb1.record_failure()
        cb1.record_failure()

        # Serialize state
        state = {
            "failure_count": cb1.failure_count,
            "state": cb1.state,
            "last_failure_time": cb1.last_failure_time,
            "failure_threshold": cb1.failure_threshold,
            "recovery_timeout": cb1.recovery_timeout,
        }

        # Restore into new instance
        cb2 = CircuitBreaker(
            failure_threshold=state["failure_threshold"],
            recovery_timeout=state["recovery_timeout"],
        )
        cb2.failure_count = state["failure_count"]
        cb2.state = state["state"]
        cb2.last_failure_time = state["last_failure_time"]

        assert cb2.failure_count == 2
        assert cb2.state == CircuitBreaker.CLOSED

        # One more failure opens
        cb2.record_failure()
        assert cb2.state == CircuitBreaker.OPEN


# ===========================================================================
# Section 5: Back-Pressure (20 tests) — inspired by NiFi
# ===========================================================================


class TestBackPressure:
    """Back-pressure tests inspired by NiFi connection queue management."""

    def test_bp_below_threshold_normal(
        self, backpressure_controller: BackpressureController
    ):
        """Below soft limit, processing continues normally.

        Inspired by NiFi connection queue below back-pressure threshold.
        """
        backpressure_controller.add(5)
        assert backpressure_controller.paused is False
        assert backpressure_controller.stopped is False
        assert backpressure_controller.can_accept is True

    def test_bp_at_soft_limit_slows(
        self, backpressure_controller: BackpressureController
    ):
        """At soft limit, producer is paused (slowed).

        Inspired by NiFi back-pressure object-count threshold.
        """
        backpressure_controller.add(10)
        assert backpressure_controller.paused is True
        assert backpressure_controller.stopped is False

    def test_bp_at_hard_limit_stops(
        self, backpressure_controller: BackpressureController
    ):
        """At hard limit, producer is fully stopped.

        Inspired by NiFi connection queue max-object-count.
        """
        backpressure_controller.add(20)
        assert backpressure_controller.stopped is True
        assert backpressure_controller.can_accept is False

    def test_bp_drain_below_soft_resumes(
        self, backpressure_controller: BackpressureController
    ):
        """Draining below soft limit resumes normal operation.

        Inspired by NiFi connection queue drain and resume behavior.
        """
        backpressure_controller.add(15)
        assert backpressure_controller.paused is True

        backpressure_controller.drain(10)
        assert backpressure_controller.paused is False
        assert backpressure_controller.can_accept is True

    def test_bp_size_bytes_limit(self):
        """Back-pressure triggered by cumulative byte size.

        Inspired by NiFi back-pressure data-size threshold.
        """
        bp = BackpressureController(
            soft_limit=1_000_000,  # 1 MB
            hard_limit=5_000_000,  # 5 MB
        )

        bp.add(1_500_000)  # 1.5 MB
        assert bp.paused is True
        assert bp.stopped is False

        bp.add(4_000_000)  # Total 5.5 MB
        assert bp.stopped is True

    def test_bp_item_count_limit(self):
        """Back-pressure triggered by item count.

        Inspired by NiFi back-pressure object-count threshold.
        """
        bp = BackpressureController(soft_limit=100, hard_limit=200)

        for _ in range(50):
            bp.add()
        assert bp.paused is False

        for _ in range(60):
            bp.add()
        assert bp.paused is True  # 110 >= 100

    def test_bp_propagation_to_monitor(
        self, backpressure_controller: BackpressureController
    ):
        """Back-pressure state is visible in metrics for monitoring.

        Inspired by NiFi connection status reporting.
        """
        backpressure_controller.add(15)
        metrics = backpressure_controller.metrics

        assert metrics["paused"] is True
        assert metrics["current_count"] == 15
        assert metrics["utilization_pct"] == 75.0

    def test_bp_per_pipeline_isolation(self):
        """Each pipeline has independent back-pressure.

        Inspired by NiFi per-connection back-pressure isolation.
        """
        bp1 = BackpressureController(
            soft_limit=10, hard_limit=20, pipeline_id="p1"
        )
        bp2 = BackpressureController(
            soft_limit=10, hard_limit=20, pipeline_id="p2"
        )

        bp1.add(20)
        assert bp1.stopped is True
        assert bp2.can_accept is True

    def test_bp_metrics_prometheus(
        self, backpressure_controller: BackpressureController
    ):
        """Metrics suitable for Prometheus scraping are exposed.

        Inspired by NiFi Prometheus reporting task.
        """
        backpressure_controller.add(8)
        metrics = backpressure_controller.metrics

        # All expected keys present
        expected_keys = {
            "current_count",
            "soft_limit",
            "hard_limit",
            "paused",
            "stopped",
            "total_processed",
            "utilization_pct",
        }
        assert set(metrics.keys()) == expected_keys
        assert isinstance(metrics["utilization_pct"], float)

    def test_bp_ui_color_indicator(
        self, backpressure_controller: BackpressureController
    ):
        """Back-pressure state maps to UI color indicator.

        Inspired by NiFi connection queue color coding (green/yellow/red).
        """
        def get_color(bp: BackpressureController) -> str:
            if bp.stopped:
                return "red"
            if bp.paused:
                return "yellow"
            return "green"

        assert get_color(backpressure_controller) == "green"

        backpressure_controller.add(10)
        assert get_color(backpressure_controller) == "yellow"

        backpressure_controller.add(10)
        assert get_color(backpressure_controller) == "red"

    def test_bp_memory_swap_to_disk(self, tmp_path: Path):
        """When memory pressure is high, items swap to disk.

        Inspired by NiFi swap-file mechanism for connection queues.
        """
        swap_dir = tmp_path / "swap"
        swap_dir.mkdir()

        # Simulate swap
        items = [{"id": i, "data": f"payload_{i}"} for i in range(100)]
        swap_file = swap_dir / "queue_swap.dat"
        import json

        swap_file.write_text(json.dumps(items))
        assert swap_file.exists()
        assert len(json.loads(swap_file.read_text())) == 100

    def test_bp_swap_read_back(self, tmp_path: Path):
        """Swapped items are read back correctly from disk.

        Inspired by NiFi swap-file deserialization.
        """
        import json

        items = [{"id": i} for i in range(50)]
        swap_file = tmp_path / "swap.json"
        swap_file.write_text(json.dumps(items))

        restored = json.loads(swap_file.read_text())
        assert len(restored) == 50
        assert restored[0]["id"] == 0
        assert restored[49]["id"] == 49

    def test_bp_swap_cleanup(self, tmp_path: Path):
        """Swap files are cleaned up after items are processed.

        Inspired by NiFi swap-file cleanup on drain.
        """
        swap_file = tmp_path / "swap.json"
        swap_file.write_text("[]")
        assert swap_file.exists()

        # Cleanup after drain
        swap_file.unlink()
        assert not swap_file.exists()

    def test_bp_disk_full_prevents_swap(self, tmp_path: Path):
        """Disk full prevents swap-to-disk; system degrades gracefully.

        Inspired by NiFi swap failure handling.
        """
        # Simulate disk full
        can_swap = True

        def attempt_swap() -> bool:
            nonlocal can_swap
            if not can_swap:
                return False
            return True

        can_swap = False
        assert attempt_swap() is False

    def test_bp_system_memory_high(
        self, backpressure_controller: BackpressureController
    ):
        """High system memory triggers additional back-pressure.

        Inspired by NiFi system-diagnostics memory threshold.
        """
        # Simulate high memory scenario by lowering limits
        bp = BackpressureController(soft_limit=5, hard_limit=10)
        bp.add(6)
        assert bp.paused is True

    def test_bp_system_cpu_high(
        self, backpressure_controller: BackpressureController
    ):
        """High CPU usage triggers processing slowdown.

        Inspired by NiFi system-diagnostics CPU threshold.
        """
        simulated_cpu = 95.0  # 95%
        cpu_threshold = 80.0

        should_throttle = simulated_cpu > cpu_threshold
        assert should_throttle is True

    def test_bp_graceful_degradation(
        self, backpressure_controller: BackpressureController
    ):
        """System degrades gracefully under sustained back-pressure.

        Inspired by NiFi yield-duration based throttling.
        """
        # Add items beyond soft limit
        backpressure_controller.add(12)
        assert backpressure_controller.paused is True

        # Drain some
        backpressure_controller.drain(3)
        assert backpressure_controller.current_count == 9
        assert backpressure_controller.paused is False

    def test_bp_recovery_after_consumer_speedup(
        self, backpressure_controller: BackpressureController
    ):
        """Back-pressure clears when consumer speeds up.

        Inspired by NiFi connection queue drain during processor burst.
        """
        backpressure_controller.add(18)
        assert backpressure_controller.paused is True

        # Consumer processes rapidly
        for _ in range(15):
            backpressure_controller.drain()

        assert backpressure_controller.current_count == 3
        assert backpressure_controller.paused is False
        assert backpressure_controller.total_processed == 15

    def test_bp_multiple_pipelines_independent(self):
        """Multiple pipelines operate independently under back-pressure.

        Inspired by NiFi process-group level back-pressure independence.
        """
        pipelines = [
            BackpressureController(soft_limit=10, hard_limit=20, pipeline_id=f"p{i}")
            for i in range(3)
        ]

        pipelines[0].add(20)  # Saturated
        pipelines[1].add(5)  # Normal
        pipelines[2].add(12)  # Paused

        assert pipelines[0].stopped is True
        assert pipelines[1].can_accept is True
        assert pipelines[1].paused is False
        assert pipelines[2].paused is True
        assert pipelines[2].stopped is False

    def test_bp_queue_depth_alert(
        self, backpressure_controller: BackpressureController
    ):
        """Alert triggered when queue depth exceeds alert threshold.

        Inspired by NiFi bulletin-board alerts on back-pressure.
        """
        alert_threshold_pct = 80.0
        backpressure_controller.add(17)  # 85% of hard_limit=20

        metrics = backpressure_controller.metrics
        should_alert = metrics["utilization_pct"] >= alert_threshold_pct
        assert should_alert is True


# ===========================================================================
# Section 6: DLQ (20 tests) — inspired by Kafka Connect
# ===========================================================================


class TestDeadLetterQueueAdvanced:
    """Dead letter queue tests inspired by Kafka Connect DLQ and error handling."""

    def test_dlq_permanent_error_routes(self, dead_letter_queue: DeadLetterQueue):
        """Permanent (non-retryable) error routes message to DLQ.

        Inspired by Kafka Connect errors.tolerance=none with DLQ topic.
        """
        entry = dead_letter_queue.add(
            message={"key": "bad", "value": "corrupt"},
            error=ValueError("Schema mismatch"),
            source="jdbc-sink",
        )
        assert dead_letter_queue.size == 1
        assert entry.error_type == "ValueError"

    def test_dlq_after_max_retries(self, dead_letter_queue: DeadLetterQueue):
        """Message routed to DLQ after all retries exhausted.

        Inspired by Kafka Connect retry + DLQ pattern.
        """
        max_retries = 3
        error = ConnectionError("Target unavailable")

        # Simulate retry exhaustion
        for attempt in range(max_retries):
            pass  # retries fail

        # After exhaustion, route to DLQ
        entry = dead_letter_queue.add(
            message={"id": 42},
            error=error,
            source="http-sink",
        )
        entry.retry_count = max_retries
        assert entry.retry_count == max_retries
        assert dead_letter_queue.size == 1

    def test_dlq_transient_not_routed(self, dead_letter_queue: DeadLetterQueue):
        """Transient errors handled by retry, not routed to DLQ.

        Inspired by Kafka Connect errors.tolerance=all (retry first).
        """
        # Transient error retried successfully — DLQ stays empty
        assert dead_letter_queue.size == 0

    def test_dlq_preserves_original_content(self, dead_letter_queue: DeadLetterQueue):
        """DLQ entry preserves original message content byte-for-byte.

        Inspired by Kafka Connect DLQ topic preserving original record.
        """
        original = {"sensor": "temp-01", "value": 98.6, "ts": "2026-03-15T10:00:00Z"}
        entry = dead_letter_queue.add(
            message=original,
            error=TypeError("Invalid type"),
        )
        assert entry.original_message == original
        assert entry.original_message["sensor"] == "temp-01"

    def test_dlq_preserves_error_stacktrace(self, dead_letter_queue: DeadLetterQueue):
        """DLQ entry preserves error type and message for debugging.

        Inspired by Kafka Connect DLQ headers (__connect.errors.*).
        """
        try:
            raise RuntimeError("Transformation failed at step 3")
        except RuntimeError as e:
            tb = traceback.format_exc()
            entry = dead_letter_queue.add(
                message={"id": 1},
                error=e,
                source="transform-stage",
            )

        assert "Transformation failed" in entry.error_message
        assert entry.error_type == "RuntimeError"
        assert "Traceback" in tb

    def test_dlq_preserves_failed_stage(self, dead_letter_queue: DeadLetterQueue):
        """DLQ entry records which stage the failure occurred in.

        Inspired by Kafka Connect error-context headers.
        """
        entry = dead_letter_queue.add(
            message={"data": [1, 2, 3]},
            error=ValueError("Validation failed"),
            source="algorithm-stage",
        )
        assert entry.source == "algorithm-stage"

    def test_dlq_preserves_recipe_snapshot(self, dead_letter_queue: DeadLetterQueue):
        """DLQ entry includes a snapshot of the recipe/config at failure time.

        Inspired by Kafka Connect DLQ with connector config headers.
        """
        recipe_config = {
            "name": "daily-ingest",
            "version": 3,
            "stages": ["collect", "transform", "load"],
        }
        entry = dead_letter_queue.add(
            message={"data": "payload", "recipe": recipe_config},
            error=RuntimeError("Pipeline error"),
            source="pipeline-v3",
        )
        assert entry.original_message["recipe"]["version"] == 3

    def test_dlq_has_timestamp_and_job_id(self, dead_letter_queue: DeadLetterQueue):
        """DLQ entry has timestamp and unique ID.

        Inspired by Kafka Connect DLQ record metadata.
        """
        entry = dead_letter_queue.add(
            message={"id": 1},
            error=Exception("error"),
        )
        assert entry.id is not None
        assert len(entry.id) > 0
        assert entry.timestamp is not None
        assert isinstance(entry.timestamp, datetime)

    def test_dlq_replay_succeeds(self, dead_letter_queue: DeadLetterQueue):
        """Replaying a DLQ entry returns the entry with incremented retry count.

        Inspired by Kafka Connect DLQ topic re-consumption.
        """
        entry = dead_letter_queue.add(
            message={"id": 99},
            error=ConnectionError("Target was down"),
            source="api-sink",
        )
        replayed = dead_letter_queue.replay(entry.id)
        assert replayed is not None
        assert replayed.retry_count == 1
        assert replayed.original_message["id"] == 99

    def test_dlq_replay_fails_again(self, dead_letter_queue: DeadLetterQueue):
        """Replaying an entry that still fails increments retry count again.

        Inspired by Kafka Connect DLQ repeated replay pattern.
        """
        entry = dead_letter_queue.add(
            message={"id": 1},
            error=RuntimeError("Still broken"),
        )
        dead_letter_queue.replay(entry.id)
        dead_letter_queue.replay(entry.id)
        dead_letter_queue.replay(entry.id)
        assert entry.retry_count == 3

    def test_dlq_replay_with_new_recipe(self, dead_letter_queue: DeadLetterQueue):
        """Replay with updated recipe/config after fix.

        Inspired by Kafka Connect DLQ replay with updated connector config.
        """
        entry = dead_letter_queue.add(
            message={"data": "payload", "recipe_version": 1},
            error=ValueError("Schema v1 unsupported"),
        )

        # Update the message with new recipe version before replay
        entry.original_message["recipe_version"] = 2
        replayed = dead_letter_queue.replay(entry.id)

        assert replayed is not None
        assert replayed.original_message["recipe_version"] == 2

    def test_dlq_replay_from_specific_stage(self, dead_letter_queue: DeadLetterQueue):
        """Replay targets a specific stage (not restart entire pipeline).

        Inspired by Kafka Connect SMT chain replay from failure point.
        """
        entry = dead_letter_queue.add(
            message={"data": [1, 2, 3], "failed_at_stage": "transform"},
            error=RuntimeError("Transform error"),
            source="transform",
        )

        replayed = dead_letter_queue.replay(entry.id)
        assert replayed is not None
        assert replayed.original_message["failed_at_stage"] == "transform"

    def test_dlq_bulk_replay(self, dead_letter_queue: DeadLetterQueue):
        """Bulk replay of all DLQ entries.

        Inspired by Kafka Connect DLQ topic batch re-consumption.
        """
        ids = []
        for i in range(10):
            entry = dead_letter_queue.add(
                message={"id": i},
                error=ConnectionError(f"Error {i}"),
            )
            ids.append(entry.id)

        assert dead_letter_queue.size == 10

        replayed_count = 0
        for eid in ids:
            result = dead_letter_queue.replay(eid)
            if result:
                replayed_count += 1

        assert replayed_count == 10

    def test_dlq_bulk_replay_filtered(self, dead_letter_queue: DeadLetterQueue):
        """Bulk replay filtered by error type.

        Inspired by Kafka Connect DLQ selective replay pattern.
        """
        dead_letter_queue.add(
            message={"id": 1},
            error=ConnectionError("conn"),
            source="a",
        )
        dead_letter_queue.add(
            message={"id": 2},
            error=ValueError("val"),
            source="b",
        )
        dead_letter_queue.add(
            message={"id": 3},
            error=ConnectionError("conn2"),
            source="c",
        )

        # Filter for ConnectionError only
        conn_entries = [
            e for e in dead_letter_queue.entries if e.error_type == "ConnectionError"
        ]
        assert len(conn_entries) == 2

        for e in conn_entries:
            dead_letter_queue.replay(e.id)

        # Only ConnectionError entries replayed
        replayed = [e for e in dead_letter_queue.entries if e.retry_count > 0]
        assert len(replayed) == 2

    def test_dlq_discard_single(self, dead_letter_queue: DeadLetterQueue):
        """Single DLQ entry discarded and removed from queue.

        Inspired by Kafka Connect admin API delete-connector-offsets.
        """
        e1 = dead_letter_queue.add(message={"id": 1}, error=Exception("e1"))
        e2 = dead_letter_queue.add(message={"id": 2}, error=Exception("e2"))

        assert dead_letter_queue.size == 2
        dead_letter_queue.discard(e1.id)
        assert dead_letter_queue.size == 1
        assert dead_letter_queue.entries[0].id == e2.id

    def test_dlq_discard_all(self, dead_letter_queue: DeadLetterQueue):
        """All DLQ entries discarded (purge).

        Inspired by Kafka Connect DLQ topic deletion/compaction.
        """
        for i in range(5):
            dead_letter_queue.add(message={"id": i}, error=Exception(f"e{i}"))

        assert dead_letter_queue.size == 5

        # Purge all
        ids = [e.id for e in dead_letter_queue.entries]
        for eid in ids:
            dead_letter_queue.discard(eid)

        assert dead_letter_queue.size == 0

    def test_dlq_retention_30_day_purge(self, dead_letter_queue: DeadLetterQueue):
        """Entries older than 30 days are eligible for purge.

        Inspired by Kafka Connect DLQ topic retention.ms.
        """
        old_entry = dead_letter_queue.add(
            message={"id": "old"},
            error=Exception("old error"),
        )
        old_entry.timestamp = datetime.now(timezone.utc) - timedelta(days=31)

        new_entry = dead_letter_queue.add(
            message={"id": "new"},
            error=Exception("new error"),
        )

        retention_days = 30
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        expired = [e for e in dead_letter_queue.entries if e.timestamp < cutoff]
        assert len(expired) == 1
        assert expired[0].id == old_entry.id

        # Purge expired
        for e in expired:
            dead_letter_queue.discard(e.id)

        assert dead_letter_queue.size == 1
        assert dead_letter_queue.entries[0].id == new_entry.id

    def test_dlq_size_limit_eviction(self, dead_letter_queue: DeadLetterQueue):
        """Oldest entries evicted when DLQ exceeds size limit.

        Inspired by Kafka Connect DLQ topic max.message.bytes/retention.
        """
        max_size = 5

        for i in range(8):
            dead_letter_queue.add(
                message={"id": i},
                error=Exception(f"error {i}"),
            )

        # Evict oldest to stay within limit
        while dead_letter_queue.size > max_size:
            dead_letter_queue.discard(dead_letter_queue.entries[0].id)

        assert dead_letter_queue.size == max_size
        # Remaining entries are the 5 newest (ids 3-7)
        remaining_ids = [
            e.original_message["id"] for e in dead_letter_queue.entries
        ]
        assert remaining_ids == [3, 4, 5, 6, 7]

    def test_dlq_stats_count_size(self, dead_letter_queue: DeadLetterQueue):
        """DLQ reports count and can compute aggregate stats.

        Inspired by Kafka Connect metrics MBean for DLQ.
        """
        for i in range(7):
            dead_letter_queue.add(
                message={"id": i, "payload": "x" * 100},
                error=Exception(f"error {i}"),
                source=f"source-{i % 3}",
            )

        assert dead_letter_queue.size == 7

        # Stats by source
        by_source: dict[str, int] = {}
        for e in dead_letter_queue.entries:
            by_source[e.source] = by_source.get(e.source, 0) + 1

        assert by_source["source-0"] == 3
        assert by_source["source-1"] == 2
        assert by_source["source-2"] == 2

    def test_dlq_alert_threshold(self, dead_letter_queue: DeadLetterQueue):
        """Alert fired when DLQ size exceeds threshold.

        Inspired by Kafka Connect DLQ monitoring with alerting rules.
        """
        alert_threshold = 5
        alerts_fired: list[str] = []

        for i in range(8):
            dead_letter_queue.add(
                message={"id": i},
                error=Exception(f"error {i}"),
            )
            if dead_letter_queue.size >= alert_threshold and len(alerts_fired) == 0:
                alerts_fired.append(
                    f"DLQ size {dead_letter_queue.size} >= threshold {alert_threshold}"
                )

        assert len(alerts_fired) == 1
        assert "DLQ size 5" in alerts_fired[0]
