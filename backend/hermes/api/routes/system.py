"""System and health check endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.execution import WorkItem
from hermes.domain.models.pipeline import PipelineInstance
from hermes.infrastructure.database.session import get_db
from hermes.infrastructure.nifi.config import NiFiConfig

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str


class SystemStats(BaseModel):
    pipeline_count: int
    active_pipeline_count: int
    work_item_count: int
    completed_count: int
    failed_count: int
    success_rate: float


class NiFiStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    base_url: str | None = None
    error: str | None = None


@router.get("/api/v1/health", response_model=HealthResponse)
async def health_check(
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Health check endpoint."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        version="0.1.0",
        database=db_status,
    )


@router.get("/api/v1/system/stats", response_model=SystemStats)
async def system_stats(
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get system-wide statistics."""
    # Pipeline counts
    total_pipelines = await db.execute(select(func.count()).select_from(PipelineInstance))
    pipeline_count = total_pipelines.scalar() or 0

    active_pipelines = await db.execute(
        select(func.count())
        .select_from(PipelineInstance)
        .where(PipelineInstance.status == "ACTIVE")
    )
    active_count = active_pipelines.scalar() or 0

    # Work item counts
    total_items = await db.execute(select(func.count()).select_from(WorkItem))
    wi_count = total_items.scalar() or 0

    completed = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.status == "COMPLETED")
    )
    completed_count = completed.scalar() or 0

    failed = await db.execute(
        select(func.count())
        .select_from(WorkItem)
        .where(WorkItem.status == "FAILED")
    )
    failed_count = failed.scalar() or 0

    # Success rate
    processed = completed_count + failed_count
    success_rate = (completed_count / processed * 100) if processed > 0 else 0.0

    return SystemStats(
        pipeline_count=pipeline_count,
        active_pipeline_count=active_count,
        work_item_count=wi_count,
        completed_count=completed_count,
        failed_count=failed_count,
        success_rate=round(success_rate, 2),
    )


@router.get("/api/v1/system/nifi-status", response_model=NiFiStatusResponse)
async def nifi_status() -> Any:
    """Get NiFi connection status."""
    config = NiFiConfig()

    if not config.enabled:
        return NiFiStatusResponse(enabled=False, connected=False)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            headers: dict[str, str] = {}
            if config.token:
                headers["Authorization"] = f"Bearer {config.token}"
            resp = await client.get(
                f"{config.base_url.rstrip('/')}/system-diagnostics",
                headers=headers,
            )
            resp.raise_for_status()
            return NiFiStatusResponse(
                enabled=True,
                connected=True,
                base_url=config.base_url,
            )
    except Exception as exc:
        return NiFiStatusResponse(
            enabled=True,
            connected=False,
            base_url=config.base_url,
            error=str(exc),
        )
