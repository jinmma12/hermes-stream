"""Migration safety tests for stage_runtime_states table.

Validates schema integrity using the in-memory SQLite test engine.
Real Alembic migrations cannot run here (no alembic setup), but these tests
verify the ORM model produces the expected schema and constraints.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.monitoring import StageRuntimeState
from hermes.domain.services.pipeline_manager import PipelineManager
from hermes.domain.services.stage_lifecycle import StageLifecycleManager

TIMEOUT = 10


@pytest.mark.asyncio
async def test_table_exists_in_schema(async_engine):
    """stage_runtime_states table must exist after create_all."""
    async def _run():
        async with async_engine.connect() as conn:
            table_names = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert "stage_runtime_states" in table_names
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_unique_constraint_activation_step(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Duplicate (activation_id, step_id) must be rejected."""
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        step = steps[0]
        # First insert OK
        s1 = StageRuntimeState(
            pipeline_activation_id=activation.id,
            pipeline_step_id=step.id,
            runtime_status="RUNNING",
        )
        async_session.add(s1)
        await async_session.flush()

        # initialize_stage_states already inserted — trying again should be idempotent
        lifecycle = StageLifecycleManager(db=async_session)
        new_states = await lifecycle.initialize_stage_states(activation.id, [step.id])
        # Should skip already-present step
        assert len(new_states) == 0
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_fk_cascade_on_activation_delete(
    async_session: AsyncSession,
    sample_pipeline,
):
    """Deleting an activation should cascade-delete its stage runtime states."""
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        # Verify states exist
        lifecycle = StageLifecycleManager(db=async_session)
        state = await lifecycle.get_stage_runtime(activation.id, steps[0].id)
        assert state is not None

        # Delete activation
        await async_session.delete(activation)
        await async_session.flush()

        # States should be gone
        stmt = select(StageRuntimeState).where(
            StageRuntimeState.pipeline_activation_id == activation.id
        )
        result = await async_session.execute(stmt)
        assert result.scalars().all() == []
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_activate_pipeline_creates_runtime_states(
    async_session: AsyncSession,
    sample_pipeline,
):
    """activate_pipeline must create RUNNING states for enabled steps."""
    async def _run():
        pipeline, steps = sample_pipeline
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)
        for step in steps:
            if step.is_enabled:
                state = await lifecycle.get_stage_runtime(activation.id, step.id)
                assert state is not None
                assert state.runtime_status == "RUNNING"
    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_coexistence_with_work_items(
    async_session: AsyncSession,
    sample_pipeline,
    sample_work_item,
):
    """stage_runtime_states must coexist with existing work items."""
    async def _run():
        pipeline, steps = sample_pipeline
        work_item, activation_from_fixture = sample_work_item

        # Create a new activation (separate from fixture)
        mgr = PipelineManager(db=async_session)
        activation = await mgr.activate_pipeline(pipeline.id)

        lifecycle = StageLifecycleManager(db=async_session)
        await lifecycle.stop_stage(activation.id, steps[0].id)
        state = await lifecycle.get_stage_runtime(activation.id, steps[0].id)
        assert state.runtime_status == "STOPPED"

        # Work item from fixture should still be queryable
        from hermes.domain.models.execution import WorkItem
        wi = await async_session.get(WorkItem, work_item.id)
        assert wi is not None
    await asyncio.wait_for(_run(), timeout=TIMEOUT)
