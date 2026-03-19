#!/usr/bin/env python3
"""Hermes REST API Transfer Plugin.

Sends processed data to a REST API endpoint via HTTP.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any, Optional


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


def send_http(
    url: str,
    method: str,
    headers: dict[str, str],
    payload: Any,
    timeout: int,
) -> dict[str, Any]:
    """Send data via HTTP and return response info."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    all_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    all_headers.update(headers)

    req = urllib.request.Request(url, data=body, headers=all_headers, method=method)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        response_text = resp.read().decode(charset)
        try:
            response_data = json.loads(response_text)
        except json.JSONDecodeError:
            response_data = response_text

        return {
            "status_code": resp.status,
            "response": response_data,
        }


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
            log(f"Configured REST API transfer to {config.get('url', '?')}")

        elif msg_type == "EXECUTE":
            url = config.get("url")
            if not url:
                error("No URL configured", "CONFIG_ERROR")
                done({"records_sent": 0})
                sys.exit(2)

            method = config.get("method", "POST")
            timeout = config.get("timeout_seconds", 30)
            batch_size = config.get("batch_size", 0)
            input_data = msg.get("input")

            # Build headers
            headers: dict[str, str] = {}
            headers.update(config.get("headers", {}))
            headers.update(build_auth_headers(config))

            status(0.1)
            log(f"Sending data via {method} to {url}")

            try:
                # Determine records to send
                records: list[Any]
                if isinstance(input_data, dict) and "records" in input_data:
                    records = input_data["records"]
                elif isinstance(input_data, list):
                    records = input_data
                else:
                    records = [input_data]

                total_sent = 0
                last_response: dict[str, Any] = {}

                if batch_size > 0 and len(records) > batch_size:
                    # Send in batches
                    batches = [
                        records[i : i + batch_size]
                        for i in range(0, len(records), batch_size)
                    ]
                    for idx, batch in enumerate(batches):
                        progress = 0.1 + (0.8 * (idx + 1) / len(batches))
                        status(progress)
                        log(f"Sending batch {idx + 1}/{len(batches)} ({len(batch)} records)")
                        last_response = send_http(url, method, headers, batch, timeout)
                        total_sent += len(batch)
                else:
                    # Send all at once
                    status(0.5)
                    payload = records if len(records) > 1 else (records[0] if records else None)
                    last_response = send_http(url, method, headers, payload, timeout)
                    total_sent = len(records)

                status(1.0)
                log(f"Sent {total_sent} records, status {last_response.get('status_code')}")

                output({
                    "status_code": last_response.get("status_code"),
                    "response": last_response.get("response"),
                    "records_sent": total_sent,
                })

                done({
                    "records_sent": total_sent,
                    "status_code": last_response.get("status_code"),
                })

            except urllib.error.HTTPError as exc:
                error(f"HTTP {exc.code}: {exc.reason}", "HTTP_ERROR")
                done({"records_sent": 0, "error": str(exc)})
                sys.exit(1)

            except urllib.error.URLError as exc:
                error(f"Connection error: {exc.reason}", "CONNECTION_ERROR")
                done({"records_sent": 0, "error": str(exc)})
                sys.exit(1)

            except Exception as exc:
                error(f"Transfer error: {exc}", "TRANSFER_ERROR")
                done({"records_sent": 0, "error": str(exc)})
                sys.exit(1)


if __name__ == "__main__":
    main()
