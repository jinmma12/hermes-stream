"""Processing orchestrator - per-WorkItem execution following ARCHITECTURE.md 11.2."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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
from vessel.domain.models.pipeline import PipelineInstance, PipelineStep
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from vessel.domain.services.snapshot_resolver import SnapshotResolver

logger = logging.getLogger(__name__)


class ProcessingOrchestrator:
    """Orchestrates the processing of individual work items through pipeline steps.

    Follows the pseudocode in ARCHITECTURE.md section 11.2.
    """

    def __init__(
        self,
        db: AsyncSession,
        dispatcher: ExecutionDispatcher | None = None,
        snapshot_resolver: SnapshotResolver | None = None,
    ) -> None:
        self.db = db
        self.dispatcher = dispatcher or ExecutionDispatcher()
        self.snapshot_resolver = snapshot_resolver or SnapshotResolver(db)

    async def process_work_item(
        self,
        work_item_id: uuid.UUID,
        trigger_type: str = "INITIAL",
        trigger_source: str = "SYSTEM",
        start_from_step: int = 1,
        use_latest_recipe: bool = True,
        reprocess_request_id: uuid.UUID | None = None,
    ) -> WorkItemExecution:
        """Process a work item through the pipeline steps.

        Follows ARCHITECTURE.md section 11.2 pseudocode exactly:
        1. Create WorkItemExecution
        2. Capture ExecutionSnapshot
        3. Execute steps in order
        4. Record results per step
        5. Handle errors based on on_error setting (STOP/SKIP/RETRY)
        """
        # Load work item and pipeline
        work_item = await self.db.get(WorkItem, work_item_id)
        if work_item is None:
            raise ValueError(f"WorkItem {work_item_id} not found")

        stmt = (
            select(PipelineInstance)
            .options(selectinload(PipelineInstance.steps))
            .where(PipelineInstance.id == work_item.pipeline_instance_id)
        )
        result = await self.db.execute(stmt)
        pipeline = result.scalar_one_or_none()
        if pipeline is None:
            raise ValueError(
                f"Pipeline {work_item.pipeline_instance_id} not found for work item {work_item_id}"
            )

        steps = sorted(pipeline.steps, key=lambda s: s.step_order)

        # 1. Create execution record
        execution_no = work_item.execution_count + 1
        now = datetime.now(timezone.utc)

        execution = WorkItemExecution(
            work_item_id=work_item.id,
            execution_no=execution_no,
            trigger_type=trigger_type,
            trigger_source=trigger_source,
            status="RUNNING",
            started_at=now,
            reprocess_request_id=reprocess_request_id,
        )
        self.db.add(execution)
        await self.db.flush()

        # Update work item
        work_item.status = "PROCESSING"
        work_item.current_execution_id = execution.id
        work_item.execution_count = execution_no
        await self.db.flush()

        # Log start event
        await self._log_event(
            execution.id,
            None,
            "INFO",
            "EXECUTION_START",
            f"Starting execution #{execution_no} ({trigger_type})",
        )

        # 2. Snapshot current configuration
        snapshot = await self.snapshot_resolver.capture(
            pipeline, steps, execution.id, use_latest_recipe
        )

        # Resolve snapshot for step configs
        resolved = await self.snapshot_resolver.resolve(snapshot.id)

        # 3. Execute steps in order
        previous_output: Any = None
        execution_failed = False

        for step in steps:
            if step.step_order < start_from_step:
                # Skip earlier steps (use cached output if available)
                step_config = resolved.get_config_for_step(step)
                if step_config:
                    previous_output = step_config.resolved_config
                continue

            if not step.is_enabled:
                continue

            step_start = datetime.now(timezone.utc)

            step_execution = WorkItemStepExecution(
                execution_id=execution.id,
                pipeline_step_id=step.id,
                step_type=step.step_type,
                step_order=step.step_order,
                status="RUNNING",
                started_at=step_start,
            )
            self.db.add(step_execution)
            await self.db.flush()

            await self._log_event(
                execution.id,
                step_execution.id,
                "INFO",
                f"{step.step_type}_START",
                f"Starting {step.step_type} step (order={step.step_order})",
            )

            # Find step config from snapshot
            step_config = resolved.get_config_for_step(step)
            exec_type = step_config.execution_type if step_config else "PLUGIN"
            exec_ref = step_config.execution_ref if step_config else None
            resolved_config = step_config.resolved_config if step_config else {}

            try:
                # 4. Dispatch to appropriate executor
                dispatch_result = await self.dispatcher.dispatch(
                    execution_type=exec_type,
                    execution_ref=exec_ref,
                    config=resolved_config,
                    input_data=previous_output,
                    context={
                        "work_item_id": str(work_item.id),
                        "step_type": step.step_type,
                        "execution_id": str(execution.id),
                    },
                )

                step_end = datetime.now(timezone.utc)
                step_execution.ended_at = step_end
                step_execution.duration_ms = int(
                    (step_end - step_start).total_seconds() * 1000
                )

                if dispatch_result.success:
                    step_execution.status = "COMPLETED"
                    step_execution.output_summary = dispatch_result.summary
                    previous_output = dispatch_result.output

                    await self._log_event(
                        execution.id,
                        step_execution.id,
                        "INFO",
                        f"{step.step_type}_DONE",
                        f"{step.step_type} completed in {dispatch_result.duration_ms}ms",
                        detail=dispatch_result.summary,
                    )
                else:
                    raise RuntimeError(
                        dispatch_result.logs[-1]["message"]
                        if dispatch_result.logs
                        else "Step execution failed"
                    )

            except Exception as exc:
                step_end = datetime.now(timezone.utc)
                step_execution.status = "FAILED"
                step_execution.error_message = str(exc)
                step_execution.error_code = type(exc).__name__
                step_execution.ended_at = step_end
                step_execution.duration_ms = int(
                    (step_end - step_start).total_seconds() * 1000
                )

                await self._log_event(
                    execution.id,
                    step_execution.id,
                    "ERROR",
                    f"{step.step_type}_ERROR",
                    str(exc),
                )

                # 5. Handle errors based on on_error setting
                if step.on_error == "STOP":
                    execution_failed = True
                    break
                elif step.on_error == "SKIP":
                    await self._log_event(
                        execution.id,
                        step_execution.id,
                        "WARN",
                        f"{step.step_type}_SKIPPED",
                        f"Skipping failed step (on_error=SKIP)",
                    )
                    continue
                elif step.on_error == "RETRY":
                    retried = await self._retry_step(
                        step, step_execution, execution, resolved_config,
                        exec_type, exec_ref, previous_output, work_item,
                    )
                    if retried:
                        previous_output = step_execution.output_summary
                    else:
                        execution_failed = True
                        break

            finally:
                await self.db.flush()

        # 5. Update final status
        end_time = datetime.now(timezone.utc)
        if execution_failed:
            execution.status = "FAILED"
        else:
            execution.status = "COMPLETED"

        execution.ended_at = end_time
        execution.duration_ms = int(
            (end_time - execution.started_at).total_seconds() * 1000
        )

        work_item.status = execution.status
        if execution.status == "COMPLETED":
            work_item.last_completed_at = end_time

        await self._log_event(
            execution.id,
            None,
            "INFO",
            "EXECUTION_END",
            f"Execution #{execution_no} {execution.status} in {execution.duration_ms}ms",
        )

        await self.db.flush()
        logger.info(
            "Work item %s execution #%d: %s (%dms)",
            work_item_id,
            execution_no,
            execution.status,
            execution.duration_ms,
        )
        return execution

    async def _retry_step(
        self,
        step: PipelineStep,
        step_execution: WorkItemStepExecution,
        execution: WorkItemExecution,
        config: dict[str, Any],
        exec_type: str,
        exec_ref: str | None,
        previous_output: Any,
        work_item: WorkItem,
    ) -> bool:
        """Retry a failed step with exponential backoff."""
        max_retries = step.retry_count or 1
        delay = step.retry_delay_seconds or 5

        for attempt in range(1, max_retries + 1):
            await self._log_event(
                execution.id,
                step_execution.id,
                "WARN",
                f"{step.step_type}_RETRY",
                f"Retrying step, attempt {attempt}/{max_retries}",
            )

            await asyncio.sleep(delay * attempt)  # exponential backoff

            try:
                dispatch_result = await self.dispatcher.dispatch(
                    execution_type=exec_type,
                    execution_ref=exec_ref,
                    config=config,
                    input_data=previous_output,
                    context={
                        "work_item_id": str(work_item.id),
                        "step_type": step.step_type,
                        "execution_id": str(execution.id),
                    },
                )

                if dispatch_result.success:
                    step_execution.status = "COMPLETED"
                    step_execution.output_summary = dispatch_result.summary
                    step_execution.retry_attempt = attempt
                    step_execution.error_message = None
                    step_execution.error_code = None
                    return True

            except Exception as exc:
                logger.warning(
                    "Retry %d/%d failed for step %s: %s",
                    attempt,
                    max_retries,
                    step.id,
                    exc,
                )

        return False

    async def reprocess_work_item(
        self, reprocess_request_id: uuid.UUID
    ) -> WorkItemExecution:
        """Reprocess a work item based on a ReprocessRequest."""
        request = await self.db.get(ReprocessRequest, reprocess_request_id)
        if request is None:
            raise ValueError(f"ReprocessRequest {reprocess_request_id} not found")

        request.status = "EXECUTING"
        await self.db.flush()

        try:
            execution = await self.process_work_item(
                work_item_id=request.work_item_id,
                trigger_type="REPROCESS",
                trigger_source=request.requested_by,
                start_from_step=request.start_from_step or 1,
                use_latest_recipe=request.use_latest_recipe,
                reprocess_request_id=reprocess_request_id,
            )

            request.status = "DONE"
            request.execution_id = execution.id
            await self.db.flush()
            return execution

        except Exception:
            request.status = "PENDING"  # Allow retry
            await self.db.flush()
            raise

    async def bulk_reprocess(
        self,
        work_item_ids: list[uuid.UUID],
        reason: str,
        requested_by: str,
        start_from_step: int | None = None,
        use_latest_recipe: bool = True,
    ) -> list[ReprocessRequest]:
        """Create reprocess requests for multiple work items."""
        requests: list[ReprocessRequest] = []
        for wid in work_item_ids:
            rr = ReprocessRequest(
                work_item_id=wid,
                requested_by=requested_by,
                reason=reason,
                start_from_step=start_from_step,
                use_latest_recipe=use_latest_recipe,
                status="PENDING",
            )
            self.db.add(rr)
            requests.append(rr)

        await self.db.flush()
        logger.info(
            "Created %d reprocess requests for work items by %s",
            len(requests),
            requested_by,
        )
        return requests

    async def _log_event(
        self,
        execution_id: uuid.UUID,
        step_execution_id: uuid.UUID | None,
        event_type: str,
        event_code: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Append an event to the execution event log."""
        log = ExecutionEventLog(
            execution_id=execution_id,
            step_execution_id=step_execution_id,
            event_type=event_type,
            event_code=event_code,
            message=message,
            detail_json=detail or {},
        )
        self.db.add(log)
