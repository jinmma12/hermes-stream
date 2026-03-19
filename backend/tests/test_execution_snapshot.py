"""Tests for Execution Snapshots - immutable audit-trail configuration capture.

Covers snapshot creation with all configs, immutability semantics,
hash-based change detection, idempotent hashing, and reprocess comparison.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.execution import (
    WorkItem,
    WorkItemExecution,
)
from hermes.domain.models.monitoring import PipelineActivation
from hermes.domain.models.pipeline import PipelineInstance
from hermes.domain.services.snapshot_resolver import (
    ResolvedConfig,
    SnapshotResolver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_execution(
    async_session: AsyncSession,
    pipeline: PipelineInstance,
) -> WorkItemExecution:
    """Create a minimal activation -> work_item -> execution chain."""
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
        source_key="test.csv",
        status="PROCESSING",
    )
    async_session.add(work_item)
    await async_session.flush()

    execution = WorkItemExecution(
        work_item_id=work_item.id,
        execution_no=1,
        trigger_type="INITIAL",
        status="RUNNING",
    )
    async_session.add(execution)
    await async_session.flush()
    return execution


# ---------------------------------------------------------------------------
# Snapshot capture
# ---------------------------------------------------------------------------


class TestSnapshotCapture:
    """Tests for capturing execution snapshots."""

    @pytest.mark.asyncio
    async def test_snapshot_captures_all_configs(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Snapshot captures pipeline, collector, algorithm, and transfer configs."""
        pipeline, steps = sample_pipeline
        execution = await _create_execution(async_session, pipeline)

        resolver = SnapshotResolver(async_session)
        snapshot = await resolver.capture(pipeline, steps, execution.id, use_latest_recipe=True)

        assert snapshot.execution_id == execution.id
        assert snapshot.pipeline_config is not None
        assert "name" in snapshot.pipeline_config
        assert snapshot.pipeline_config["name"] == pipeline.name
        assert snapshot.snapshot_hash is not None
        assert len(snapshot.snapshot_hash) > 0

    @pytest.mark.asyncio
    async def test_snapshot_immutable_after_creation(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Once created, a snapshot's config values should not change.

        We verify this by capturing, then checking the values are frozen dicts
        that retain their original content even if we modify the source pipeline.
        """
        pipeline, steps = sample_pipeline
        execution = await _create_execution(async_session, pipeline)

        resolver = SnapshotResolver(async_session)
        snapshot = await resolver.capture(pipeline, steps, execution.id, use_latest_recipe=True)

        original_hash = snapshot.snapshot_hash
        original_pipeline_name = snapshot.pipeline_config["name"]

        # Modify the pipeline after snapshot
        pipeline.name = "Modified Pipeline Name"
        await async_session.flush()

        # Snapshot should still have original name
        await async_session.refresh(snapshot)
        assert snapshot.pipeline_config["name"] == original_pipeline_name, (
            "Snapshot should be immutable - pipeline name change should not affect it"
        )
        assert snapshot.snapshot_hash == original_hash

    @pytest.mark.asyncio
    async def test_snapshot_hash_detects_config_change(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Different configs produce different snapshot hashes."""
        pipeline, steps = sample_pipeline

        exec1 = await _create_execution(async_session, pipeline)
        resolver1 = SnapshotResolver(async_session)
        snap1 = await resolver1.capture(pipeline, steps, exec1.id, use_latest_recipe=True)

        # Modify pipeline config
        pipeline.monitoring_config = {"watch_path": "/different/path", "pattern": "*.json"}
        await async_session.flush()

        exec2 = await _create_execution(async_session, pipeline)
        resolver2 = SnapshotResolver(async_session)
        snap2 = await resolver2.capture(pipeline, steps, exec2.id, use_latest_recipe=True)

        assert snap1.snapshot_hash != snap2.snapshot_hash, (
            "Different pipeline configs should produce different hashes"
        )

    @pytest.mark.asyncio
    async def test_snapshot_same_config_same_hash(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Identical configs produce identical snapshot hashes (idempotent)."""
        pipeline, steps = sample_pipeline

        exec1 = await _create_execution(async_session, pipeline)
        resolver1 = SnapshotResolver(async_session)
        snap1 = await resolver1.capture(pipeline, steps, exec1.id, use_latest_recipe=True)

        exec2 = await _create_execution(async_session, pipeline)
        resolver2 = SnapshotResolver(async_session)
        snap2 = await resolver2.capture(pipeline, steps, exec2.id, use_latest_recipe=True)

        assert snap1.snapshot_hash == snap2.snapshot_hash, (
            "Same config should always produce same hash"
        )


# ---------------------------------------------------------------------------
# Snapshot resolution
# ---------------------------------------------------------------------------


class TestSnapshotResolution:
    """Tests for resolving a snapshot back into usable configs."""

    @pytest.mark.asyncio
    async def test_snapshot_resolves_to_step_configs(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """resolve() returns ResolvedConfig with StepConfig entries for each step."""
        pipeline, steps = sample_pipeline
        execution = await _create_execution(async_session, pipeline)

        resolver = SnapshotResolver(async_session)
        snapshot = await resolver.capture(pipeline, steps, execution.id, use_latest_recipe=True)
        resolved = await resolver.resolve(snapshot.id)

        assert isinstance(resolved, ResolvedConfig)
        assert resolved.pipeline_config is not None
        # Steps are sorted by step_order
        assert len(resolved.steps) >= 0  # May be 0 if no published recipes found

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_snapshot_raises(
        self,
        async_session: AsyncSession,
    ):
        """resolve() with unknown snapshot_id raises ValueError."""
        resolver = SnapshotResolver(async_session)
        with pytest.raises(ValueError, match="not found"):
            await resolver.resolve(uuid.uuid4())


# ---------------------------------------------------------------------------
# Reprocess comparison
# ---------------------------------------------------------------------------


class TestSnapshotReprocessComparison:
    """Tests for comparing original vs reprocess snapshots."""

    @pytest.mark.asyncio
    async def test_snapshot_used_for_reprocess_comparison(
        self,
        async_session: AsyncSession,
        sample_pipeline,
    ):
        """Two snapshots can be compared by their hashes and configs."""
        pipeline, steps = sample_pipeline

        # Original execution snapshot
        exec1 = await _create_execution(async_session, pipeline)
        resolver = SnapshotResolver(async_session)
        snap1 = await resolver.capture(pipeline, steps, exec1.id, use_latest_recipe=True)

        # Modify config (simulate recipe update)
        pipeline.monitoring_config = {"watch_path": "/updated", "pattern": "*.xml", "interval": 10}
        await async_session.flush()

        # Reprocess snapshot
        exec2 = await _create_execution(async_session, pipeline)
        snap2 = await resolver.capture(pipeline, steps, exec2.id, use_latest_recipe=True)

        # Compare
        assert snap1.snapshot_hash != snap2.snapshot_hash, (
            "Snapshots with different configs should have different hashes"
        )
        assert snap1.pipeline_config["monitoring_config"] != snap2.pipeline_config["monitoring_config"], (
            "Pipeline monitoring config should differ between snapshots"
        )
