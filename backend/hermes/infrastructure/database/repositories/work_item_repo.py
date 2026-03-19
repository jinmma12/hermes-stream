"""Repository for work items, executions, and reprocess requests."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from hermes.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    ReprocessRequest,
    WorkItem,
    WorkItemExecution,
    WorkItemStepExecution,
)


class WorkItemRepository:
    """CRUD and query operations for work items and their executions."""

    # ------------------------------------------------------------------
    # Work Item CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        pipeline_activation_id: uuid.UUID,
        pipeline_instance_id: uuid.UUID,
        source_type: str,
        source_key: str,
        source_metadata: dict[str, Any] | None = None,
        dedup_key: str | None = None,
    ) -> WorkItem:
        item = WorkItem(
            pipeline_activation_id=pipeline_activation_id,
            pipeline_instance_id=pipeline_instance_id,
            source_type=source_type,
            source_key=source_key,
            source_metadata=source_metadata or {},
            dedup_key=dedup_key,
        )
        db.add(item)
        await db.flush()
        return item

    async def get_by_id(
        self,
        db: AsyncSession,
        work_item_id: uuid.UUID,
        *,
        with_executions: bool = False,
    ) -> WorkItem | None:
        stmt = select(WorkItem).where(WorkItem.id == work_item_id)
        if with_executions:
            stmt = stmt.options(
                selectinload(WorkItem.executions).selectinload(
                    WorkItemExecution.step_executions
                )
            )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_pipeline(
        self,
        db: AsyncSession,
        pipeline_instance_id: uuid.UUID,
        *,
        status: str | None = None,
        source_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorkItem], int]:
        """List work items for a pipeline with optional filters."""
        stmt = select(WorkItem).where(WorkItem.pipeline_instance_id == pipeline_instance_id)
        count_stmt = select(func.count()).select_from(WorkItem).where(
            WorkItem.pipeline_instance_id == pipeline_instance_id
        )

        if status is not None:
            stmt = stmt.where(WorkItem.status == status)
            count_stmt = count_stmt.where(WorkItem.status == status)
        if source_type is not None:
            stmt = stmt.where(WorkItem.source_type == source_type)
            count_stmt = count_stmt.where(WorkItem.source_type == source_type)

        stmt = stmt.order_by(WorkItem.detected_at.desc()).offset(offset).limit(limit)

        total = (await db.execute(count_stmt)).scalar_one()
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_activation(
        self,
        db: AsyncSession,
        activation_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[WorkItem], int]:
        """List work items for a specific activation."""
        stmt = select(WorkItem).where(WorkItem.pipeline_activation_id == activation_id)
        count_stmt = select(func.count()).select_from(WorkItem).where(
            WorkItem.pipeline_activation_id == activation_id
        )

        stmt = stmt.order_by(WorkItem.detected_at.desc()).offset(offset).limit(limit)

        total = (await db.execute(count_stmt)).scalar_one()
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # Dedup check
    # ------------------------------------------------------------------

    async def check_dedup(
        self,
        db: AsyncSession,
        pipeline_instance_id: uuid.UUID,
        dedup_key: str,
    ) -> WorkItem | None:
        """Check if a work item with the given dedup_key already exists for this pipeline."""
        stmt = select(WorkItem).where(
            WorkItem.pipeline_instance_id == pipeline_instance_id,
            WorkItem.dedup_key == dedup_key,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Status updates
    # ------------------------------------------------------------------

    async def update_status(
        self,
        db: AsyncSession,
        work_item_id: uuid.UUID,
        status: str,
        *,
        current_execution_id: uuid.UUID | None = None,
    ) -> WorkItem | None:
        item = await self.get_by_id(db, work_item_id)
        if item is None:
            return None
        item.status = status
        if current_execution_id is not None:
            item.current_execution_id = current_execution_id
        if status == "COMPLETED":
            item.last_completed_at = datetime.utcnow()
            item.execution_count += 1
        elif status == "FAILED":
            item.execution_count += 1
        await db.flush()
        return item

    async def bulk_update_status(
        self,
        db: AsyncSession,
        work_item_ids: list[uuid.UUID],
        status: str,
    ) -> int:
        """Bulk update status for multiple work items. Returns count updated."""
        stmt = (
            update(WorkItem)
            .where(WorkItem.id.in_(work_item_ids))
            .values(status=status)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Executions
    # ------------------------------------------------------------------

    async def create_execution(
        self,
        db: AsyncSession,
        *,
        work_item_id: uuid.UUID,
        trigger_type: str = "INITIAL",
        trigger_source: str | None = None,
        reprocess_request_id: uuid.UUID | None = None,
    ) -> WorkItemExecution:
        """Create a new execution for a work item. Auto-increments execution_no."""
        next_no = await self._next_execution_no(db, work_item_id)
        execution = WorkItemExecution(
            work_item_id=work_item_id,
            execution_no=next_no,
            trigger_type=trigger_type,
            trigger_source=trigger_source,
            reprocess_request_id=reprocess_request_id,
        )
        db.add(execution)
        await db.flush()
        return execution

    async def get_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        *,
        with_steps: bool = False,
    ) -> WorkItemExecution | None:
        stmt = select(WorkItemExecution).where(WorkItemExecution.id == execution_id)
        if with_steps:
            stmt = stmt.options(selectinload(WorkItemExecution.step_executions))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def complete_execution(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        *,
        status: str = "COMPLETED",
        ended_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> WorkItemExecution | None:
        execution = await self.get_execution(db, execution_id)
        if execution is None:
            return None
        execution.status = status
        execution.ended_at = ended_at or datetime.utcnow()
        execution.duration_ms = duration_ms
        await db.flush()
        return execution

    # ------------------------------------------------------------------
    # Step executions
    # ------------------------------------------------------------------

    async def create_step_execution(
        self,
        db: AsyncSession,
        *,
        execution_id: uuid.UUID,
        pipeline_step_id: uuid.UUID,
        step_type: str,
        step_order: int,
    ) -> WorkItemStepExecution:
        step_exec = WorkItemStepExecution(
            execution_id=execution_id,
            pipeline_step_id=pipeline_step_id,
            step_type=step_type,
            step_order=step_order,
        )
        db.add(step_exec)
        await db.flush()
        return step_exec

    async def update_step_execution(
        self,
        db: AsyncSession,
        step_execution_id: uuid.UUID,
        **kwargs: Any,
    ) -> WorkItemStepExecution | None:
        stmt = select(WorkItemStepExecution).where(
            WorkItemStepExecution.id == step_execution_id
        )
        result = await db.execute(stmt)
        step_exec = result.scalar_one_or_none()
        if step_exec is None:
            return None
        for key, value in kwargs.items():
            setattr(step_exec, key, value)
        await db.flush()
        return step_exec

    # ------------------------------------------------------------------
    # Execution snapshots
    # ------------------------------------------------------------------

    async def create_snapshot(
        self,
        db: AsyncSession,
        *,
        execution_id: uuid.UUID,
        pipeline_config: dict[str, Any],
        collector_config: dict[str, Any],
        algorithm_config: dict[str, Any],
        transfer_config: dict[str, Any],
        snapshot_hash: str | None = None,
    ) -> ExecutionSnapshot:
        snapshot = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config=pipeline_config,
            collector_config=collector_config,
            algorithm_config=algorithm_config,
            transfer_config=transfer_config,
            snapshot_hash=snapshot_hash,
        )
        db.add(snapshot)
        await db.flush()
        return snapshot

    # ------------------------------------------------------------------
    # Event logs
    # ------------------------------------------------------------------

    async def add_event_log(
        self,
        db: AsyncSession,
        *,
        execution_id: uuid.UUID,
        event_code: str,
        event_type: str = "INFO",
        step_execution_id: uuid.UUID | None = None,
        message: str | None = None,
        detail_json: dict[str, Any] | None = None,
    ) -> ExecutionEventLog:
        log = ExecutionEventLog(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            event_type=event_type,
            event_code=event_code,
            message=message,
            detail_json=detail_json,
        )
        db.add(log)
        await db.flush()
        return log

    async def get_event_logs(
        self,
        db: AsyncSession,
        execution_id: uuid.UUID,
        *,
        event_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ExecutionEventLog]:
        stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == execution_id
        )
        if event_type is not None:
            stmt = stmt.where(ExecutionEventLog.event_type == event_type)
        stmt = stmt.order_by(ExecutionEventLog.created_at).offset(offset).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Reprocess requests
    # ------------------------------------------------------------------

    async def create_reprocess_request(
        self,
        db: AsyncSession,
        *,
        work_item_id: uuid.UUID,
        requested_by: str,
        reason: str | None = None,
        start_from_step: int | None = None,
        use_latest_recipe: bool = True,
    ) -> ReprocessRequest:
        req = ReprocessRequest(
            work_item_id=work_item_id,
            requested_by=requested_by,
            reason=reason,
            start_from_step=start_from_step,
            use_latest_recipe=use_latest_recipe,
        )
        db.add(req)
        await db.flush()
        return req

    async def bulk_create_reprocess_requests(
        self,
        db: AsyncSession,
        *,
        work_item_ids: list[uuid.UUID],
        requested_by: str,
        reason: str | None = None,
        start_from_step: int | None = None,
        use_latest_recipe: bool = True,
    ) -> list[ReprocessRequest]:
        """Create reprocess requests for multiple work items."""
        requests: list[ReprocessRequest] = []
        for wid in work_item_ids:
            req = ReprocessRequest(
                work_item_id=wid,
                requested_by=requested_by,
                reason=reason,
                start_from_step=start_from_step,
                use_latest_recipe=use_latest_recipe,
            )
            db.add(req)
            requests.append(req)
        await db.flush()
        return requests

    async def get_reprocess_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ) -> ReprocessRequest | None:
        stmt = select(ReprocessRequest).where(ReprocessRequest.id == request_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def approve_reprocess_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        approved_by: str,
    ) -> ReprocessRequest | None:
        req = await self.get_reprocess_request(db, request_id)
        if req is None:
            return None
        req.status = "APPROVED"
        req.approved_by = approved_by
        await db.flush()
        return req

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _next_execution_no(self, db: AsyncSession, work_item_id: uuid.UUID) -> int:
        stmt = select(
            func.coalesce(func.max(WorkItemExecution.execution_no), 0)
        ).where(WorkItemExecution.work_item_id == work_item_id)
        result = await db.execute(stmt)
        return result.scalar_one() + 1
