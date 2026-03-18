"""Tests for Reprocessing - Vessel's killer feature.

Covers reprocessing with same recipe, updated recipe, from a specific step,
bulk reprocessing, audit trails, and reprocessing already-completed items.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    ReprocessRequest,
    WorkItem,
    WorkItemExecution,
)
from vessel.domain.models.monitoring import PipelineActivation
from vessel.domain.models.pipeline import PipelineInstance, PipelineStep
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.domain.services.recipe_engine import RecipeEngine
from vessel.domain.services.snapshot_resolver import ResolvedConfig, SnapshotResolver, StepConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_dispatcher(results: list[ExecutionResult] | None = None) -> ExecutionDispatcher:
    """Create a mock dispatcher returning sequential results."""
    dispatcher = AsyncMock(spec=ExecutionDispatcher)
    if results is None:
        ok = ExecutionResult(success=True, output={"data": []}, summary={}, duration_ms=10)
        dispatcher.dispatch = AsyncMock(return_value=ok)
    else:
        dispatcher.dispatch = AsyncMock(side_effect=results)
    return dispatcher


def _make_mock_resolver(
    async_session: AsyncSession,
    steps: list[PipelineStep],
) -> SnapshotResolver:
    """Create a mock snapshot resolver."""
    resolver = AsyncMock(spec=SnapshotResolver)

    async def mock_capture(pipeline, pipeline_steps, execution_id, use_latest):
        snapshot = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config={"name": pipeline.name},
            collector_config={},
            algorithm_config={},
            transfer_config={},
            snapshot_hash="hash-" + str(execution_id)[:8],
        )
        async_session.add(snapshot)
        await async_session.flush()
        return snapshot

    async def mock_resolve(snapshot_id):
        resolved = ResolvedConfig(pipeline_config={})
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


async def _create_failed_work_item(
    async_session: AsyncSession,
    pipeline: PipelineInstance,
    steps: list[PipelineStep],
    source_key: str = "failed-data.csv",
) -> tuple[WorkItem, WorkItemExecution]:
    """Create a work item and execute it through to FAILED status."""
    activation = PipelineActivation(
        pipeline_instance_id=pipeline.id,
        status="RUNNING",
    )
    async_session.add(activation)
    await async_session.flush()

    work_item = WorkItem(
        pipeline_activation_id=activation.id,
        pipeline_instance_id=pipeline.id,
        source_type="FILE",
        source_key=source_key,
        dedup_key=f"FILE:{source_key}",
        status="DETECTED",
    )
    async_session.add(work_item)
    await async_session.flush()

    # Run the work item with ALGORITHM step failing
    fail_results = [
        ExecutionResult(success=True, output={"data": []}, summary={}, duration_ms=10),
        ExecutionResult(
            success=False, output={}, summary={}, duration_ms=5,
            logs=[{"level": "ERROR", "message": "Algorithm failed"}],
        ),
    ]
    dispatcher = _make_mock_dispatcher(fail_results)
    resolver = _make_mock_resolver(async_session, steps)

    orchestrator = ProcessingOrchestrator(
        db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
    )
    execution = await orchestrator.process_work_item(work_item.id)
    assert execution.status == "FAILED"

    await async_session.refresh(work_item)
    return work_item, execution


# ---------------------------------------------------------------------------
# Reprocess with same recipe
# ---------------------------------------------------------------------------


class TestReprocessSameRecipe:
    """Reprocessing a failed item with the same (original) recipe."""

    @pytest.mark.asyncio
    async def test_reprocess_failed_item_with_same_recipe(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Failed item -> ReprocessRequest -> new execution (REPROCESS trigger).

        1. WorkItem fails at ALGORITHM step
        2. ReprocessRequest created
        3. New WorkItemExecution with trigger_type=REPROCESS
        4. Full re-run from step 1
        5. Uses same recipe
        """
        pipeline, steps = sample_pipeline
        work_item, failed_exec = await _create_failed_work_item(
            async_session, pipeline, steps
        )

        # Create reprocess request
        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="operator-test",
            reason="Retry after fixing upstream data",
            use_latest_recipe=False,  # same recipe
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        # Now reprocess (all steps succeed this time)
        dispatcher = _make_mock_dispatcher()  # all succeed
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        new_exec = await orchestrator.reprocess_work_item(rr.id)

        assert new_exec.status == "COMPLETED"
        assert new_exec.trigger_type == "REPROCESS"
        assert new_exec.execution_no == 2, "Should be execution #2"
        assert new_exec.reprocess_request_id == rr.id

        # Verify request status updated
        await async_session.refresh(rr)
        assert rr.status == "DONE"
        assert rr.execution_id == new_exec.id

        # Work item should be COMPLETED now
        await async_session.refresh(work_item)
        assert work_item.status == "COMPLETED"
        assert work_item.execution_count == 2


# ---------------------------------------------------------------------------
# Reprocess with updated recipe
# ---------------------------------------------------------------------------


class TestReprocessUpdatedRecipe:
    """Reprocessing with use_latest_recipe=True after recipe change."""

    @pytest.mark.asyncio
    async def test_reprocess_with_updated_recipe(
        self,
        async_session: AsyncSession,
        sample_pipeline,
        sample_algorithm_instance,
    ):
        """Failed item -> update recipe -> reprocess with latest -> succeeds.

        1. WorkItem fails (threshold too aggressive)
        2. User updates recipe (threshold 2.5 -> 3.0)
        3. ReprocessRequest with use_latest_recipe=True
        4. New execution uses new recipe
        5. Both snapshots preserved
        """
        pipeline, steps = sample_pipeline
        algo_inst, algo_ver = sample_algorithm_instance

        work_item, failed_exec = await _create_failed_work_item(
            async_session, pipeline, steps
        )

        # Update algorithm recipe
        engine = RecipeEngine(async_session)
        new_recipe = await engine.create_recipe(
            instance_type="ALGORITHM",
            instance_id=algo_inst.id,
            config_json={"threshold": 3.0, "field_name": "value"},
            change_note="Relaxed threshold for better results",
        )
        await engine.publish_recipe("ALGORITHM", algo_inst.id, new_recipe.version_no)

        # Create reprocess request with use_latest_recipe=True
        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="operator-test",
            reason="Retry with relaxed threshold",
            use_latest_recipe=True,
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        # Reprocess
        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        new_exec = await orchestrator.reprocess_work_item(rr.id)

        assert new_exec.status == "COMPLETED"

        # Verify the capture was called with use_latest_recipe=True
        resolver.capture.assert_called_once()
        call_args = resolver.capture.call_args
        assert call_args[0][3] is True, "use_latest_recipe should be True"

        # Both executions exist
        exec_stmt = select(WorkItemExecution).where(
            WorkItemExecution.work_item_id == work_item.id
        )
        result = await async_session.execute(exec_stmt)
        all_execs = list(result.scalars().all())
        assert len(all_execs) == 2, "Should have 2 executions (original + reprocess)"

        # Both snapshots exist
        snap_stmt = select(ExecutionSnapshot).where(
            ExecutionSnapshot.execution_id.in_([e.id for e in all_execs])
        )
        snap_result = await async_session.execute(snap_stmt)
        snapshots = list(snap_result.scalars().all())
        assert len(snapshots) == 2, "Both executions should have snapshots"

        # Snapshots should have different hashes (different config)
        hashes = [s.snapshot_hash for s in snapshots]
        assert hashes[0] != hashes[1], (
            "Different configs should produce different snapshot hashes"
        )


# ---------------------------------------------------------------------------
# Reprocess from specific step
# ---------------------------------------------------------------------------


class TestReprocessFromStep:
    """Reprocessing starting from a specific step."""

    @pytest.mark.asyncio
    async def test_reprocess_from_specific_step(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Reprocess starting from step 2, skipping COLLECT.

        1. WorkItem: COLLECT ok, ALGORITHM failed
        2. ReprocessRequest with start_from_step=2
        3. New execution skips COLLECT, starts at ALGORITHM
        """
        pipeline, steps = sample_pipeline
        work_item, failed_exec = await _create_failed_work_item(
            async_session, pipeline, steps
        )

        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="operator-test",
            reason="Skip collect, retry algorithm only",
            start_from_step=2,
            use_latest_recipe=True,
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        new_exec = await orchestrator.reprocess_work_item(rr.id)

        assert new_exec.status == "COMPLETED"

        # Dispatcher should only be called for steps 2 and 3 (skipping step 1)
        assert dispatcher.dispatch.call_count == 2, (
            "Should only dispatch steps 2 and 3 when starting from step 2"
        )


# ---------------------------------------------------------------------------
# Bulk reprocess
# ---------------------------------------------------------------------------


class TestBulkReprocess:
    """Bulk reprocessing of multiple work items."""

    @pytest.mark.asyncio
    async def test_bulk_reprocess(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Create reprocess requests for 5 failed work items at once.

        1. 5 WorkItems failed
        2. bulk_reprocess creates 5 ReprocessRequests
        3. Each can be individually processed
        """
        pipeline, steps = sample_pipeline

        # Create 5 failed work items
        work_items = []
        for i in range(5):
            wi, _ = await _create_failed_work_item(
                async_session, pipeline, steps, source_key=f"bulk-{i}.csv"
            )
            work_items.append(wi)

        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )

        # Bulk create reprocess requests
        requests = await orchestrator.bulk_reprocess(
            work_item_ids=[wi.id for wi in work_items],
            reason="Bulk retry after config fix",
            requested_by="admin",
            use_latest_recipe=True,
        )

        assert len(requests) == 5, "Should create 5 reprocess requests"
        assert all(r.status == "PENDING" for r in requests)
        assert all(r.requested_by == "admin" for r in requests)
        assert all(r.reason == "Bulk retry after config fix" for r in requests)

        # Process each one
        for rr in requests:
            execution = await orchestrator.reprocess_work_item(rr.id)
            assert execution.status == "COMPLETED"

        # Verify all work items now COMPLETED
        for wi in work_items:
            await async_session.refresh(wi)
            assert wi.status == "COMPLETED"


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestReprocessAuditTrail:
    """Reprocess requests maintain a full audit trail."""

    @pytest.mark.asyncio
    async def test_reprocess_creates_audit_trail(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Reprocess request -> execution -> steps forms a traceable chain.

        1. Reprocess request has reason, requested_by
        2. Linked to resulting execution via execution_id
        3. Full trace: request -> execution -> step executions -> event logs
        """
        pipeline, steps = sample_pipeline
        work_item, _ = await _create_failed_work_item(
            async_session, pipeline, steps
        )

        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="operator-alice",
            reason="Data quality issue resolved upstream",
            use_latest_recipe=True,
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        new_exec = await orchestrator.reprocess_work_item(rr.id)

        # Verify audit chain
        await async_session.refresh(rr)
        assert rr.requested_by == "operator-alice"
        assert rr.reason == "Data quality issue resolved upstream"
        assert rr.status == "DONE"
        assert rr.execution_id == new_exec.id

        # Execution is linked back to reprocess request
        assert new_exec.reprocess_request_id == rr.id
        assert new_exec.trigger_type == "REPROCESS"
        assert new_exec.trigger_source == "operator-alice"

        # Event logs exist
        log_stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == new_exec.id
        )
        result = await async_session.execute(log_stmt)
        logs = list(result.scalars().all())
        assert len(logs) >= 2, "Should have execution start/end event logs"


# ---------------------------------------------------------------------------
# Reprocess already completed item
# ---------------------------------------------------------------------------


class TestReprocessCompleted:
    """Reprocessing an already-completed work item (re-analysis)."""

    @pytest.mark.asyncio
    async def test_reprocess_already_completed_item(
        self,
        async_session: AsyncSession,
        sample_work_item,
        sample_pipeline,
    ):
        """Completed WorkItem can be reprocessed for re-analysis.

        1. WorkItem COMPLETED
        2. ReprocessRequest still works
        3. Original execution preserved alongside new one
        """
        work_item, activation = sample_work_item
        pipeline, steps = sample_pipeline

        # First run: succeed
        dispatcher = _make_mock_dispatcher()
        resolver = _make_mock_resolver(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        first_exec = await orchestrator.process_work_item(work_item.id)
        assert first_exec.status == "COMPLETED"

        # Create reprocess request on the completed item
        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="analyst",
            reason="Re-analysis with updated algorithm",
            use_latest_recipe=True,
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        # Reprocess
        dispatcher2 = _make_mock_dispatcher()
        resolver2 = _make_mock_resolver(async_session, steps)
        orchestrator2 = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher2, snapshot_resolver=resolver2,
        )
        second_exec = await orchestrator2.reprocess_work_item(rr.id)

        assert second_exec.status == "COMPLETED"
        assert second_exec.execution_no == 2

        # Both executions exist
        exec_stmt = select(WorkItemExecution).where(
            WorkItemExecution.work_item_id == work_item.id
        )
        result = await async_session.execute(exec_stmt)
        all_execs = list(result.scalars().all())
        assert len(all_execs) == 2, "Both original and reprocess executions preserved"
