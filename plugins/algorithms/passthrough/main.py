#!/usr/bin/env python3
"""Vessel Passthrough Algorithm Plugin.

Default algorithm that passes input data through unchanged.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def send_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(message: str, level: str = "INFO") -> None:
    send_message({"type": "LOG", "level": level, "message": message})


def output(data: Any) -> None:
    send_message({"type": "OUTPUT", "data": data})


def done(summary: dict[str, Any]) -> None:
    send_message({"type": "DONE", "summary": summary})


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
            log("Passthrough algorithm configured")

        elif msg_type == "EXECUTE":
            input_data = msg.get("input")

            if config.get("log_passthrough", False):
                if isinstance(input_data, dict):
                    keys = list(input_data.keys())
                    log(f"Passing through data with keys: {keys}")
                elif isinstance(input_data, list):
                    log(f"Passing through list of {len(input_data)} items")
                else:
                    log(f"Passing through data of type: {type(input_data).__name__}")

            output(input_data)
            done({"action": "passthrough", "modified": False})


if __name__ == "__main__":
    main()
