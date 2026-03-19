"""WebSocket endpoints for real-time event streaming."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from hermes.domain.models.execution import ExecutionEventLog, WorkItem
from hermes.domain.models.monitoring import PipelineActivation
from hermes.infrastructure.database.session import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections grouped by channel."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(channel, []).append(websocket)
        logger.info("WebSocket connected: %s (total=%d)", channel, len(self._connections[channel]))

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        conns = self._connections.get(channel, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(channel, None)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        """Send a message to all connections on a channel."""
        conns = self._connections.get(channel, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.remove(ws)

    @property
    def active_channels(self) -> list[str]:
        return list(self._connections.keys())


# Global connection manager
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Pipeline events WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/api/v1/ws/pipeline/{pipeline_id}/events")
async def pipeline_events(
    websocket: WebSocket,
    pipeline_id: uuid.UUID,
) -> None:
    """Stream pipeline events in real-time.

    Events include:
    - WORKITEM_CREATED: new work item detected
    - STEP_COMPLETED: a step finished processing
    - PIPELINE_HEARTBEAT: periodic heartbeat
    """
    channel = f"pipeline:{pipeline_id}"
    await manager.connect(channel, websocket)

    try:
        # Poll for new events and send to clients
        last_check = datetime.now(UTC)

        while True:
            try:
                # Check for incoming messages (ping/pong or close)
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=5.0
                    )
                    # Client can send commands (future use)
                    logger.debug("Received from client: %s", data)
                except TimeoutError:
                    pass

                # Poll for new work items and activations
                async with async_session_factory() as db:
                    # Check for new work items
                    stmt = (
                        select(WorkItem)
                        .where(
                            WorkItem.pipeline_instance_id == pipeline_id,
                            WorkItem.detected_at > last_check,
                        )
                        .order_by(WorkItem.detected_at)
                    )
                    result = await db.execute(stmt)
                    new_items = result.scalars().all()

                    for item in new_items:
                        await manager.broadcast(channel, {
                            "type": "WORKITEM_CREATED",
                            "workItem": {
                                "id": str(item.id),
                                "source_key": item.source_key,
                                "status": item.status,
                                "detected_at": item.detected_at.isoformat(),
                            },
                        })

                    # Check latest activation heartbeat
                    stmt_act = (
                        select(PipelineActivation)
                        .where(
                            PipelineActivation.pipeline_instance_id == pipeline_id,
                            PipelineActivation.status.in_(["STARTING", "RUNNING"]),
                        )
                        .order_by(PipelineActivation.started_at.desc())
                        .limit(1)
                    )
                    act_result = await db.execute(stmt_act)
                    activation = act_result.scalar_one_or_none()

                    if activation:
                        await manager.broadcast(channel, {
                            "type": "PIPELINE_HEARTBEAT",
                            "activation": {
                                "id": str(activation.id),
                                "status": activation.status,
                                "last_heartbeat_at": (
                                    activation.last_heartbeat_at.isoformat()
                                    if activation.last_heartbeat_at
                                    else None
                                ),
                            },
                        })

                last_check = datetime.now(UTC)

            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(channel, websocket)


# ---------------------------------------------------------------------------
# Work item log streaming WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/api/v1/ws/work-items/{work_item_id}/logs")
async def work_item_logs(
    websocket: WebSocket,
    work_item_id: uuid.UUID,
) -> None:
    """Stream live execution logs for a work item.

    Events are ExecutionEventLog entries streamed as they appear.
    """
    channel = f"work-item-logs:{work_item_id}"
    await manager.connect(channel, websocket)

    try:
        last_log_id: uuid.UUID | None = None

        while True:
            try:
                # Check for close
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                except TimeoutError:
                    pass

                # Poll for new log entries
                async with async_session_factory() as db:
                    # Get current execution for this work item
                    work_item = await db.get(WorkItem, work_item_id)
                    if work_item is None or work_item.current_execution_id is None:
                        await asyncio.sleep(1)
                        continue

                    stmt = (
                        select(ExecutionEventLog)
                        .where(
                            ExecutionEventLog.execution_id == work_item.current_execution_id,
                        )
                        .order_by(ExecutionEventLog.created_at)
                    )

                    if last_log_id is not None:
                        stmt = stmt.where(ExecutionEventLog.id > last_log_id)

                    result = await db.execute(stmt)
                    logs = result.scalars().all()

                    for log in logs:
                        last_log_id = log.id
                        await manager.broadcast(channel, {
                            "type": "LOG",
                            "event": {
                                "id": str(log.id),
                                "event_type": log.event_type,
                                "event_code": log.event_code,
                                "message": log.message,
                                "detail_json": log.detail_json,
                                "created_at": log.created_at.isoformat(),
                            },
                        })

            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(channel, websocket)
