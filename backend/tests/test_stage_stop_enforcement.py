"""Tests that stage stop is enforced by the orchestrator at dispatch time.

Validates Finding 1: stopped stages must block real dispatch, not just write
a status row. Also validates Finding 5: stop/resume reject invalid step/activation.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.execution import WorkItem
from hermes.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from hermes.domain.services.pipeline_manager import PipelineManager
from hermes.domain.services.processing_orchestrator import ProcessingOrchestrator
from hermes.domain.services.snapshot_resolver import SnapshotResolver
from hermes.domain.services.stage_lifecycle import StageLifecycleManager


class FakeDispatcher(ExecutionDispatcher):
    """Deterministic dispatcher for enforcement tests."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict] = []

    async def dispatch(self, execution_type, execution_ref, config, input_data, context):
        self.calls.append({"step_type": context.get("step_type", "")})
        return ExecutionResult(
            success=True, output={}, summary={}, duration_ms=1, logs=[],
        )

TIMEOUT = 10


@pytest.mark.asyncio
async def test_orchestrator_stops_at_stopped_stage(
    async_session: AsyncSession,
    sample_pipeline,
):
    """When a stage is STOPPED, the orchestrator must NOT dispatch into it.

    Instead it should return with status=QUEUED and the work item stays queued.
    """

    async def _run():
        pipeline, steps = sample_pipeline
        sorted_steps = sorted(steps, key=lambda s: s.step_order)
        process_step = sorted_steps[1]

        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)
        await lifecycle.stop_stage(activation.id, process_step.id)

        # Create work item
        wi = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="FILE",
            source_key="blocked.csv",
            dedup_key="FILE:blocked",
            status="DETECTED",
        )
        async_session.add(wi)
        await async_session.flush()

        # Run orchestrator with a real FakeDispatcher
        dispatcher = FakeDispatcher()
        orchestrator = ProcessingOrchestrator(
            db=async_session,
            dispatcher=dispatcher,
            snapshot_resolver=SnapshotResolver(async_session),
        )
        execution = await orchestrator.process_work_item(wi.id)

        # Execution should be QUEUED, not COMPLETED or FAILED
        assert execution.status == "QUEUED", (
            f"Expected QUEUED when stage is stopped, got {execution.status}"
        )

        # Dispatcher should only have been called for step 1 (COLLECT),
        # NOT for step 2 (ALGORITHM/PROCESS) since it's stopped
        dispatched_types = [c["step_type"] for c in dispatcher.calls]
        assert "COLLECT" in dispatched_types, "Collect step should have run"
        assert "ALGORITHM" not in dispatched_types, (
            "Stopped ALGORITHM stage must NOT be dispatched"
        )

    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_orchestrator_runs_normally_when_resumed(
    async_session: AsyncSession,
    sample_pipeline,
):
    """After resume, the orchestrator should dispatch through all stages normally."""

    async def _run():
        pipeline, steps = sample_pipeline
        sorted_steps = sorted(steps, key=lambda s: s.step_order)
        process_step = sorted_steps[1]

        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)
        await lifecycle.stop_stage(activation.id, process_step.id)
        await lifecycle.resume_stage(activation.id, process_step.id)

        wi = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="FILE",
            source_key="resumed.csv",
            dedup_key="FILE:resumed",
            status="DETECTED",
        )
        async_session.add(wi)
        await async_session.flush()

        dispatcher = FakeDispatcher()
        orchestrator = ProcessingOrchestrator(
            db=async_session,
            dispatcher=dispatcher,
            snapshot_resolver=SnapshotResolver(async_session),
        )
        execution = await orchestrator.process_work_item(wi.id)

        assert execution.status == "COMPLETED"
        dispatched_types = [c["step_type"] for c in dispatcher.calls]
        assert len(dispatched_types) == 3  # COLLECT, ALGORITHM, TRANSFER

    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_stop_stage_rejects_invalid_step(
    async_session: AsyncSession,
    sample_pipeline,
):
    """stop_stage must reject a step that doesn't belong to the activation's pipeline."""

    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)

        # Random UUID that doesn't exist
        with pytest.raises(ValueError, match="not found"):
            await lifecycle.stop_stage(activation.id, uuid.uuid4())

    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_resume_stage_rejects_invalid_activation(
    async_session: AsyncSession,
    sample_pipeline,
):
    """resume_stage must reject a nonexistent activation."""

    async def _run():
        pipeline, steps = sample_pipeline

        lifecycle = StageLifecycleManager(db=async_session)

        with pytest.raises(ValueError, match="not found"):
            await lifecycle.resume_stage(uuid.uuid4(), steps[0].id)

    await asyncio.wait_for(_run(), timeout=TIMEOUT)
