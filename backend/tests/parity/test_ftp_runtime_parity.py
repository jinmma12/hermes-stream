"""Runtime parity tests: Python reference vs .NET for FTP/SFTP.

These tests verify that the same config/recipe produces the same
semantic behavior in the Python reference layer. Where .NET behavior
differs or is not yet implemented, tests are marked xfail.

The parity corpus uses the canonical examples from:
- docs/FTP_SFTP_COLLECTOR_CONFIG_SPEC.md
- docs/FTP_SFTP_RECIPE_EXAMPLES.md
"""
from __future__ import annotations

import re

import pytest

# Parity corpus: recipe config → expected behavior
PARITY_FIXTURES = [
    {
        "name": "flat_csv_pickup",
        "recipe": {
            "remote_path": "/drop",
            "recursive": False,
            "file_filter": {"filename_regex": ".*\\.csv$"},
            "discovery_mode": "ALL_NEW",
        },
        "test_paths": [
            ("/drop/a.csv", True),
            ("/drop/b.csv", True),
            ("/drop/readme.txt", False),
            ("/drop/subdir/data.csv", False),  # not recursive
        ],
    },
    {
        "name": "recursive_equipment_tree",
        "recipe": {
            "remote_path": "/data",
            "recursive": True,
            "max_depth": -1,
            "file_filter": {
                "filename_regex": "sensor_.*\\.csv$",
                "path_regex": ".*/equipment_[A-Z]+/.*",
            },
            "discovery_mode": "ALL_NEW",
        },
        "test_paths": [
            ("/data/equipment_A/sensor_01.csv", True),
            ("/data/equipment_B/sensor_02.csv", True),
            ("/data/logs/sensor_01.csv", False),  # path_regex fails
            ("/data/equipment_A/readme.txt", False),  # filename_regex fails
        ],
    },
    {
        "name": "exclude_patterns",
        "recipe": {
            "remote_path": "/data",
            "recursive": True,
            "max_depth": -1,
            "file_filter": {
                "filename_regex": ".*\\.csv$",
                "exclude_patterns": ["\\.tmp$", "^\\.", "\\.bak$"],
                "exclude_zero_byte": True,
            },
            "discovery_mode": "ALL_NEW",
        },
        "test_paths": [
            ("/data/report.csv", True),
            ("/data/report.csv.tmp", False),  # exclude .tmp
            ("/data/.hidden.csv", False),  # exclude hidden
            ("/data/old.csv.bak", False),  # exclude .bak
        ],
    },
    {
        "name": "depth_limited",
        "recipe": {
            "remote_path": "/data",
            "recursive": True,
            "max_depth": 1,
            "file_filter": {"filename_regex": ".*\\.csv$"},
            "discovery_mode": "ALL_NEW",
        },
        "test_paths": [
            ("/data/root.csv", True),  # depth 0
            ("/data/sub/file.csv", True),  # depth 1
            ("/data/sub/deep/file.csv", False),  # depth 2 > max_depth 1
        ],
    },
]


def python_match(path: str, recipe: dict) -> bool:
    """Simulate Python reference collector's file matching logic."""
    remote_path = recipe.get("remote_path", "/").rstrip("/")
    recursive = recipe.get("recursive", False)
    max_depth = recipe.get("max_depth", -1) if recursive else 0
    file_filter = recipe.get("file_filter", {})
    filename = path.split("/")[-1]

    # Check remote_path prefix
    if not path.startswith(remote_path + "/") and path != remote_path:
        return False

    # Check depth
    relative = path[len(remote_path) + 1:]
    segments = relative.split("/")
    depth = len(segments) - 1
    if max_depth >= 0 and depth > max_depth:
        return False

    # filename_regex
    fn_re = file_filter.get("filename_regex")
    if fn_re and not re.search(fn_re, filename):
        return False

    # path_regex
    path_re = file_filter.get("path_regex")
    if path_re and not re.search(path_re, path):
        return False

    # exclude_patterns
    for pattern in file_filter.get("exclude_patterns", []):
        if re.search(pattern, filename):
            return False

    return True


@pytest.mark.parametrize("fixture", PARITY_FIXTURES, ids=lambda f: f["name"])
def test_python_reference_parity(fixture):
    """Python reference layer matches expected selection for each test path."""
    recipe = fixture["recipe"]
    for path, expected in fixture["test_paths"]:
        result = python_match(path, recipe)
        assert result == expected, (
            f"[{fixture['name']}] path={path}: expected={expected}, got={result}"
        )


# ── .NET parity gaps (xfail) ────────────────────────────────

@pytest.mark.xfail(
    reason=".NET FtpSftpMonitor does not yet support exclude_patterns",
    strict=False,
)
def test_dotnet_exclude_patterns_parity():
    """Current .NET FtpSftpMonitor has no exclude_patterns field.

    Gap: docs/manifest promise exclude_patterns but .NET monitor uses
    only path_filter_regex and file_filter_regex without an explicit
    exclude list. This should be implemented in the .NET monitor.
    """
    raise NotImplementedError("Implement in .NET: FtpSftpMonitor.cs exclude_patterns")


@pytest.mark.xfail(
    reason=".NET FtpSftpMonitor does not persist checkpoint state",
    strict=False,
)
def test_dotnet_persisted_checkpoint_parity():
    """Python collector supports ALL_NEW via in-memory seen set.
    .NET monitor uses in-memory _seenFiles with no DB persistence.

    Gap: restart duplicates are possible in .NET.
    """
    raise NotImplementedError("Implement in .NET: persisted checkpoint for dedup")


@pytest.mark.xfail(
    reason=".NET FtpSftpMonitor does not support completion_check",
    strict=False,
)
def test_dotnet_completion_check_parity():
    """Python collector supports MARKER_FILE and SIZE_STABLE completion checks.
    .NET monitor has no completion check implementation.
    """
    raise NotImplementedError("Implement in .NET: completion_check strategies")


@pytest.mark.xfail(
    reason=".NET FtpSftpMonitor does not support post_action",
    strict=False,
)
def test_dotnet_post_action_parity():
    """Python collector supports KEEP/DELETE/MOVE/RENAME post-collection.
    .NET monitor has no post-action implementation.
    """
    raise NotImplementedError("Implement in .NET: post_action (MOVE/DELETE/RENAME)")


@pytest.mark.xfail(
    reason="Kafka consumer duplicate handling not yet tested",
    strict=False,
)
def test_kafka_duplicate_handling_contract():
    """Kafka consumer must handle duplicate messages idempotently.
    Current implementation does not have explicit dedup.
    """
    raise NotImplementedError("Implement: Kafka consumer dedup contract")


@pytest.mark.xfail(
    reason="DB writer upsert idempotency not yet tested",
    strict=False,
)
def test_db_writer_upsert_idempotency_contract():
    """DB writer UPSERT mode must be idempotent on conflict_key.
    Current .NET DbWriterExporter has the model but no integration test.
    """
    raise NotImplementedError("Implement: DB writer UPSERT idempotency test")
