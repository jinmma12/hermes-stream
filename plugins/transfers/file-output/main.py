#!/usr/bin/env python3
"""Vessel File Output Transfer Plugin.

Writes data to files in JSON, JSONL, CSV, or plain text format.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import uuid
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


def resolve_filename(template: str, index: int = 0) -> str:
    """Resolve filename template placeholders."""
    now = datetime.now(tz=timezone.utc)
    return template.format(
        timestamp=now.strftime("%Y%m%d_%H%M%S"),
        date=now.strftime("%Y-%m-%d"),
        uuid=str(uuid.uuid4())[:8],
        index=index,
    )


def write_json(data: Any, path: Path, indent: int) -> int:
    """Write data as JSON file."""
    content = json.dumps(data, ensure_ascii=False, indent=indent if indent > 0 else None)
    path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def write_jsonl(data: Any, path: Path) -> int:
    """Write data as JSON Lines file (one JSON object per line)."""
    records = data if isinstance(data, list) else [data]
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def write_csv(data: Any, path: Path, delimiter: str) -> int:
    """Write data as CSV file."""
    records: list[dict[str, Any]]
    if isinstance(data, dict) and "records" in data:
        records = data["records"]
    elif isinstance(data, list):
        records = data
    else:
        records = [data] if isinstance(data, dict) else [{"value": data}]

    if not records:
        path.write_text("", encoding="utf-8")
        return 0

    buf = io.StringIO()
    # Gather all keys across all records for the header
    fieldnames: list[str] = []
    seen: set[str] = set()
    for record in records:
        if isinstance(record, dict):
            for key in record:
                if key not in seen:
                    fieldnames.append(key)
                    seen.add(key)

    writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=delimiter, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        if isinstance(record, dict):
            writer.writerow(record)

    content = buf.getvalue()
    path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


def write_text(data: Any, path: Path) -> int:
    """Write data as plain text."""
    if isinstance(data, str):
        content = data
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return len(content.encode("utf-8"))


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
            log(f"Configured file output to {config.get('output_dir', '?')}")

        elif msg_type == "EXECUTE":
            output_dir = config.get("output_dir")
            if not output_dir:
                error("No output_dir configured", "CONFIG_ERROR")
                done({"bytes_written": 0})
                sys.exit(2)

            status(0.1)
            input_data = msg.get("input")
            fmt = config.get("format", "json")
            template = config.get("filename_template", f"output_{{timestamp}}.{fmt}")
            indent = config.get("json_indent", 2)
            delimiter = config.get("csv_delimiter", ",")
            create_dirs = config.get("create_dirs", True)
            overwrite = config.get("overwrite", False)

            out_path = Path(output_dir)
            if create_dirs:
                out_path.mkdir(parents=True, exist_ok=True)

            if not out_path.is_dir():
                error(f"Output directory does not exist: {output_dir}", "PATH_NOT_FOUND")
                done({"bytes_written": 0})
                sys.exit(1)

            filename = resolve_filename(template)
            file_path = out_path / filename

            if file_path.exists() and not overwrite:
                # Append index to avoid collision
                stem = file_path.stem
                suffix = file_path.suffix
                counter = 1
                while file_path.exists():
                    file_path = out_path / f"{stem}_{counter}{suffix}"
                    counter += 1

            status(0.4)
            log(f"Writing {fmt} to {file_path}")

            try:
                if fmt == "json":
                    bytes_written = write_json(input_data, file_path, indent)
                elif fmt == "jsonl":
                    bytes_written = write_jsonl(input_data, file_path)
                elif fmt == "csv":
                    bytes_written = write_csv(input_data, file_path, delimiter)
                elif fmt == "text":
                    bytes_written = write_text(input_data, file_path)
                else:
                    error(f"Unsupported format: {fmt}", "FORMAT_ERROR")
                    done({"bytes_written": 0})
                    sys.exit(1)

                status(1.0)
                log(f"Wrote {bytes_written} bytes to {file_path}")

                output({
                    "file_path": str(file_path),
                    "bytes_written": bytes_written,
                })

                done({
                    "file_path": str(file_path),
                    "bytes_written": bytes_written,
                    "format": fmt,
                })

            except PermissionError as exc:
                error(f"Permission denied: {exc}", "PERMISSION_ERROR")
                done({"bytes_written": 0})
                sys.exit(1)

            except Exception as exc:
                error(f"Write error: {exc}", "WRITE_ERROR")
                done({"bytes_written": 0})
                sys.exit(1)


if __name__ == "__main__":
    main()
