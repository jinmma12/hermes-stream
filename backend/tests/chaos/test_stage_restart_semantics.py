"""Restart/failover chaos tests for stage lifecycle.

These tests validate behavior when activations restart, stages are
re-initialized, and backlog must be preserved or recalculated.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.execution import (
    WorkItem,
    WorkItemExecution,
    WorkItemStepExecution,
)
from hermes.domain.services.pipeline_manager import PipelineManager
from hermes.domain.services.stage_lifecycle import StageLifecycleManager

TIMEOUT = 10


@pytest.mark.asyncio
async def test_stage_stop_state_lost_on_new_activation(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Stage stop state from old activation does NOT carry to new activation.

    Current design: each activation gets fresh runtime states.
    Operator must re-stop stages after reactivation if needed.
    """
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)

        # Activate and stop a stage
        act1 = await mgr.activate_pipeline(pipeline.id)
        lifecycle = StageLifecycleManager(db=async_session)
        await lifecycle.stop_stage(act1.id, steps[1].id)
        state1 = await lifecycle.get_stage_runtime(act1.id, steps[1].id)
        assert state1.runtime_status == "STOPPED"

        # Deactivate and reactivate
        await mgr.deactivate_pipeline(pipeline.id)
        act2 = await mgr.activate_pipeline(pipeline.id)

        # New activation should have RUNNING states (stop not inherited)
        state2 = await lifecycle.get_stage_runtime(act2.id, steps[1].id)
        assert state2 is not None
        assert state2.runtime_status == "RUNNING", (
            "Stage stop must not persist across activation boundaries"
        )
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_backlog_from_old_activation_not_visible_in_new(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Queue summary for a new activation should start at zero."""
    async def _run():
        pipeline, steps = sample_pipeline
        sorted_steps = sorted(steps, key=lambda s: s.step_order)
        sorted_steps[0]

        mgr = PipelineManager(db=async_session)
        act1 = await mgr.activate_pipeline(pipeline.id)

        # Create work items in first activation
        for i in range(3):
            wi = WorkItem(
                pipeline_activation_id=act1.id,
                pipeline_instance_id=pipeline.id,
                source_type="FILE",
                source_key=f"old-{i}.csv",
                dedup_key=f"FILE:old-{i}",
                status="DETECTED",
            )
            async_session.add(wi)
        await async_session.flush()

        # Deactivate and reactivate
        await mgr.deactivate_pipeline(pipeline.id)
        act2 = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)
        summaries = await lifecycle.get_queue_summary(act2.id)

        for s in summaries:
            assert s.queued_count == 0, (
                f"New activation should start with empty queues, "
                f"stage {s.stage_order} has {s.queued_count}"
            )
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_backlog_survives_within_same_activation(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Within the same activation, queued items must survive stop/resume."""
    async def _run():
        pipeline, steps = sample_pipeline
        sorted_steps = sorted(steps, key=lambda s: s.step_order)
        collect_step, process_step = sorted_steps[0], sorted_steps[1]

        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)
        lifecycle = StageLifecycleManager(db=async_session)

        # Stop process stage
        await lifecycle.stop_stage(activation.id, process_step.id)

        # Create work items and complete collect
        for i in range(3):
            wi = WorkItem(
                pipeline_activation_id=activation.id,
                pipeline_instance_id=pipeline.id,
                source_type="FILE",
                source_key=f"survive-{i}.csv",
                dedup_key=f"FILE:survive-{i}",
                status="DETECTED",
            )
            async_session.add(wi)
            await async_session.flush()

            exec_rec = WorkItemExecution(
                work_item_id=wi.id, execution_no=1,
                trigger_type="INITIAL", status="RUNNING",
            )
            async_session.add(exec_rec)
            await async_session.flush()
            wi.execution_count = 1

            step_exec = WorkItemStepExecution(
                execution_id=exec_rec.id,
                pipeline_step_id=collect_step.id,
                step_type=collect_step.step_type,
                step_order=collect_step.step_order,
                status="COMPLETED",
            )
            async_session.add(step_exec)
        await async_session.flush()

        # Verify backlog exists
        summaries = await lifecycle.get_queue_summary(activation.id)
        proc_summary = next(s for s in summaries if s.stage_order == process_step.step_order)
        assert proc_summary.queued_count >= 3

        # Stop and resume — backlog should still be there
        await lifecycle.resume_stage(activation.id, process_step.id)
        await lifecycle.stop_stage(activation.id, process_step.id)

        summaries = await lifecycle.get_queue_summary(activation.id)
        proc_summary = next(s for s in summaries if s.stage_order == process_step.step_order)
        assert proc_summary.queued_count >= 3, (
            "Backlog must survive stop/resume cycles within same activation"
        )
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_double_stop_is_idempotent(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Stopping an already-stopped stage should not error."""
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)
        lifecycle = StageLifecycleManager(db=async_session)

        await lifecycle.stop_stage(activation.id, steps[0].id)
        state = await lifecycle.stop_stage(activation.id, steps[0].id)  # idempotent
        assert state.runtime_status == "STOPPED"
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_double_resume_is_idempotent(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Resuming an already-running stage should not error."""
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)
        lifecycle = StageLifecycleManager(db=async_session)

        state = await lifecycle.resume_stage(activation.id, steps[0].id)  # already running
        assert state.runtime_status == "RUNNING"
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.xfail(
    reason="Cluster failover with stage stop state preservation requires .NET engine",
    strict=False,
)
@pytest.mark.asyncio
async def test_cluster_failover_preserves_stage_stop():
    """In a cluster failover scenario, stage stop state should be preserved
    or explicitly reset. This requires the .NET engine's lease mechanism.
    """
    raise NotImplementedError("Requires .NET engine cluster support")


@pytest.mark.xfail(
    reason="Reprocess interruption recovery not yet implemented",
    strict=False,
)
@pytest.mark.asyncio
async def test_reprocess_interrupted_mid_execution():
    """If reprocess is interrupted (crash mid-step), the system should:
    - not leave orphan in-flight records
    - allow retry of the reprocess request
    - maintain audit consistency
    """
    raise NotImplementedError("Requires crash recovery in orchestrator")
