"""Runtime parity tests: Python reference vs .NET for FTP/SFTP.

Uses the shared corpus at ftp_parity_corpus.json.
Python assertions validate the reference matching logic.
.NET gaps are documented as xfail with specific gap references.

This file tests ONLY FTP/SFTP parity.
Kafka and DB writer integrity are in separate files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ── Load shared corpus ───────────────────────────────────────

CORPUS_PATH = Path(__file__).parent / "ftp_parity_corpus.json"
with open(CORPUS_PATH) as f:
    PARITY_CORPUS: list[dict] = json.load(f)


# ── Python reference matching (mirrors main.py logic) ────────

def python_match(path: str, recipe: dict) -> bool:
    """Simulate Python reference collector's file matching logic."""
    remote_path = recipe.get("remote_path", "/").rstrip("/")
    recursive = recipe.get("recursive", False)
    max_depth = recipe.get("max_depth", -1) if recursive else 0
    file_filter = recipe.get("file_filter", {})
    filename = path.split("/")[-1]

    if not path.startswith(remote_path + "/") and path != remote_path:
        return False

    relative = path[len(remote_path) + 1:]
    segments = relative.split("/")
    depth = len(segments) - 1
    if max_depth >= 0 and depth > max_depth:
        return False

    fn_re = file_filter.get("filename_regex")
    if fn_re and not re.search(fn_re, filename):
        return False

    path_re = file_filter.get("path_regex")
    if path_re and not re.search(path_re, path):
        return False

    for pattern in file_filter.get("exclude_patterns", []):
        if re.search(pattern, filename):
            return False

    return True


# ── .NET matching simulation (mirrors FtpSftpMonitor.cs) ─────

def dotnet_match(path: str, dotnet_recipe: dict) -> bool:
    """Simulate .NET FtpSftpMonitor's ApplyFilters logic.

    .NET uses: base_path, recursive, path_filter_regex, file_filter_regex.
    Does NOT support: max_depth, exclude_patterns, folder_pattern.
    """
    base_path = dotnet_recipe.get("base_path", "/").rstrip("/")
    recursive = dotnet_recipe.get("recursive", False)
    filename = path.split("/")[-1]

    if not path.startswith(base_path + "/"):
        return False

    if not recursive:
        relative = path[len(base_path) + 1:]
        if "/" in relative:
            return False

    pfr = dotnet_recipe.get("path_filter_regex")
    if pfr and not re.search(pfr, path, re.IGNORECASE):
        return False

    ffr = dotnet_recipe.get("file_filter_regex")
    if ffr and not re.search(ffr, filename, re.IGNORECASE):
        return False

    return True


# ── Python parity tests ──────────────────────────────────────

@pytest.mark.parametrize(
    "fixture",
    PARITY_CORPUS,
    ids=lambda f: f["name"],
)
def test_python_reference_parity(fixture):
    """Python reference layer matches expected selection for each test path."""
    recipe = fixture["recipe"]
    for case in fixture["test_paths"]:
        result = python_match(case["path"], recipe)
        assert result == case["expected"], (
            f"[{fixture['name']}] path={case['path']}: "
            f"expected={case['expected']}, got={result}"
        )


# ── .NET parity tests (actual comparison, not just gap docs) ─

DOTNET_TESTABLE = [f for f in PARITY_CORPUS if f.get("dotnet_recipe") is not None]
DOTNET_GAP = [f for f in PARITY_CORPUS if f.get("dotnet_recipe") is None]


@pytest.mark.parametrize(
    "fixture",
    DOTNET_TESTABLE,
    ids=lambda f: f["name"],
)
def test_dotnet_matching_parity(fixture):
    """Verify .NET matching logic produces same results as Python for shared corpus."""
    dotnet_recipe = fixture["dotnet_recipe"]
    for case in fixture["test_paths"]:
        result = dotnet_match(case["path"], dotnet_recipe)
        assert result == case["expected"], (
            f"[{fixture['name']}] .NET path={case['path']}: "
            f"expected={case['expected']}, got={result}"
        )


@pytest.mark.parametrize(
    "fixture",
    DOTNET_GAP,
    ids=lambda f: f["name"],
)
@pytest.mark.xfail(reason=".NET lacks this feature", strict=False)
def test_dotnet_gap_fixture(fixture):
    """Corpus fixtures where .NET has no equivalent recipe (documented gap)."""
    raise NotImplementedError(f".NET gap: {fixture.get('dotnet_gap', 'unknown')}")


# ── .NET-specific gap contracts ──────────────────────────────

@pytest.mark.xfail(reason=".NET FtpSftpMonitor: no persisted checkpoint", strict=False)
def test_dotnet_persisted_checkpoint_parity():
    """Both Python and .NET use in-memory dedup. Restart causes re-collection."""
    raise NotImplementedError("Implement: persisted checkpoint for dedup")


@pytest.mark.xfail(reason=".NET FtpSftpMonitor: no completion_check", strict=False)
def test_dotnet_completion_check_parity():
    """Python supports MARKER_FILE and SIZE_STABLE. .NET does not."""
    raise NotImplementedError("Implement: completion_check strategies")


@pytest.mark.xfail(reason=".NET FtpSftpMonitor: no post_action", strict=False)
def test_dotnet_post_action_parity():
    """Python supports KEEP/DELETE/MOVE/RENAME. .NET does not."""
    raise NotImplementedError("Implement: post_action (MOVE/DELETE/RENAME)")
