"""Vessel Plugin Protocol v1.

Language-agnostic JSON line protocol for communication between Vessel Core
and plugin subprocesses via stdin/stdout.

Direction: Vessel Core -> Plugin (stdin)
  CONFIGURE - send plugin configuration and context
  EXECUTE   - send input data for processing

Direction: Plugin -> Vessel Core (stdout)
  LOG    - log message with level
  OUTPUT - output data record
  ERROR  - error with code and message
  STATUS - progress update (0.0 to 1.0)
  DONE   - execution complete with summary
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from io import TextIOBase
from typing import Any


class MessageType(StrEnum):
    """Types of messages in the Vessel Plugin Protocol."""

    # Vessel Core -> Plugin
    CONFIGURE = "CONFIGURE"
    EXECUTE = "EXECUTE"

    # Plugin -> Vessel Core
    LOG = "LOG"
    OUTPUT = "OUTPUT"
    ERROR = "ERROR"
    STATUS = "STATUS"
    DONE = "DONE"


@dataclass
class VesselMessage:
    """A single message in the Vessel Plugin Protocol.

    Messages are serialized as single-line JSON objects, one per line.
    """

    type: MessageType
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to a single-line JSON string."""
        payload: dict[str, Any] = {"type": self.type.value}
        payload.update(self.data)
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> VesselMessage:
        """Deserialize from a JSON line string.

        Raises:
            ValueError: If the line is not valid JSON or missing 'type' field.
        """
        line = line.strip()
        if not line:
            raise ValueError("Empty message line")

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if "type" not in payload:
            raise ValueError("Message missing required 'type' field")

        try:
            msg_type = MessageType(payload.pop("type"))
        except ValueError:
            raise ValueError(f"Unknown message type: {payload.get('type')}")

        return cls(type=msg_type, data=payload)

    # Convenience factory methods for outbound (Plugin -> Core) messages

    @classmethod
    def log(cls, message: str, level: str = "INFO") -> VesselMessage:
        """Create a LOG message."""
        return cls(type=MessageType.LOG, data={"level": level, "message": message})

    @classmethod
    def output(cls, data: Any) -> VesselMessage:
        """Create an OUTPUT message."""
        return cls(type=MessageType.OUTPUT, data={"data": data})

    @classmethod
    def error(cls, message: str, code: str = "PLUGIN_ERROR") -> VesselMessage:
        """Create an ERROR message."""
        return cls(type=MessageType.ERROR, data={"code": code, "message": message})

    @classmethod
    def status(cls, progress: float) -> VesselMessage:
        """Create a STATUS message with progress (0.0 to 1.0)."""
        return cls(
            type=MessageType.STATUS,
            data={"progress": min(1.0, max(0.0, progress))},
        )

    @classmethod
    def done(cls, summary: dict[str, Any] | None = None) -> VesselMessage:
        """Create a DONE message."""
        return cls(type=MessageType.DONE, data={"summary": summary or {}})

    # Convenience factory methods for inbound (Core -> Plugin) messages

    @classmethod
    def configure(
        cls,
        config: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> VesselMessage:
        """Create a CONFIGURE message."""
        return cls(
            type=MessageType.CONFIGURE,
            data={"config": config, "context": context or {}},
        )

    @classmethod
    def execute(cls, input_data: Any) -> VesselMessage:
        """Create an EXECUTE message."""
        return cls(type=MessageType.EXECUTE, data={"input": input_data})


class PluginProtocol:
    """Handles reading and writing Vessel protocol messages over streams.

    This class is used both by the Vessel Core (writing to plugin stdin,
    reading from plugin stdout) and by plugins themselves (reading from
    their own stdin, writing to their own stdout).
    """

    @staticmethod
    def send_message(message: VesselMessage, stream: TextIOBase | Any = None) -> None:
        """Write a message as a JSON line to the given stream.

        Args:
            message: The VesselMessage to send.
            stream: Writable text stream. Defaults to sys.stdout.
        """
        output = stream if stream is not None else sys.stdout
        line = message.to_json()
        output.write(line + "\n")
        output.flush()

    @staticmethod
    def read_message(stream: TextIOBase | Any = None) -> VesselMessage | None:
        """Read a single message from the given stream.

        Blocks until a line is available. Returns None on EOF.

        Args:
            stream: Readable text stream. Defaults to sys.stdin.

        Returns:
            Parsed VesselMessage, or None on EOF.

        Raises:
            ValueError: If the line is not a valid protocol message.
        """
        input_stream = stream if stream is not None else sys.stdin
        line = input_stream.readline()
        if not line:
            return None  # EOF
        return VesselMessage.from_json(line)

    @staticmethod
    def read_all_messages(
        stream: TextIOBase | Any = None,
    ) -> list[VesselMessage]:
        """Read all available messages from the stream until EOF.

        Args:
            stream: Readable text stream. Defaults to sys.stdin.

        Returns:
            List of parsed VesselMessages.
        """
        messages: list[VesselMessage] = []
        while True:
            msg = PluginProtocol.read_message(stream)
            if msg is None:
                break
            messages.append(msg)
        return messages
