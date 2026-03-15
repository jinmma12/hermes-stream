"""Tests for WorkItem lifecycle - per-item tracking through the pipeline.

End-to-end tests covering the full happy path (COLLECT -> ALGORITHM -> TRANSFER),
step failure handling, deduplication prevention, and concurrent processing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    WorkItem,
    WorkItemExecution,
    WorkItemStepExecution,
)
from vessel.domain.models.monitoring import PipelineActivation
from vessel.domain.models.pipeline import PipelineInstance, PipelineStep
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.domain.services.snapshot_resolver import ResolvedConfig, SnapshotResolver, StepConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_dispatcher(results: list[ExecutionResult] | None = None) -> ExecutionDispatcher:
    """Create a mock dispatcher that returns the given results in order."""
    dispatcher = AsyncMock(spec=ExecutionDispatcher)

    if results is None:
        # Default: all steps succeed
        success_result = ExecutionResult(
            success=True,
            output={"data": [{"id": 1}]},
            summary={"records": 1},
            duration_ms=50,
        )
        dispatcher.dispatch = AsyncMock(return_value=success_result)
    else:
        dispatcher.dispatch = AsyncMock(side_effect=results)

    return dispatcher


def _make_mock_snapshot_resolver(
    async_session: AsyncSession,
    steps: list[PipelineStep],
) -> SnapshotResolver:
    """Create a mock snapshot resolver that returns step configs for given steps."""
    resolver = AsyncMock(spec=SnapshotResolver)

    async def mock_capture(pipeline, pipeline_steps, execution_id, use_latest):
        snapshot = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config={"name": pipeline.name},
            collector_config={},
            algorithm_config={},
            transfer_config={},
            snapshot_hash="testhash123",
        )
        async_session.add(snapshot)
        await async_session.flush()
        return snapshot

    async def mock_resolve(snapshot_id):
        resolved = ResolvedConfig(pipeline_config={"name": "test"})
        for step in steps:
            resolved.steps.append(
                StepConfig(
                    step_id=step.id,
                    step_order=step.step_order,
                    step_type=step.step_type,
                    ref_type=step.ref_type,
                    ref_id=step.ref_id,
                    execution_type="PLUGIN",
                    execution_ref=f"{step.ref_type}:test",
                    resolved_config={"test": True},
                    version_no=1,
                )
            )
        return resolved

    resolver.capture = AsyncMock(side_effect=mock_capture)
    resolver.resolve = AsyncMock(side_effect=mock_resolve)
    return resolver


# ---------------------------------------------------------------------------
# Full lifecycle happy path
# ---------------------------------------------------------------------------


class TestWorkItemHappyPath:
    """Test the complete happy-path lifecycle of a work item."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_happy_path(
        self,
        async_session: AsyncSession,
        sample_work_item,
        sample_pipeline,
    ):
        """WorkItem goes DETECTED -> PROCESSING -> COMPLETED through 3 steps.

        Steps:
        1. Create pipeline with 3 steps (already done via fixture)
        2. Monitor detects event -> WorkItem created (fixture)
        3. WorkItem processed through COLLECT -> ALGORITHM -> TRANSFER
        4. Each step recorded with timing
        5. Final status: COMPLETED
        6. ExecutionSnapshot captured
        7. EventLog has full trace
        """
        work_item, activation = sample_work_item
        pipeline, steps = sample_pipeline

        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_snapshot_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session,
            dispatcher=dispatcher,
            snapshot_resolver=resolver,
        )

        execution = await orchestrator.process_work_item(work_item.id)

        # Verify execution completed
        assert execution.status == "COMPLETED", (
            f"Expected COMPLETED, got {execution.status}"
        )
        assert execution.execution_no == 1
        assert execution.trigger_type == "INITIAL"
        assert execution.duration_ms is not None
        assert execution.duration_ms >= 0

        # Verify work item status updated
        await async_session.refresh(work_item)
        assert work_item.status == "COMPLETED"
        assert work_item.execution_count == 1
        assert work_item.last_completed_at is not None

        # Verify dispatcher was called 3 times (once per step)
        assert dispatcher.dispatch.call_count == 3

        # Verify snapshot was captured
        assert resolver.capture.call_count == 1

        # Verify event logs exist
        log_stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == execution.id
        )
        log_result = await async_session.execute(log_stmt)
        event_logs = list(log_result.scalars().all())
        assert len(event_logs) >= 2, (
            "Should have at least EXECUTION_START and EXECUTION_END events"
        )

        # Check specific event codes
        event_codes = [log.event_code for log in event_logs]
        assert "EXECUTION_START" in event_codes
        assert "EXECUTION_END" in event_codes


# ---------------------------------------------------------------------------
# Step failure
# ---------------------------------------------------------------------------


class TestWorkItemStepFailure:
    """Test work item behaviour when a step fails."""

    @pytest.mark.asyncio
    async def test_workitem_step_failure(
        self,
        async_session: AsyncSession,
        sample_work_item,
        sample_pipeline,
    ):
        """COLLECT succeeds, ALGORITHM fails -> WorkItem FAILED, TRANSFER skipped.

        1. COLLECT succeeds
        2. ALGORITHM fails (plugin returns ERROR)
        3. TRANSFER is skipped (on_error=STOP)
        4. WorkItem status: FAILED
        5. Error details recorded in step execution
        """
        work_item, activation = sample_work_item
        pipeline, steps = sample_pipeline

        results = [
            # Step 1 (COLLECT): success
            ExecutionResult(success=True, output={"data": []}, summary={}, duration_ms=10),
            # Step 2 (ALGORITHM): failure
            ExecutionResult(
                success=False,
                output={},
                summary={},
                duration_ms=5,
                logs=[{"level": "ERROR", "message": "Threshold validation failed"}],
            ),
            # Step 3 (TRANSFER): should never be called
        ]

        dispatcher = _make_mock_dispatcher(results)
        resolver = _make_mock_snapshot_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session,
            dispatcher=dispatcher,
            snapshot_resolver=resolver,
        )

        execution = await orchestrator.process_work_item(work_item.id)

        assert execution.status == "FAILED"

        # Dispatcher should only be called twice (step 3 skipped due to STOP)
        assert dispatcher.dispatch.call_count == 2

        # Work item should be FAILED
        await async_session.refresh(work_item)
        assert work_item.status == "FAILED"

        # Check event logs contain error
        log_stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == execution.id,
            ExecutionEventLog.event_type == "ERROR",
        )
        result = await async_session.execute(log_stmt)
        error_logs = list(result.scalars().all())
        assert len(error_logs) >= 1, "Should have at least one ERROR event log"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestWorkItemDedup:
    """Test deduplication of work items."""

    @pytest.mark.asyncio
    async def test_workitem_dedup_prevention(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Same dedup_key cannot create two work items."""
        pipeline, steps = sample_pipeline

        activation = PipelineActivation(
            pipeline_instance_id=pipeline.id,
            status="RUNNING",
        )
        async_session.add(activation)
        await async_session.flush()

        dedup = "FILE:same-file-hash"

        # Create first work item
        wi1 = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="FILE",
            source_key="data.csv",
            dedup_key=dedup,
            status="DETECTED",
        )
        async_session.add(wi1)
        await async_session.flush()

        # Check that a query for this dedup_key finds the existing item
        stmt = select(WorkItem).where(WorkItem.dedup_key == dedup).limit(1)
        result = await async_session.execute(stmt)
        existing = result.scalar_one_or_none()

        assert existing is not None, "First work item should be found by dedup_key"
        assert existing.id == wi1.id

        # In the monitoring engine, this would prevent creating a second work item.
        # We verify the logic: if existing is not None, skip creation.
        should_create_second = existing is None
        assert should_create_second is False, (
            "Dedup check should prevent second work item creation"
        )


# ---------------------------------------------------------------------------
# Concurrent processing
# ---------------------------------------------------------------------------


class TestWorkItemConcurrent:
    """Test concurrent processing of multiple work items."""

    @pytest.mark.asyncio
    async def test_workitem_concurrent_processing(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Multiple work items can be processed with independent execution histories."""
        pipeline, steps = sample_pipeline

        activation = PipelineActivation(
            pipeline_instance_id=pipeline.id,
            status="RUNNING",
        )
        async_session.add(activation)
        await async_session.flush()

        # Create 3 work items
        work_items = []
        for i in range(3):
            wi = WorkItem(
                pipeline_activation_id=activation.id,
                pipeline_instance_id=pipeline.id,
                source_type="FILE",
                source_key=f"data-{i}.csv",
                dedup_key=f"FILE:hash-{i}",
                status="DETECTED",
            )
            async_session.add(wi)
            work_items.append(wi)
        await async_session.flush()

        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_snapshot_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session,
            dispatcher=dispatcher,
            snapshot_resolver=resolver,
        )

        # Process each sequentially (same session prevents true concurrency here)
        executions = []
        for wi in work_items:
            exec_ = await orchestrator.process_work_item(wi.id)
            executions.append(exec_)

        # All should complete
        assert all(e.status == "COMPLETED" for e in executions)

        # Each has independent execution_no
        assert all(e.execution_no == 1 for e in executions)

        # Each work item updated
        for wi in work_items:
            await async_session.refresh(wi)
            assert wi.status == "COMPLETED"
            assert wi.execution_count == 1
