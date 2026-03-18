"""Tests for the Processing Orchestrator - per-WorkItem pipeline execution.

Covers sequential step execution, error handling modes (STOP, SKIP, RETRY),
disabled step skipping, output chaining between steps, and timing recording.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    WorkItem,
)
from vessel.domain.models.monitoring import PipelineActivation
from vessel.domain.models.pipeline import PipelineInstance, PipelineStep
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.domain.services.snapshot_resolver import ResolvedConfig, SnapshotResolver, StepConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_dispatcher(results: list[ExecutionResult]) -> ExecutionDispatcher:
    """Create a mock dispatcher that returns results in sequence."""
    d = AsyncMock(spec=ExecutionDispatcher)
    d.dispatch = AsyncMock(side_effect=results)
    return d


def _mock_resolver(
    async_session: AsyncSession,
    steps: list[PipelineStep],
) -> SnapshotResolver:
    """Create a mock resolver for the given steps."""
    resolver = AsyncMock(spec=SnapshotResolver)

    async def capture(pipeline, pipeline_steps, execution_id, use_latest):
        snap = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config={"name": pipeline.name},
            collector_config={},
            algorithm_config={},
            transfer_config={},
            snapshot_hash="test-hash",
        )
        async_session.add(snap)
        await async_session.flush()
        return snap

    async def resolve(snapshot_id):
        rc = ResolvedConfig(pipeline_config={})
        for step in steps:
            rc.steps.append(
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
        return rc

    resolver.capture = AsyncMock(side_effect=capture)
    resolver.resolve = AsyncMock(side_effect=resolve)
    return resolver


async def _setup_work_item(
    async_session: AsyncSession,
    pipeline: PipelineInstance,
) -> WorkItem:
    """Create an activation and work item for testing."""
    activation = PipelineActivation(
        pipeline_instance_id=pipeline.id,
        status="RUNNING",
    )
    async_session.add(activation)
    await async_session.flush()

    wi = WorkItem(
        pipeline_activation_id=activation.id,
        pipeline_instance_id=pipeline.id,
        source_type="FILE",
        source_key="test.csv",
        status="DETECTED",
    )
    async_session.add(wi)
    await async_session.flush()
    return wi


# ---------------------------------------------------------------------------
# Sequential execution
# ---------------------------------------------------------------------------


class TestSequentialExecution:
    """Tests for steps running in the correct order."""

    @pytest.mark.asyncio
    async def test_sequential_step_execution(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Steps are dispatched in step_order sequence."""
        pipeline, steps = sample_pipeline
        wi = await _setup_work_item(async_session, pipeline)

        call_order: list[str] = []

        async def track_dispatch(**kwargs):
            step_type = kwargs.get("context", {}).get("step_type", "?")
            call_order.append(step_type)
            return ExecutionResult(success=True, output={"data": []}, summary={}, duration_ms=5)

        dispatcher = AsyncMock(spec=ExecutionDispatcher)
        dispatcher.dispatch = AsyncMock(side_effect=track_dispatch)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.status == "COMPLETED"
        assert call_order == ["COLLECT", "ALGORITHM", "TRANSFER"], (
            f"Steps should run in order, got: {call_order}"
        )


# ---------------------------------------------------------------------------
# Error handling modes
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for on_error=STOP, SKIP, and RETRY behaviours."""

    @pytest.mark.asyncio
    async def test_step_on_error_stop(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """on_error=STOP: failure halts the pipeline."""
        pipeline, steps = sample_pipeline
        wi = await _setup_work_item(async_session, pipeline)

        # Step 1 succeeds, step 2 fails (on_error=STOP is default)
        results = [
            ExecutionResult(success=True, output={}, summary={}, duration_ms=5),
            ExecutionResult(
                success=False, output={}, summary={}, duration_ms=3,
                logs=[{"level": "ERROR", "message": "boom"}],
            ),
        ]
        dispatcher = _mock_dispatcher(results)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.status == "FAILED"
        assert dispatcher.dispatch.call_count == 2, "Step 3 should not be called"

    @pytest.mark.asyncio
    async def test_step_on_error_skip(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """on_error=SKIP: failure skips the step, continues to next."""
        pipeline, steps = sample_pipeline

        # Set step 2 to SKIP on error
        steps[1].on_error = "SKIP"
        await async_session.flush()

        wi = await _setup_work_item(async_session, pipeline)

        results = [
            ExecutionResult(success=True, output={"collect": True}, summary={}, duration_ms=5),
            ExecutionResult(
                success=False, output={}, summary={}, duration_ms=3,
                logs=[{"level": "ERROR", "message": "skip me"}],
            ),
            ExecutionResult(success=True, output={"transfer": True}, summary={}, duration_ms=5),
        ]
        dispatcher = _mock_dispatcher(results)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.status == "COMPLETED", (
            "Pipeline should COMPLETE even though step 2 failed (SKIP mode)"
        )
        assert dispatcher.dispatch.call_count == 3, "All 3 steps should be attempted"

        # Check event logs for SKIPPED entry
        log_stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == execution.id,
            ExecutionEventLog.event_code.like("%SKIPPED%"),
        )
        result = await async_session.execute(log_stmt)
        skip_logs = list(result.scalars().all())
        assert len(skip_logs) >= 1, "Should have a SKIPPED event log"

    @pytest.mark.asyncio
    async def test_step_on_error_retry(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """on_error=RETRY: step is retried N times with delay."""
        pipeline, steps = sample_pipeline

        # Set step 2 to RETRY with 2 retries and 0 delay for speed
        steps[1].on_error = "RETRY"
        steps[1].retry_count = 2
        steps[1].retry_delay_seconds = 0
        await async_session.flush()

        wi = await _setup_work_item(async_session, pipeline)

        call_count = 0

        async def dispatch_with_retry(**kwargs):
            nonlocal call_count
            call_count += 1
            step_type = kwargs.get("context", {}).get("step_type", "?")
            if step_type == "ALGORITHM" and call_count <= 2:
                # First call is the initial attempt (fails),
                # second call might be retry (fails or succeeds)
                return ExecutionResult(
                    success=False, output={}, summary={}, duration_ms=3,
                    logs=[{"level": "ERROR", "message": "retry needed"}],
                )
            return ExecutionResult(success=True, output={}, summary={}, duration_ms=5)

        dispatcher = AsyncMock(spec=ExecutionDispatcher)
        dispatcher.dispatch = AsyncMock(side_effect=dispatch_with_retry)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        await orch.process_work_item(wi.id)

        # The initial attempt fails, then retry succeeds on attempt 2
        # So total calls: step1(ok) + step2(fail) + retry1(fail) + retry2(ok) + step3(ok)
        assert dispatcher.dispatch.call_count >= 3, (
            f"Should have retried, got {dispatcher.dispatch.call_count} calls"
        )


# ---------------------------------------------------------------------------
# Disabled steps
# ---------------------------------------------------------------------------


class TestDisabledSteps:
    """Tests for disabled step handling."""

    @pytest.mark.asyncio
    async def test_disabled_step_skipped(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """is_enabled=False step is not dispatched."""
        pipeline, steps = sample_pipeline

        # Disable step 2 (ALGORITHM)
        steps[1].is_enabled = False
        await async_session.flush()

        wi = await _setup_work_item(async_session, pipeline)

        results = [
            ExecutionResult(success=True, output={"from_collect": True}, summary={}, duration_ms=5),
            ExecutionResult(success=True, output={"from_transfer": True}, summary={}, duration_ms=5),
        ]
        dispatcher = _mock_dispatcher(results)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.status == "COMPLETED"
        assert dispatcher.dispatch.call_count == 2, (
            "Disabled step should be skipped - only 2 dispatches"
        )


# ---------------------------------------------------------------------------
# Output chaining
# ---------------------------------------------------------------------------


class TestOutputChaining:
    """Tests for output of step N being input to step N+1."""

    @pytest.mark.asyncio
    async def test_step_output_feeds_next_input(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Output from step 1 is passed as input_data to step 2."""
        pipeline, steps = sample_pipeline
        wi = await _setup_work_item(async_session, pipeline)

        received_inputs: list[Any] = []

        async def capture_dispatch(**kwargs):
            received_inputs.append(kwargs.get("input_data"))
            step_type = kwargs.get("context", {}).get("step_type", "?")
            if step_type == "COLLECT":
                return ExecutionResult(
                    success=True,
                    output={"collected_data": [1, 2, 3]},
                    summary={},
                    duration_ms=5,
                )
            elif step_type == "ALGORITHM":
                return ExecutionResult(
                    success=True,
                    output={"processed_data": [2, 3]},
                    summary={},
                    duration_ms=5,
                )
            return ExecutionResult(success=True, output={}, summary={}, duration_ms=5)

        dispatcher = AsyncMock(spec=ExecutionDispatcher)
        dispatcher.dispatch = AsyncMock(side_effect=capture_dispatch)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.status == "COMPLETED"
        # Step 1 receives None (no previous output)
        assert received_inputs[0] is None
        # Step 2 receives output from step 1
        assert received_inputs[1] == {"collected_data": [1, 2, 3]}
        # Step 3 receives output from step 2
        assert received_inputs[2] == {"processed_data": [2, 3]}


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


class TestExecutionTiming:
    """Tests for execution timing recording."""

    @pytest.mark.asyncio
    async def test_execution_timing_recorded(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """duration_ms is recorded on the execution record."""
        pipeline, steps = sample_pipeline
        wi = await _setup_work_item(async_session, pipeline)

        ok = ExecutionResult(success=True, output={}, summary={}, duration_ms=10)
        dispatcher = AsyncMock(spec=ExecutionDispatcher)
        dispatcher.dispatch = AsyncMock(return_value=ok)
        resolver = _mock_resolver(async_session, steps)

        orch = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orch.process_work_item(wi.id)

        assert execution.duration_ms is not None
        assert execution.duration_ms >= 0, "duration_ms should be non-negative"
        assert execution.started_at is not None
        assert execution.ended_at is not None
        assert execution.ended_at >= execution.started_at
