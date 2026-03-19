#!/usr/bin/env python3
"""Hermes JSON Transform Algorithm Plugin.

Applies JMESPath expressions to transform JSON data.

Requires: pip install jmespath
Falls back to basic dot-notation path extraction if jmespath is not installed.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

try:
    import jmespath

    HAS_JMESPATH = True
except ImportError:
    HAS_JMESPATH = False


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


def simple_path_extract(data: Any, path: str) -> Any:
    """Basic dot-notation path extraction as fallback when jmespath is unavailable."""
    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def apply_transform(
    input_data: Any,
    expression: str,
    fallback: Any = None,
) -> Any:
    """Apply JMESPath expression to input data."""
    if HAS_JMESPATH:
        result = jmespath.search(expression, input_data)
    else:
        result = simple_path_extract(input_data, expression)

    if result is None and fallback is not None:
        return fallback
    return result


def format_output(result: Any, output_format: str) -> Any:
    """Format the transform result according to output_format setting."""
    if output_format == "records":
        if isinstance(result, list):
            return {"records": result, "record_count": len(result)}
        return {"records": [result], "record_count": 1}
    elif output_format == "single":
        return {"record": result}
    else:
        return result


def main() -> None:
    config: dict[str, Any] = {}

    if not HAS_JMESPATH:
        log(
            "jmespath package not installed. Using basic dot-notation fallback. "
            "Install with: pip install jmespath",
            "WARN",
        )

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
            expr = config.get("jmespath_expression", "")
            log(f"Configured JSON transform with expression: {expr}")

        elif msg_type == "EXECUTE":
            expression = config.get("jmespath_expression")
            if not expression:
                error("No jmespath_expression configured", "CONFIG_ERROR")
                done({"transformed": False})
                sys.exit(2)

            input_data = msg.get("input")
            output_fmt = config.get("output_format", "raw")
            fallback = config.get("fallback_value")

            status(0.2)

            try:
                result = apply_transform(input_data, expression, fallback)
                status(0.7)

                formatted = format_output(result, output_fmt)
                output(formatted)

                status(1.0)
                done({
                    "transformed": True,
                    "expression": expression,
                    "output_format": output_fmt,
                    "jmespath_available": HAS_JMESPATH,
                })

            except Exception as exc:
                error(f"Transform error: {exc}", "TRANSFORM_ERROR")
                done({"transformed": False, "error": str(exc)})
                sys.exit(1)


if __name__ == "__main__":
    main()
