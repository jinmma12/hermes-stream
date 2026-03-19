#!/usr/bin/env python3
"""Hermes REST API Collector Plugin.

Fetches data from a REST API endpoint and outputs the records
via the Hermes plugin protocol.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Optional


def send_message(msg: dict[str, Any]) -> None:
    """Send a JSON line message to stdout."""
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


def extract_records(data: Any, path: Optional[str]) -> list[Any]:
    """Extract records from response data using dot-notation path."""
    if not path:
        if isinstance(data, list):
            return data
        return [data]

    current = data
    for key in path.split("."):
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            raise ValueError(f"Path '{path}' not found in response data at key '{key}'")

    if isinstance(current, list):
        return current
    return [current]


def build_auth_headers(config: dict[str, Any]) -> dict[str, str]:
    """Build authentication headers from config."""
    auth_type = config.get("auth_type", "none")
    auth_token = config.get("auth_token", "")
    headers: dict[str, str] = {}

    if auth_type == "bearer" and auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    elif auth_type == "basic" and auth_token:
        headers["Authorization"] = f"Basic {auth_token}"
    elif auth_type == "api_key" and auth_token:
        key_header = config.get("api_key_header", "X-API-Key")
        headers[key_header] = auth_token

    return headers


def fetch_url(config: dict[str, Any]) -> Any:
    """Fetch data from the configured URL."""
    url = config["url"]
    method = config.get("method", "GET")
    timeout = config.get("timeout_seconds", 30)

    # Build headers
    headers: dict[str, str] = {"Accept": "application/json"}
    headers.update(config.get("headers", {}))
    headers.update(build_auth_headers(config))

    # Build request body
    body_data: Optional[bytes] = None
    body = config.get("body")
    if body and method in ("POST", "PUT", "PATCH"):
        headers["Content-Type"] = "application/json"
        body_data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body_data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        response_text = resp.read().decode(charset)
        return json.loads(response_text)


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
            log(f"Configured REST API collector for {config.get('url', '?')}")

        elif msg_type == "EXECUTE":
            if not config.get("url"):
                error("No URL configured", "CONFIG_ERROR")
                done({"record_count": 0})
                sys.exit(2)

            status(0.1)
            log(f"Fetching {config.get('method', 'GET')} {config['url']}")

            try:
                status(0.3)
                response_data = fetch_url(config)
                status(0.7)

                records_path = config.get("records_path")
                records = extract_records(response_data, records_path)

                log(f"Extracted {len(records)} records")

                output({
                    "records": records,
                    "record_count": len(records),
                })

                status(1.0)
                done({"record_count": len(records)})

            except urllib.error.HTTPError as exc:
                error(
                    f"HTTP {exc.code}: {exc.reason}",
                    "HTTP_ERROR",
                )
                done({"record_count": 0, "error": str(exc)})
                sys.exit(1)

            except urllib.error.URLError as exc:
                error(f"Connection error: {exc.reason}", "CONNECTION_ERROR")
                done({"record_count": 0, "error": str(exc)})
                sys.exit(1)

            except Exception as exc:
                error(f"Unexpected error: {exc}", "FETCH_ERROR")
                done({"record_count": 0, "error": str(exc)})
                sys.exit(1)


if __name__ == "__main__":
    main()
