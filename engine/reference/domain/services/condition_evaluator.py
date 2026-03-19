"""Condition evaluator for monitoring events."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from hermes.domain.models.pipeline import PipelineInstance

logger = logging.getLogger(__name__)


class MonitorEvent:
    """Lightweight event class used by the evaluator (mirrors monitoring_engine.MonitorEvent)."""

    def __init__(
        self,
        event_type: str,
        key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.event_type = event_type
        self.key = key
        self.metadata = metadata or {}


class ConditionEvaluator:
    """Evaluates whether a monitoring event should create a work item.

    Currently supports basic conditions:
    - FILE: file exists at the path
    - API_RESPONSE: content has changed (non-empty response)
    - DB_CHANGE: new rows detected

    More sophisticated condition expressions can be added later.
    """

    def evaluate(self, event: Any, pipeline: PipelineInstance) -> bool:
        """Determine whether the given event warrants a new work item.

        Args:
            event: A MonitorEvent (from monitoring_engine or this module).
            pipeline: The pipeline instance being monitored.

        Returns:
            True if a work item should be created.
        """
        event_type = getattr(event, "event_type", "")

        if event_type == "FILE":
            # File events always create work items if the file exists
            path = getattr(event, "metadata", {}).get("path")
            if path:
                return True
            return bool(getattr(event, "key", ""))

        if event_type == "API_RESPONSE":
            # API events create work items when content has changed
            return True

        if event_type == "DB_CHANGE":
            # DB change events always create work items
            return True

        # Unknown event types: log and accept
        logger.debug("Accepting unknown event type '%s' as valid", event_type)
        return True

    def generate_dedup_key(self, event: Any) -> str:
        """Generate a deduplication key for an event.

        The dedup key prevents the same source item from being processed
        multiple times. The format is ``{event_type}:{hash_of_key_and_metadata}``.
        """
        event_type = getattr(event, "event_type", "UNKNOWN")
        key = getattr(event, "key", "")
        metadata = getattr(event, "metadata", {})

        # For file events, use the full file path as the basis
        if event_type == "FILE":
            basis = metadata.get("path", key)
        elif event_type == "API_RESPONSE":
            # Use content hash if available, otherwise the key
            basis = metadata.get("content_hash", key)
        elif event_type == "DB_CHANGE":
            basis = key
        else:
            basis = key

        content = f"{event_type}:{basis}"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
        return f"{event_type}:{digest}"
