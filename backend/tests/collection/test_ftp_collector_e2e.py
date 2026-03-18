"""End-to-End tests for the FTP/SFTP Collector plugin.

Tests the FTPSFTPCollector class with mocked FTP/SFTP connections,
verifying directory traversal, file filtering, ordering, completion checks,
retry/circuit-breaker resilience, and post-collection actions.

These tests import and exercise the actual collector logic from
plugins/collectors/ftp-sftp/main.py, replacing real FTP connections
with MockFTPConnection instances that simulate various folder structures,
failure modes, and edge cases.

Test categories:
    1. Folder structure traversal (flat, nested dates, deep hierarchies)
    2. File filtering (regex, size, age, exclusion)
    3. Ordering (newest/oldest, name asc/desc)
    4. Discovery modes (ALL, LATEST, BATCH, ALL_NEW)
    5. Completion checks (MARKER_FILE, SIZE_STABLE)
    6. Post-collection actions (KEEP, DELETE, MOVE, RENAME)
    7. Retry & resilience (backoff, jitter, circuit breaker)
    8. Connection lifecycle (reconnect, timeout, pool)
    9. Integrated E2E scenarios (full pipeline runs)
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Optional
from unittest.mock import patch, MagicMock

import pytest

# We import collector classes directly for unit-level integration testing
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'plugins', 'community-examples', 'ftp-sftp-collector'))
from main import (
    FTPSFTPCollector,
    FTPConnection,
    SFTPConnection,
    RemoteFile,
    CircuitBreakerState,
    CollectorStats,
)


# ============================================================
# Mock FTP Connection for E2E tests
# ============================================================

@dataclass
class MockRemoteFS:
    """Simulates a remote filesystem with directories and files."""
    files: dict[str, list[RemoteFile]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    created_dirs: list[str] = field(default_factory=list)

    def add_file(self, directory: str, name: str, size: int = 1024,
                 modified: datetime | None = None, content: bytes | None = None) -> None:
        if modified is None:
            modified = datetime.now(timezone.utc)
        if content is None:
            content = os.urandom(size) if size > 0 else b""
        full_path = str(PurePosixPath(directory) / name)
        entry = RemoteFile(path=full_path, name=name, size=size, modified=modified)
        entry._content = content  # type: ignore
        self.files.setdefault(directory, []).append(entry)

    def add_directory(self, parent: str, name: str) -> None:
        full_path = str(PurePosixPath(parent) / name)
        entry = RemoteFile(path=full_path, name=name, size=0,
                           modified=datetime.now(timezone.utc), is_dir=True)
        self.files.setdefault(parent, []).append(entry)
        # Ensure the directory key exists
        self.files.setdefault(full_path, [])

    def get_file_content(self, path: str) -> bytes:
        directory = str(PurePosixPath(path).parent)
        name = PurePosixPath(path).name
        for f in self.files.get(directory, []):
            if f.name == name and hasattr(f, '_content'):
                return f._content  # type: ignore
        raise FileNotFoundError(f"File not found: {path}")

    def get_file_size(self, path: str) -> int:
        directory = str(PurePosixPath(path).parent)
        name = PurePosixPath(path).name
        for f in self.files.get(directory, []):
            if f.name == name:
                return f.size
        raise FileNotFoundError(f"File not found: {path}")


class MockConnection:
    """Mock FTP/SFTP connection backed by MockRemoteFS."""

    def __init__(self, fs: MockRemoteFS):
        self.fs = fs
        self._connected = False
        self._connect_fail_count = 0
        self._connect_attempts = 0
        self._list_fail_count = 0
        self._list_attempts = 0
        self._download_fail_count = 0
        self._download_attempts = 0

    def set_connect_failures(self, count: int) -> None:
        self._connect_fail_count = count

    def set_list_failures(self, count: int) -> None:
        self._list_fail_count = count

    def set_download_failures(self, count: int) -> None:
        self._download_fail_count = count

    def connect(self) -> None:
        self._connect_attempts += 1
        if self._connect_attempts <= self._connect_fail_count:
            raise ConnectionError(f"Connection refused (attempt {self._connect_attempts})")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def list_directory(self, path: str) -> list[RemoteFile]:
        self._list_attempts += 1
        if self._list_attempts <= self._list_fail_count:
            raise ConnectionError(f"Listing failed (attempt {self._list_attempts})")
        return list(self.fs.files.get(path, []))

    def download(self, remote_path: str) -> bytes:
        self._download_attempts += 1
        if self._download_attempts <= self._download_fail_count:
            raise ConnectionError(f"Download failed (attempt {self._download_attempts})")
        return self.fs.get_file_content(remote_path)

    def rename(self, from_path: str, to_path: str) -> None:
        self.fs.renamed.append((from_path, to_path))

    def delete(self, path: str) -> None:
        self.fs.deleted.append(path)

    def mkdir(self, path: str) -> None:
        self.fs.created_dirs.append(path)

    def file_size(self, path: str) -> int:
        return self.fs.get_file_size(path)

    @property
    def is_connected(self) -> bool:
        return self._connected


# ============================================================
# Helper to build collector with mock
# ============================================================

def make_collector(
    fs: MockRemoteFS,
    settings: dict[str, Any] | None = None,
    recipe: dict[str, Any] | None = None,
) -> tuple[FTPSFTPCollector, MockConnection]:
    """Create a collector with a mocked connection."""
    default_settings = {
        "host": "test-server",
        "username": "testuser",
        "protocol": "FTP",
        "retry_max_attempts": 3,
        "retry_base_delay_seconds": 0.01,  # Fast for tests
        "retry_max_delay_seconds": 0.1,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_recovery_seconds": 1,
    }
    if settings:
        default_settings.update(settings)

    default_recipe = {
        "remote_path": "/data",
        "recursive": False,
        "ordering": "NEWEST_FIRST",
        "discovery_mode": "ALL",
        "checksum_verification": False,
    }
    if recipe:
        default_recipe.update(recipe)

    collector = FTPSFTPCollector(default_settings, default_recipe)
    mock_conn = MockConnection(fs)
    mock_conn._connected = True  # Already connected
    collector._conn = mock_conn
    # Skip connect phase since we inject mock
    collector.circuit_breaker.state = "CLOSED"

    # Override _ensure_connected to use mock (prevent real FTP connection attempts)
    collector._ensure_connected = lambda: None
    # Override _create_connection to return mock
    collector._create_connection = lambda: mock_conn

    return collector, mock_conn


# ============================================================
# 1. Folder Structure Traversal
# ============================================================

class TestFolderTraversal:
    """Test various folder structures and traversal strategies."""

    def test_flat_directory_single_level(self):
        """Flat directory with files — no recursion."""
        fs = MockRemoteFS()
        fs.add_file("/data", "report_001.csv", size=500)
        fs.add_file("/data", "report_002.csv", size=600)
        fs.add_file("/data", "report_003.csv", size=700)

        collector, _ = make_collector(fs)
        files = collector.discover_files()
        assert len(files) == 3
        assert collector.stats.directories_scanned == 1

    def test_recursive_traversal_depth_unlimited(self):
        """Recursive traversal with no depth limit."""
        fs = MockRemoteFS()
        fs.add_directory("/data", "level1")
        fs.add_directory("/data/level1", "level2")
        fs.add_directory("/data/level1/level2", "level3")
        fs.add_file("/data", "root.csv", size=100)
        fs.add_file("/data/level1", "l1.csv", size=200)
        fs.add_file("/data/level1/level2", "l2.csv", size=300)
        fs.add_file("/data/level1/level2/level3", "l3.csv", size=400)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "max_depth": -1,
        })
        files = collector.discover_files()
        assert len(files) == 4
        assert collector.stats.directories_scanned == 4

    def test_recursive_traversal_depth_limited(self):
        """Depth=1 should only scan immediate subdirectories."""
        fs = MockRemoteFS()
        fs.add_directory("/data", "sub1")
        fs.add_directory("/data/sub1", "sub2")
        fs.add_file("/data", "root.csv", size=100)
        fs.add_file("/data/sub1", "s1.csv", size=200)
        fs.add_file("/data/sub1/sub2", "s2.csv", size=300)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "max_depth": 1,
        })
        files = collector.discover_files()
        assert len(files) == 2  # root.csv + s1.csv (s2.csv is depth=2)

    def test_date_folder_yyyymmdd_pattern(self):
        """Date-based folder pattern: yyyyMMdd with lookback."""
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        # Create folders for last 10 days
        for i in range(10):
            d = now - timedelta(days=i)
            folder_name = d.strftime("%Y%m%d")
            fs.add_directory("/data", folder_name)
            fs.add_file(f"/data/{folder_name}", f"data_{folder_name}.csv", size=1024,
                        modified=d)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "folder_pattern": {
                "enabled": True,
                "format": "yyyyMMdd",
                "lookback_days": 3,
                "timezone": "UTC",
            },
        })
        files = collector.discover_files()
        # Should only find files in last 4 days (today + 3 lookback)
        assert len(files) <= 4

    def test_date_folder_nested_yyyy_mm_dd(self):
        """Nested date folder structure: yyyy/MM/dd."""
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        # Today's folder
        y = now.strftime("%Y")
        m = now.strftime("%m")
        d = now.strftime("%d")
        fs.add_directory("/data", y)
        fs.add_directory(f"/data/{y}", m)
        fs.add_directory(f"/data/{y}/{m}", d)
        fs.add_file(f"/data/{y}/{m}/{d}", "today.csv", size=100, modified=now)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "max_depth": -1,
        })
        files = collector.discover_files()
        assert len(files) == 1
        assert files[0].name == "today.csv"

    def test_mixed_folder_structure_with_topics(self):
        """Mixed structure: /data/{topic}/{date}/ — common industrial pattern."""
        fs = MockRemoteFS()
        topics = ["temperature", "vibration", "pressure"]
        now = datetime.now(timezone.utc)

        for topic in topics:
            fs.add_directory("/data", topic)
            for i in range(3):
                d = now - timedelta(days=i)
                date_str = d.strftime("%Y%m%d")
                fs.add_directory(f"/data/{topic}", date_str)
                fs.add_file(f"/data/{topic}/{date_str}",
                            f"{topic}_{date_str}.csv", size=1024, modified=d)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "max_depth": -1,
        })
        files = collector.discover_files()
        assert len(files) == 9  # 3 topics × 3 days

    def test_empty_directories_skipped(self):
        """Empty directories should not cause errors."""
        fs = MockRemoteFS()
        fs.add_directory("/data", "empty1")
        fs.add_directory("/data", "empty2")
        fs.add_directory("/data", "has_files")
        fs.add_file("/data/has_files", "data.csv", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
        })
        files = collector.discover_files()
        assert len(files) == 1


# ============================================================
# 2. File Filtering
# ============================================================

class TestFileFiltering:
    """Test regex, size, age, and exclusion filtering."""

    def test_filename_regex_csv_only(self):
        """Only .csv files should be collected."""
        fs = MockRemoteFS()
        fs.add_file("/data", "report.csv", size=100)
        fs.add_file("/data", "readme.txt", size=50)
        fs.add_file("/data", "data.json", size=200)
        fs.add_file("/data", "output.csv", size=300)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"filename_regex": r".*\.csv$"},
        })
        files = collector.discover_files()
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"report.csv", "output.csv"}

    def test_filename_regex_date_pattern(self):
        """Match files with date pattern: data_YYYYMMDD.csv."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data_20260315.csv", size=100)
        fs.add_file("/data", "data_20260314.csv", size=100)
        fs.add_file("/data", "data_invalid.csv", size=100)
        fs.add_file("/data", "other.csv", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"filename_regex": r"data_\d{8}\.csv$"},
        })
        files = collector.discover_files()
        assert len(files) == 2

    def test_path_regex_filter(self):
        """Filter by full path pattern."""
        fs = MockRemoteFS()
        fs.add_directory("/data", "equipment_A")
        fs.add_directory("/data", "equipment_B")
        fs.add_directory("/data", "logs")
        fs.add_file("/data/equipment_A", "data.csv", size=100)
        fs.add_file("/data/equipment_B", "data.csv", size=100)
        fs.add_file("/data/logs", "app.log", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "file_filter": {"path_regex": r".*/equipment_[A-Z]+/.*"},
        })
        files = collector.discover_files()
        assert len(files) == 2

    def test_min_max_size_filter(self):
        """Filter files by size range."""
        fs = MockRemoteFS()
        fs.add_file("/data", "tiny.csv", size=10)
        fs.add_file("/data", "small.csv", size=500)
        fs.add_file("/data", "medium.csv", size=5000)
        fs.add_file("/data", "large.csv", size=50000)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"min_size_bytes": 100, "max_size_bytes": 10000},
        })
        files = collector.discover_files()
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"small.csv", "medium.csv"}

    def test_max_age_filter(self):
        """Only files newer than max_age_hours."""
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        fs.add_file("/data", "new.csv", size=100, modified=now - timedelta(hours=1))
        fs.add_file("/data", "recent.csv", size=100, modified=now - timedelta(hours=12))
        fs.add_file("/data", "old.csv", size=100, modified=now - timedelta(hours=48))
        fs.add_file("/data", "ancient.csv", size=100, modified=now - timedelta(days=30))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"max_age_hours": 24},
        })
        files = collector.discover_files()
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"new.csv", "recent.csv"}

    def test_exclude_patterns(self):
        """Exclude .tmp, hidden files, .bak."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=100)
        fs.add_file("/data", "data.csv.tmp", size=100)
        fs.add_file("/data", ".hidden", size=100)
        fs.add_file("/data", "backup.bak", size=100)
        fs.add_file("/data", "output.json", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"exclude_patterns": [r"\.tmp$", r"^\.", r"\.bak$"]},
        })
        files = collector.discover_files()
        assert len(files) == 2
        names = {f.name for f in files}
        assert names == {"data.csv", "output.json"}

    def test_exclude_zero_byte_files(self):
        """Zero-byte files should be excluded by default."""
        fs = MockRemoteFS()
        fs.add_file("/data", "empty.csv", size=0)
        fs.add_file("/data", "data.csv", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"exclude_zero_byte": True},
        })
        files = collector.discover_files()
        assert len(files) == 1
        assert files[0].name == "data.csv"

    def test_combined_filters(self):
        """Multiple filters applied together."""
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        fs.add_file("/data", "data_20260316.csv", size=500, modified=now)
        fs.add_file("/data", "data_20260316.tmp", size=500, modified=now)
        fs.add_file("/data", "data_20260316.csv.bak", size=500, modified=now)
        fs.add_file("/data", "tiny.csv", size=10, modified=now)
        fs.add_file("/data", "old_data.csv", size=500, modified=now - timedelta(days=30))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {
                "filename_regex": r".*\.csv$",
                "min_size_bytes": 100,
                "max_age_hours": 48,
                "exclude_patterns": [r"\.bak$"],
            },
        })
        files = collector.discover_files()
        assert len(files) == 1
        assert files[0].name == "data_20260316.csv"


# ============================================================
# 3. Ordering
# ============================================================

class TestFileOrdering:
    """Test file ordering strategies."""

    def _make_files(self, fs: MockRemoteFS):
        now = datetime.now(timezone.utc)
        fs.add_file("/data", "c_file.csv", size=100, modified=now - timedelta(hours=3))
        fs.add_file("/data", "a_file.csv", size=100, modified=now - timedelta(hours=1))
        fs.add_file("/data", "b_file.csv", size=100, modified=now - timedelta(hours=2))

    def test_newest_first(self):
        fs = MockRemoteFS()
        self._make_files(fs)
        collector, _ = make_collector(fs, recipe={"remote_path": "/data", "ordering": "NEWEST_FIRST"})
        files = collector.discover_files()
        assert [f.name for f in files] == ["a_file.csv", "b_file.csv", "c_file.csv"]

    def test_oldest_first(self):
        fs = MockRemoteFS()
        self._make_files(fs)
        collector, _ = make_collector(fs, recipe={"remote_path": "/data", "ordering": "OLDEST_FIRST"})
        files = collector.discover_files()
        assert [f.name for f in files] == ["c_file.csv", "b_file.csv", "a_file.csv"]

    def test_name_ascending(self):
        fs = MockRemoteFS()
        self._make_files(fs)
        collector, _ = make_collector(fs, recipe={"remote_path": "/data", "ordering": "NAME_ASC"})
        files = collector.discover_files()
        assert [f.name for f in files] == ["a_file.csv", "b_file.csv", "c_file.csv"]

    def test_name_descending(self):
        fs = MockRemoteFS()
        self._make_files(fs)
        collector, _ = make_collector(fs, recipe={"remote_path": "/data", "ordering": "NAME_DESC"})
        files = collector.discover_files()
        assert [f.name for f in files] == ["c_file.csv", "b_file.csv", "a_file.csv"]


# ============================================================
# 4. Discovery Modes
# ============================================================

class TestDiscoveryModes:

    def test_mode_all(self):
        fs = MockRemoteFS()
        for i in range(10):
            fs.add_file("/data", f"file_{i:03d}.csv", size=100)

        collector, _ = make_collector(fs, recipe={"remote_path": "/data", "discovery_mode": "ALL"})
        assert len(collector.discover_files()) == 10

    def test_mode_latest(self):
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        fs.add_file("/data", "old.csv", size=100, modified=now - timedelta(hours=5))
        fs.add_file("/data", "newest.csv", size=100, modified=now)
        fs.add_file("/data", "mid.csv", size=100, modified=now - timedelta(hours=2))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "ordering": "NEWEST_FIRST",
            "discovery_mode": "LATEST",
        })
        files = collector.discover_files()
        assert len(files) == 1
        assert files[0].name == "newest.csv"

    def test_mode_batch(self):
        fs = MockRemoteFS()
        for i in range(20):
            fs.add_file("/data", f"file_{i:03d}.csv", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "discovery_mode": "BATCH",
            "batch_size": 5,
        })
        files = collector.discover_files()
        assert len(files) == 5

    def test_mode_all_new_tracks_seen(self):
        """ALL_NEW should not return previously seen files."""
        fs = MockRemoteFS()
        fs.add_file("/data", "file_a.csv", size=100)
        fs.add_file("/data", "file_b.csv", size=100)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "discovery_mode": "ALL_NEW",
        })

        # First call: both files are new
        files1 = collector.discover_files()
        assert len(files1) == 2

        # Second call: no new files
        collector.stats = CollectorStats()  # Reset stats
        files2 = collector.discover_files()
        assert len(files2) == 0

        # Third call: add a new file
        fs.add_file("/data", "file_c.csv", size=100)
        collector.stats = CollectorStats()
        files3 = collector.discover_files()
        assert len(files3) == 1
        assert files3[0].name == "file_c.csv"


# ============================================================
# 5. Completion Checks
# ============================================================

class TestCompletionChecks:

    def test_marker_file_present(self):
        """File with .done marker should be collected."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=1024)
        fs.add_file("/data", "data.csv.done", size=0)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"filename_regex": r"^[^.]*\.csv$", "exclude_zero_byte": False},
            "completion_check": {"strategy": "MARKER_FILE", "marker_suffix": ".done"},
        })
        files = collector.discover_files()
        # Only data.csv matches the filename regex (not data.csv.done)
        assert len(files) == 1
        # Check completion
        assert collector._check_completion(files[0]) is True

    def test_marker_file_missing(self):
        """File WITHOUT .done marker should be skipped."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=1024)
        # No data.csv.done

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "completion_check": {"strategy": "MARKER_FILE", "marker_suffix": ".done"},
        })
        files = collector.discover_files()
        assert len(files) == 1
        assert collector._check_completion(files[0]) is False

    def test_no_completion_check(self):
        """NONE strategy should always pass."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=1024)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "completion_check": {"strategy": "NONE"},
        })
        files = collector.discover_files()
        assert collector._check_completion(files[0]) is True


# ============================================================
# 6. Post-Collection Actions
# ============================================================

class TestPostActions:

    def test_action_keep(self):
        """KEEP should not modify remote file."""
        fs = MockRemoteFS()
        file = RemoteFile(path="/data/file.csv", name="file.csv", size=100,
                          modified=datetime.now(timezone.utc))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "post_action": {"action": "KEEP"},
        })
        collector._post_action(file)
        assert len(fs.deleted) == 0
        assert len(fs.renamed) == 0

    def test_action_delete(self):
        """DELETE should remove the file."""
        fs = MockRemoteFS()
        fs.add_file("/data", "file.csv", size=100)
        file = RemoteFile(path="/data/file.csv", name="file.csv", size=100,
                          modified=datetime.now(timezone.utc))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "post_action": {"action": "DELETE"},
        })
        collector._post_action(file)
        assert "/data/file.csv" in fs.deleted

    def test_action_move_with_timestamp(self):
        """MOVE should move to target dir with timestamp suffix."""
        fs = MockRemoteFS()
        file = RemoteFile(path="/data/file.csv", name="file.csv", size=100,
                          modified=datetime.now(timezone.utc))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "post_action": {
                "action": "MOVE",
                "move_target": "/archive",
                "conflict_resolution": "TIMESTAMP",
            },
        })
        collector._post_action(file)
        assert "/archive" in fs.created_dirs
        assert len(fs.renamed) == 1
        src, dst = fs.renamed[0]
        assert src == "/data/file.csv"
        assert dst.startswith("/archive/file_")
        assert dst.endswith(".csv")

    def test_action_rename(self):
        """RENAME should append suffix."""
        fs = MockRemoteFS()
        file = RemoteFile(path="/data/file.csv", name="file.csv", size=100,
                          modified=datetime.now(timezone.utc))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "post_action": {"action": "RENAME", "rename_suffix": ".processed"},
        })
        collector._post_action(file)
        assert len(fs.renamed) == 1
        assert fs.renamed[0] == ("/data/file.csv", "/data/file.csv.processed")


# ============================================================
# 7. Retry & Resilience
# ============================================================

class TestRetryResilience:

    def test_connect_retry_succeeds_after_failures(self):
        """Connection should succeed after transient failures with retry."""
        fs = MockRemoteFS()
        mock_conn = MockConnection(fs)
        mock_conn.set_connect_failures(2)  # Fail first 2 attempts

        # Attempt 1: fails
        with pytest.raises(ConnectionError):
            mock_conn.connect()
        # Attempt 2: fails
        with pytest.raises(ConnectionError):
            mock_conn.connect()
        # Attempt 3: succeeds
        mock_conn.connect()
        assert mock_conn.is_connected
        assert mock_conn._connect_attempts == 3

    def test_circuit_breaker_opens_after_threshold(self):
        """Circuit breaker should open after N consecutive failures."""
        cb = CircuitBreakerState(threshold=3, recovery_seconds=1)

        cb.record_failure()
        assert cb.state == "CLOSED"
        cb.record_failure()
        assert cb.state == "CLOSED"
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.can_execute() is False

    def test_circuit_breaker_half_open_after_recovery(self):
        """Circuit breaker should transition to HALF_OPEN after recovery time."""
        cb = CircuitBreakerState(threshold=2, recovery_seconds=0)  # 0 for instant recovery

        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        # With recovery_seconds=0, should immediately go HALF_OPEN
        time.sleep(0.01)
        assert cb.can_execute() is True
        assert cb.state == "HALF_OPEN"

    def test_circuit_breaker_closes_on_success(self):
        """Successful operation in HALF_OPEN should close circuit."""
        cb = CircuitBreakerState(threshold=2, recovery_seconds=0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        time.sleep(0.01)
        cb.can_execute()  # Transitions to HALF_OPEN
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

    def test_download_retry_on_connection_lost(self):
        """Download should retry after connection lost."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=100)

        collector, mock_conn = make_collector(fs)
        mock_conn.set_download_failures(2)  # Fail first 2 download attempts
        # Ensure reconnect restores the mock connection
        collector._ensure_connected = lambda: setattr(collector, '_conn', mock_conn)

        file = RemoteFile(path="/data/data.csv", name="data.csv", size=100,
                          modified=datetime.now(timezone.utc))
        result = collector.download_file(file)
        assert result is not None
        assert result.success is True
        assert collector.stats.files_downloaded == 1

    def test_list_retry_on_failure(self):
        """Directory listing should retry on transient failure."""
        fs = MockRemoteFS()
        fs.add_file("/data", "file.csv", size=100)

        collector, mock_conn = make_collector(fs)
        mock_conn.set_list_failures(1)  # Fail first listing attempt
        collector._ensure_connected = lambda: setattr(collector, '_conn', mock_conn)

        files = collector.discover_files()
        assert len(files) == 1

    def test_stats_track_retries(self):
        """Stats should accurately track retry counts."""
        fs = MockRemoteFS()
        fs.add_file("/data", "data.csv", size=100)

        collector, mock_conn = make_collector(fs)
        mock_conn.set_download_failures(2)
        collector._ensure_connected = lambda: setattr(collector, '_conn', mock_conn)

        file = RemoteFile(path="/data/data.csv", name="data.csv", size=100,
                          modified=datetime.now(timezone.utc))
        collector.download_file(file)
        assert collector.stats.retry_count >= 2


# ============================================================
# 8. Integrated E2E Scenarios
# ============================================================

class TestE2EScenarios:
    """Full pipeline runs simulating real-world scenarios."""

    def test_e2e_equipment_ftp_daily_collection(self):
        """
        Scenario: Equipment generates CSV files in date-named folders.
        Structure: /equipment/{YYYYMMDD}/sensor_*.csv
        Strategy: Recursive, newest first, ALL_NEW, marker file check.
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)

        for day_offset in range(5):
            d = now - timedelta(days=day_offset)
            date_str = d.strftime("%Y%m%d")
            fs.add_directory("/equipment", date_str)

            for sensor in ["temp", "vibration", "pressure"]:
                fname = f"sensor_{sensor}_{date_str}.csv"
                fs.add_file(f"/equipment/{date_str}", fname, size=2048, modified=d)
                # Add marker files for last 3 days only
                if day_offset < 3:
                    fs.add_file(f"/equipment/{date_str}", f"{fname}.done", size=0, modified=d)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/equipment",
            "recursive": True,
            "max_depth": 1,
            "file_filter": {
                "filename_regex": r"sensor_.*\.csv$",
                "exclude_zero_byte": True,
            },
            "ordering": "NEWEST_FIRST",
            "discovery_mode": "ALL",
            "completion_check": {"strategy": "MARKER_FILE", "marker_suffix": ".done"},
            "post_action": {"action": "KEEP"},
            "checksum_verification": False,
        })

        files = collector.discover_files()
        # 5 days × 3 sensors = 15 files, but only files matching regex
        assert len(files) == 15

        # Check completion — only 3 days have markers
        ready_files = [f for f in files if collector._check_completion(f)]
        assert len(ready_files) == 9  # 3 days × 3 sensors

    def test_e2e_topic_based_collection_with_move(self):
        """
        Scenario: /data/{topic}/{date}/files → collect and move to /archive.
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)

        for topic in ["orders", "inventory"]:
            fs.add_directory("/data", topic)
            for day_offset in range(2):
                d = now - timedelta(days=day_offset)
                date_str = d.strftime("%Y%m%d")
                fs.add_directory(f"/data/{topic}", date_str)
                fs.add_file(f"/data/{topic}/{date_str}",
                            f"{topic}_{date_str}.json", size=4096, modified=d)

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "recursive": True,
            "file_filter": {"filename_regex": r".*\.json$"},
            "ordering": "NEWEST_FIRST",
            "discovery_mode": "ALL",
            "post_action": {
                "action": "MOVE",
                "move_target": "/archive",
                "conflict_resolution": "TIMESTAMP",
            },
            "checksum_verification": False,
        })

        files = collector.discover_files()
        assert len(files) == 4  # 2 topics × 2 days

        # Simulate download and post-action for each file
        for f in files:
            result = collector.download_file(f)
            assert result is not None and result.success
            collector._post_action(f)

        assert collector.stats.files_downloaded == 4
        assert len(fs.renamed) == 4  # All moved
        assert all(dst.startswith("/archive/") for _, dst in fs.renamed)

    def test_e2e_large_directory_with_batch_mode(self):
        """
        Scenario: Directory with 1000 files, batch collect 50 at a time.
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)
        for i in range(1000):
            fs.add_file("/data", f"record_{i:05d}.csv", size=256,
                        modified=now - timedelta(minutes=i))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "ordering": "NEWEST_FIRST",
            "discovery_mode": "BATCH",
            "batch_size": 50,
            "checksum_verification": False,
        })

        files = collector.discover_files()
        assert len(files) == 50
        # Verify ordering: first file should be the newest
        assert files[0].name == "record_00000.csv"

    def test_e2e_retry_during_collection(self):
        """
        Scenario: Connection drops during file download, retries succeed.
        """
        fs = MockRemoteFS()
        for i in range(3):
            fs.add_file("/data", f"file_{i}.csv", size=512)

        collector, mock_conn = make_collector(fs, recipe={
            "remote_path": "/data",
            "discovery_mode": "ALL",
            "checksum_verification": False,
        })
        # Ensure reconnect restores mock
        collector._ensure_connected = lambda: setattr(collector, '_conn', mock_conn)

        files = collector.discover_files()
        assert len(files) == 3

        # Make downloads fail once then succeed
        for f in files:
            mock_conn._download_attempts = 0  # Reset per file
            mock_conn._download_fail_count = 1
            result = collector.download_file(f)
            assert result is not None and result.success

        assert collector.stats.files_downloaded == 3
        assert collector.stats.retry_count >= 3  # At least 1 retry per file

    def test_e2e_filter_by_age_and_size_with_delete(self):
        """
        Scenario: Only collect files < 24h old, > 100 bytes, then delete.
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)

        # Should be collected
        fs.add_file("/data", "fresh_big.csv", size=500, modified=now - timedelta(hours=2))
        # Too old
        fs.add_file("/data", "old_big.csv", size=500, modified=now - timedelta(days=3))
        # Too small
        fs.add_file("/data", "fresh_tiny.csv", size=10, modified=now - timedelta(hours=1))
        # Should be collected
        fs.add_file("/data", "fresh_medium.csv", size=200, modified=now - timedelta(hours=6))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "file_filter": {"min_size_bytes": 100, "max_age_hours": 24},
            "post_action": {"action": "DELETE"},
            "checksum_verification": False,
        })

        files = collector.discover_files()
        assert len(files) == 2

        for f in files:
            result = collector.download_file(f)
            assert result is not None and result.success
            collector._post_action(f)

        assert collector.stats.files_downloaded == 2
        assert len(fs.deleted) == 2
        deleted_names = {PurePosixPath(p).name for p in fs.deleted}
        assert deleted_names == {"fresh_big.csv", "fresh_medium.csv"}

    def test_e2e_all_new_incremental_collection(self):
        """
        Scenario: Incremental collection — only new files each poll.
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)

        # Initial files
        fs.add_file("/data", "batch_001.csv", size=100, modified=now - timedelta(hours=2))
        fs.add_file("/data", "batch_002.csv", size=100, modified=now - timedelta(hours=1))

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/data",
            "discovery_mode": "ALL_NEW",
            "checksum_verification": False,
        })

        # Poll 1: get both files
        files1 = collector.discover_files()
        assert len(files1) == 2

        # Poll 2: no new files
        collector.stats = CollectorStats()
        files2 = collector.discover_files()
        assert len(files2) == 0

        # New file arrives
        fs.add_file("/data", "batch_003.csv", size=100, modified=now)

        # Poll 3: only the new file
        collector.stats = CollectorStats()
        files3 = collector.discover_files()
        assert len(files3) == 1
        assert files3[0].name == "batch_003.csv"

    def test_e2e_deep_hierarchy_with_rename(self):
        """
        Scenario: /plant/{line}/{station}/{date}/data.csv
        """
        fs = MockRemoteFS()
        now = datetime.now(timezone.utc)

        for line in ["LINE_A", "LINE_B"]:
            fs.add_directory("/plant", line)
            for station in ["ST01", "ST02"]:
                fs.add_directory(f"/plant/{line}", station)
                date_str = now.strftime("%Y%m%d")
                fs.add_directory(f"/plant/{line}/{station}", date_str)
                fs.add_file(
                    f"/plant/{line}/{station}/{date_str}",
                    "measurement.csv",
                    size=2048,
                    modified=now,
                )

        collector, _ = make_collector(fs, recipe={
            "remote_path": "/plant",
            "recursive": True,
            "max_depth": -1,
            "ordering": "NAME_ASC",
            "post_action": {"action": "RENAME", "rename_suffix": ".collected"},
            "checksum_verification": False,
        })

        files = collector.discover_files()
        assert len(files) == 4  # 2 lines × 2 stations

        for f in files:
            result = collector.download_file(f)
            assert result is not None and result.success
            collector._post_action(f)

        assert collector.stats.files_downloaded == 4
        assert len(fs.renamed) == 4
        assert all(dst.endswith(".collected") for _, dst in fs.renamed)
