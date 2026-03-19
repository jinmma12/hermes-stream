"""Monitoring engine - watches for events and creates work items."""

from __future__ import annotations

import abc
import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hermes.domain.models.execution import WorkItem
from hermes.domain.models.monitoring import PipelineActivation
from hermes.domain.models.pipeline import PipelineInstance

logger = logging.getLogger(__name__)


@dataclass
class MonitorEvent:
    """An event detected by a monitor."""

    event_type: str  # FILE | API_RESPONSE | DB_CHANGE
    key: str  # unique identifier for the source item
    metadata: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Abstract monitor and concrete implementations
# ---------------------------------------------------------------------------


class BaseMonitor(abc.ABC):
    """Abstract base for all monitor types."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abc.abstractmethod
    async def poll(self) -> list[MonitorEvent]:
        """Poll for new events. Returns a list of detected events."""
        ...


class FileMonitor(BaseMonitor):
    """Watches a directory for new or modified files."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.watch_path: str = config.get("watch_path", ".")
        self.pattern: str = config.get("pattern", "*")
        self.recursive: bool = config.get("recursive", False)
        self._seen: set[str] = set()

    async def poll(self) -> list[MonitorEvent]:
        """Check directory for new files matching the pattern."""
        events: list[MonitorEvent] = []
        watch = Path(self.watch_path)
        if not watch.exists():
            logger.warning("Watch path does not exist: %s", self.watch_path)
            return events

        glob_method = watch.rglob if self.recursive else watch.glob
        for path in glob_method(self.pattern):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key not in self._seen:
                self._seen.add(key)
                stat = path.stat()
                events.append(
                    MonitorEvent(
                        event_type="FILE",
                        key=path.name,
                        metadata={
                            "path": key,
                            "size": stat.st_size,
                            "modified_at": datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            ).isoformat(),
                        },
                    )
                )
        return events


class ApiPollMonitor(BaseMonitor):
    """Polls a REST API endpoint at a configured interval."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.url: str = config["url"]
        self.method: str = config.get("method", "GET").upper()
        self.headers: dict[str, str] = config.get("headers", {})
        self._last_hash: str | None = None

    async def poll(self) -> list[MonitorEvent]:
        """Fetch the API endpoint and check for changes."""
        events: list[MonitorEvent] = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(
                    self.method, self.url, headers=self.headers
                )
                resp.raise_for_status()
                body = resp.text
                content_hash = hashlib.sha256(body.encode()).hexdigest()

                if content_hash != self._last_hash:
                    self._last_hash = content_hash
                    events.append(
                        MonitorEvent(
                            event_type="API_RESPONSE",
                            key=content_hash[:16],
                            metadata={
                                "url": self.url,
                                "status_code": resp.status_code,
                                "content_hash": content_hash,
                            },
                        )
                    )
        except Exception as exc:
            logger.error("API poll failed for %s: %s", self.url, exc)
        return events


class DbPollMonitor(BaseMonitor):
    """Polls a database table for new or changed rows."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.connection_string: str = config.get("connection_string", "")
        self.query: str = config.get("query", "")
        self.poll_column: str = config.get("poll_column", "id")
        self._last_value: Any = None

    async def poll(self) -> list[MonitorEvent]:
        """Execute the poll query and detect new rows.

        Uses asyncpg for actual DB polling. For prototype, logs a stub.
        """
        events: list[MonitorEvent] = []
        if not self.connection_string or not self.query:
            logger.debug("DbPollMonitor not configured, skipping")
            return events

        try:
            import asyncpg  # type: ignore[import-untyped]

            conn = await asyncpg.connect(self.connection_string)
            try:
                if self._last_value is not None:
                    rows = await conn.fetch(
                        self.query + f" WHERE {self.poll_column} > $1",
                        self._last_value,
                    )
                else:
                    rows = await conn.fetch(self.query)

                for row in rows:
                    row_dict = dict(row)
                    key = str(row_dict.get(self.poll_column, uuid.uuid4()))
                    self._last_value = row_dict.get(self.poll_column, self._last_value)
                    events.append(
                        MonitorEvent(
                            event_type="DB_CHANGE",
                            key=key,
                            metadata=row_dict,
                        )
                    )
            finally:
                await conn.close()
        except ImportError:
            logger.warning("asyncpg not available, DB polling disabled")
        except Exception as exc:
            logger.error("DB poll failed: %s", exc)

        return events


# ---------------------------------------------------------------------------
# Monitor task wrapper
# ---------------------------------------------------------------------------


@dataclass
class MonitorTask:
    """Tracks a running monitoring loop."""

    activation_id: uuid.UUID
    pipeline_id: uuid.UUID
    task: asyncio.Task[None] | None = None
    monitor: BaseMonitor | None = None


# ---------------------------------------------------------------------------
# Monitoring engine
# ---------------------------------------------------------------------------

_MONITOR_FACTORIES: dict[str, type[BaseMonitor]] = {
    "FILE_MONITOR": FileMonitor,
    "API_POLL": ApiPollMonitor,
    "DB_POLL": DbPollMonitor,
}


class MonitoringEngine:
    """Manages active monitoring loops for pipeline activations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self.monitors: dict[uuid.UUID, MonitorTask] = {}

    def _create_monitor(
        self, monitoring_type: str, config: dict[str, Any]
    ) -> BaseMonitor:
        """Create a monitor instance from type and config."""
        factory = _MONITOR_FACTORIES.get(monitoring_type.upper())
        if factory is None:
            raise ValueError(
                f"Unknown monitoring_type '{monitoring_type}'. "
                f"Supported: {list(_MONITOR_FACTORIES.keys())}"
            )
        return factory(config)

    async def start_monitoring(self, activation: PipelineActivation) -> None:
        """Start a monitoring loop for an activation."""
        if activation.id in self.monitors:
            logger.warning("Monitoring already running for activation %s", activation.id)
            return

        async with self.session_factory() as db:
            pipeline = await db.get(PipelineInstance, activation.pipeline_instance_id)
            if pipeline is None:
                raise ValueError(f"Pipeline {activation.pipeline_instance_id} not found")
            monitoring_type = pipeline.monitoring_type or "FILE_MONITOR"
            monitoring_config = pipeline.monitoring_config or {}

        monitor = self._create_monitor(monitoring_type, monitoring_config)
        mt = MonitorTask(
            activation_id=activation.id,
            pipeline_id=activation.pipeline_instance_id,
            monitor=monitor,
        )
        mt.task = asyncio.create_task(
            self._monitoring_loop(activation.id, monitor, monitoring_config)
        )
        self.monitors[activation.id] = mt
        logger.info("Started monitoring for activation %s", activation.id)

    async def stop_monitoring(self, activation_id: uuid.UUID) -> None:
        """Stop a running monitoring loop."""
        mt = self.monitors.pop(activation_id, None)
        if mt is None:
            logger.warning("No monitoring found for activation %s", activation_id)
            return
        if mt.task and not mt.task.done():
            mt.task.cancel()
            try:
                await mt.task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped monitoring for activation %s", activation_id)

    async def stop_all(self) -> None:
        """Stop all running monitoring loops."""
        ids = list(self.monitors.keys())
        for aid in ids:
            await self.stop_monitoring(aid)

    async def _monitoring_loop(
        self,
        activation_id: uuid.UUID,
        monitor: BaseMonitor,
        config: dict[str, Any],
    ) -> None:
        """Main polling loop following ARCHITECTURE.md section 11.1."""
        interval = config.get("interval", 60)
        if isinstance(interval, str):
            # Parse simple duration strings like "5m", "30s"
            interval = _parse_interval(interval)

        from hermes.domain.services.condition_evaluator import ConditionEvaluator

        evaluator = ConditionEvaluator()

        while True:
            try:
                async with self.session_factory() as db:
                    # Check activation is still running
                    activation = await db.get(PipelineActivation, activation_id)
                    if activation is None or activation.status not in ("STARTING", "RUNNING"):
                        logger.info("Activation %s is no longer running, stopping loop", activation_id)
                        break

                    # Update to RUNNING if still STARTING
                    if activation.status == "STARTING":
                        activation.status = "RUNNING"

                    # 1. Poll for events
                    events = await monitor.poll()

                    for event in events:
                        # 2. Evaluate conditions
                        pipeline = await db.get(
                            PipelineInstance, activation.pipeline_instance_id
                        )
                        if pipeline is None:
                            continue

                        if not evaluator.evaluate(event, pipeline):
                            continue

                        # 3. Dedup check
                        dedup_key = evaluator.generate_dedup_key(event)
                        existing = await db.execute(
                            select(WorkItem).where(WorkItem.dedup_key == dedup_key).limit(1)
                        )
                        if existing.scalar_one_or_none() is not None:
                            continue

                        # 4. Create WorkItem
                        work_item = WorkItem(
                            pipeline_activation_id=activation.id,
                            pipeline_instance_id=activation.pipeline_instance_id,
                            source_type=event.event_type,
                            source_key=event.key,
                            source_metadata=event.metadata,
                            dedup_key=dedup_key,
                            detected_at=event.detected_at,
                            status="QUEUED",
                        )
                        db.add(work_item)
                        logger.info(
                            "Created work item for event %s (dedup=%s)",
                            event.key,
                            dedup_key,
                        )

                    # 6. Update heartbeat
                    now = datetime.now(timezone.utc)
                    activation.last_heartbeat_at = now
                    activation.last_polled_at = now
                    await db.commit()

            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in monitoring loop for %s", activation_id)

            # 7. Wait for next poll
            await asyncio.sleep(interval)


def _parse_interval(value: str) -> int:
    """Parse a duration string like '5m', '30s', '1h' into seconds."""
    value = value.strip().lower()
    if value.endswith("s"):
        return int(value[:-1])
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    try:
        return int(value)
    except ValueError:
        return 60
