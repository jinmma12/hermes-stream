"""API routes for WorkItem operations (Layer 4: Execution tracking)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vessel.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    ReprocessRequest,
    WorkItem,
    WorkItemExecution,
    WorkItemStepExecution,
)
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.infrastructure.database.session import get_db

router = APIRouter(prefix="/api/v1/work-items", tags=["work-items"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class WorkItemOut(BaseModel):
    id: uuid.UUID
    pipeline_activation_id: uuid.UUID
    pipeline_instance_id: uuid.UUID
    source_type: str
    source_key: str
    source_metadata: dict[str, Any]
    dedup_key: str | None = None
    detected_at: str
    status: str
    current_execution_id: uuid.UUID | None = None
    execution_count: int
    last_completed_at: str | None = None

    model_config = {"from_attributes": True}


class ExecutionOut(BaseModel):
    id: uuid.UUID
    work_item_id: uuid.UUID
    execution_no: int
    trigger_type: str
    trigger_source: str | None = None
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    reprocess_request_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class StepExecutionOut(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    pipeline_step_id: uuid.UUID
    step_type: str
    step_order: int
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    input_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_attempt: int

    model_config = {"from_attributes": True}


class SnapshotOut(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    pipeline_config: dict[str, Any]
    collector_config: dict[str, Any]
    algorithm_config: dict[str, Any]
    transfer_config: dict[str, Any]
    snapshot_hash: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class EventLogOut(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    step_execution_id: uuid.UUID | None = None
    event_type: str
    event_code: str
    message: str | None = None
    detail_json: dict[str, Any] | None = None
    created_at: str

    model_config = {"from_attributes": True}


class ReprocessCreate(BaseModel):
    reason: str
    requested_by: str = "user"
    start_from_step: int | None = None
    use_latest_recipe: bool = True


class BulkReprocessCreate(BaseModel):
    work_item_ids: list[uuid.UUID]
    reason: str
    requested_by: str = "user"
    start_from_step: int | None = None
    use_latest_recipe: bool = True


class ReprocessRequestOut(BaseModel):
    id: uuid.UUID
    work_item_id: uuid.UUID
    requested_by: str
    requested_at: str
    reason: str | None = None
    start_from_step: int | None = None
    use_latest_recipe: bool
    status: str
    execution_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class PaginatedWorkItems(BaseModel):
    items: list[WorkItemOut]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# WorkItem endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=PaginatedWorkItems)
async def list_work_items(
    status_filter: str | None = Query(None, alias="status"),
    pipeline_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List work items with filtering and pagination."""
    base_stmt = select(WorkItem)
    count_stmt = select(func.count()).select_from(WorkItem)

    if status_filter:
        base_stmt = base_stmt.where(WorkItem.status == status_filter)
        count_stmt = count_stmt.where(WorkItem.status == status_filter)
    if pipeline_id:
        base_stmt = base_stmt.where(WorkItem.pipeline_instance_id == pipeline_id)
        count_stmt = count_stmt.where(WorkItem.pipeline_instance_id == pipeline_id)
    if date_from:
        base_stmt = base_stmt.where(WorkItem.detected_at >= date_from)
        count_stmt = count_stmt.where(WorkItem.detected_at >= date_from)
    if date_to:
        base_stmt = base_stmt.where(WorkItem.detected_at <= date_to)
        count_stmt = count_stmt.where(WorkItem.detected_at <= date_to)

    # Total count
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Paginated items
    stmt = (
        base_stmt
        .order_by(WorkItem.detected_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return PaginatedWorkItems(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{work_item_id}", response_model=WorkItemOut)
async def get_work_item(
    work_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a single work item by ID."""
    work_item = await db.get(WorkItem, work_item_id)
    if work_item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    return work_item


# ---------------------------------------------------------------------------
# Execution endpoints
# ---------------------------------------------------------------------------


@router.get("/{work_item_id}/executions", response_model=list[ExecutionOut])
async def list_executions(
    work_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all executions for a work item."""
    stmt = (
        select(WorkItemExecution)
        .where(WorkItemExecution.work_item_id == work_item_id)
        .order_by(WorkItemExecution.execution_no.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{work_item_id}/executions/{exec_id}", response_model=ExecutionOut)
async def get_execution(
    work_item_id: uuid.UUID,
    exec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a specific execution."""
    stmt = select(WorkItemExecution).where(
        WorkItemExecution.id == exec_id,
        WorkItemExecution.work_item_id == work_item_id,
    )
    result = await db.execute(stmt)
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@router.get(
    "/{work_item_id}/executions/{exec_id}/steps",
    response_model=list[StepExecutionOut],
)
async def list_step_executions(
    work_item_id: uuid.UUID,
    exec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List step executions for a given execution."""
    # Verify execution belongs to work item
    stmt_check = select(WorkItemExecution).where(
        WorkItemExecution.id == exec_id,
        WorkItemExecution.work_item_id == work_item_id,
    )
    check_result = await db.execute(stmt_check)
    if check_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    stmt = (
        select(WorkItemStepExecution)
        .where(WorkItemStepExecution.execution_id == exec_id)
        .order_by(WorkItemStepExecution.step_order)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/{work_item_id}/executions/{exec_id}/snapshot",
    response_model=SnapshotOut,
)
async def get_execution_snapshot(
    work_item_id: uuid.UUID,
    exec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get the configuration snapshot for an execution."""
    stmt = select(ExecutionSnapshot).where(ExecutionSnapshot.execution_id == exec_id)
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot


@router.get(
    "/{work_item_id}/executions/{exec_id}/logs",
    response_model=list[EventLogOut],
)
async def list_execution_logs(
    work_item_id: uuid.UUID,
    exec_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get the event log for an execution."""
    stmt = (
        select(ExecutionEventLog)
        .where(ExecutionEventLog.execution_id == exec_id)
        .order_by(ExecutionEventLog.created_at)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Reprocess endpoints
# ---------------------------------------------------------------------------


@router.post("/{work_item_id}/reprocess", response_model=ReprocessRequestOut)
async def reprocess_work_item(
    work_item_id: uuid.UUID,
    body: ReprocessCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a reprocess request for a work item."""
    work_item = await db.get(WorkItem, work_item_id)
    if work_item is None:
        raise HTTPException(status_code=404, detail="Work item not found")

    rr = ReprocessRequest(
        work_item_id=work_item_id,
        requested_by=body.requested_by,
        reason=body.reason,
        start_from_step=body.start_from_step,
        use_latest_recipe=body.use_latest_recipe,
        status="PENDING",
    )
    db.add(rr)
    await db.flush()
    return rr


@router.post("/bulk-reprocess", response_model=list[ReprocessRequestOut])
async def bulk_reprocess(
    body: BulkReprocessCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create reprocess requests for multiple work items."""
    orchestrator = ProcessingOrchestrator(db)
    try:
        requests = await orchestrator.bulk_reprocess(
            work_item_ids=body.work_item_ids,
            reason=body.reason,
            requested_by=body.requested_by,
            start_from_step=body.start_from_step,
            use_latest_recipe=body.use_latest_recipe,
        )
        return requests
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
