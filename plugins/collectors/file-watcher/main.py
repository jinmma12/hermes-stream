#!/usr/bin/env python3
"""Hermes File Watcher Collector Plugin.

Scans a directory for files matching a glob pattern and outputs
file metadata via the Hermes plugin protocol.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def send_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(message: str, level: str = "INFO") -> None:
    send_message({"type": "LOG", "level": level, "message": message})


def output(data: Any) -> None:
    send_message({"type": "OUTPUT", "data": data})


def error(message: str, code: str = "PLUGIN_ERROR") -> None:
    send_message({"type": "ERROR", "code": code, "message": message})


def done(summary: dict[str, Any]) -> None:
    send_message({"type": "DONE", "summary": summary})


def status(progress: float) -> None:
    send_message({"type": "STATUS", "progress": progress})


def scan_directory(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan the configured directory for matching files."""
    watch_path = Path(config["watch_path"])
    pattern = config.get("pattern", "*")
    recursive = config.get("recursive", False)
    min_size = config.get("min_file_size", 0)

    if not watch_path.is_dir():
        raise FileNotFoundError(f"Watch directory does not exist: {watch_path}")

    if recursive:
        matches = list(watch_path.rglob(pattern))
    else:
        matches = list(watch_path.glob(pattern))

    files: list[dict[str, Any]] = []
    for file_path in sorted(matches):
        if not file_path.is_file():
            continue

        stat = file_path.stat()
        if stat.st_size < min_size:
            continue

        modified_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        files.append({
            "path": str(file_path),
            "name": file_path.name,
            "size": stat.st_size,
            "modified": modified_dt.isoformat(),
        })

    return files


def main() -> None:
    config: dict[str, Any] = {}

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type")

        if msg_type == "CONFIGURE":
            config = msg.get("config", {})
            log(f"Configured file watcher for {config.get('watch_path', '?')}")

        elif msg_type == "EXECUTE":
            if not config.get("watch_path"):
                error("No watch_path configured", "CONFIG_ERROR")
                done({"file_count": 0})
                sys.exit(2)

            status(0.1)
            log(f"Scanning {config['watch_path']} for '{config.get('pattern', '*')}'")

            try:
                status(0.3)
                files = scan_directory(config)
                status(0.8)

                log(f"Found {len(files)} matching files")

                output({
                    "files": files,
                    "file_count": len(files),
                })

                status(1.0)
                done({"file_count": len(files)})

            except FileNotFoundError as exc:
                error(str(exc), "PATH_NOT_FOUND")
                done({"file_count": 0})
                sys.exit(1)

            except PermissionError as exc:
                error(f"Permission denied: {exc}", "PERMISSION_ERROR")
                done({"file_count": 0})
                sys.exit(1)

            except Exception as exc:
                error(f"Unexpected error: {exc}", "SCAN_ERROR")
                done({"file_count": 0})
                sys.exit(1)


if __name__ == "__main__":
    main()
