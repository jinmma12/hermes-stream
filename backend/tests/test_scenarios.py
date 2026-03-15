"""Integration / scenario tests - full end-to-end workflows.

These tests combine multiple Vessel subsystems to validate real-world
usage patterns: file collection pipelines, API monitoring with reprocessing,
and recipe change workflows.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.execution import (
    ExecutionEventLog,
    ExecutionSnapshot,
    ReprocessRequest,
    WorkItem,
    WorkItemExecution,
    WorkItemStepExecution,
)
from vessel.domain.models.instance import (
    AlgorithmInstanceVersion,
    CollectorInstanceVersion,
)
from vessel.domain.models.monitoring import PipelineActivation
from vessel.domain.models.pipeline import PipelineInstance, PipelineStep
from vessel.domain.services.execution_dispatcher import ExecutionDispatcher, ExecutionResult
from vessel.domain.services.monitoring_engine import FileMonitor, MonitorEvent
from vessel.domain.services.processing_orchestrator import ProcessingOrchestrator
from vessel.domain.services.recipe_engine import RecipeEngine
from vessel.domain.services.snapshot_resolver import (
    ResolvedConfig,
    SnapshotResolver,
    StepConfig,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_dispatcher_fn(results: list[ExecutionResult] | None = None):
    """Create a mock dispatcher."""
    d = AsyncMock(spec=ExecutionDispatcher)
    if results is None:
        ok = ExecutionResult(success=True, output={"data": []}, summary={"ok": True}, duration_ms=10)
        d.dispatch = AsyncMock(return_value=ok)
    else:
        d.dispatch = AsyncMock(side_effect=results)
    return d


def _mock_resolver_fn(
    async_session: AsyncSession,
    steps: list[PipelineStep],
):
    """Create a mock resolver."""
    resolver = AsyncMock(spec=SnapshotResolver)

    async def capture(pipeline, pipeline_steps, execution_id, use_latest):
        snap = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config={"name": pipeline.name},
            collector_config={},
            algorithm_config={},
            transfer_config={},
            snapshot_hash=f"hash-{str(execution_id)[:8]}",
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


# ---------------------------------------------------------------------------
# Scenario 1: File Collection Pipeline
# ---------------------------------------------------------------------------


class TestScenarioFileCollection:
    """
    Scenario: Equipment generates CSV files that need processing.

    1. Define a File Watcher collector
    2. Define a CSV Parser algorithm
    3. Define a File Output transfer
    4. Create instances with recipes
    5. Create pipeline: watch -> parse -> output
    6. Activate pipeline
    7. Create a test CSV file
    8. Verify: WorkItem created, processed through all steps
    """

    @pytest.mark.asyncio
    async def test_scenario_file_collection_pipeline(
        self,
        async_session: AsyncSession,
        sample_pipeline,
        tmp_path: Path,
    ):
        """End-to-end file collection scenario."""
        pipeline, steps = sample_pipeline

        # Step 1-5: Pipeline already created via fixtures

        # Step 6: Simulate activation
        activation = PipelineActivation(
            pipeline_instance_id=pipeline.id,
            status="RUNNING",
        )
        async_session.add(activation)
        await async_session.flush()

        # Step 7: Simulate file detection via FileMonitor
        watch_dir = tmp_path / "watch"
        watch_dir.mkdir()
        csv_file = watch_dir / "sensor-data-001.csv"
        csv_file.write_text("timestamp,value\n2026-01-01T00:00:00,42.5\n")

        monitor = FileMonitor({
            "watch_path": str(watch_dir),
            "pattern": "*.csv",
        })
        events = await monitor.poll()
        assert len(events) == 1, "Should detect the CSV file"

        # Create WorkItem from the detected event
        event = events[0]
        work_item = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type=event.event_type,
            source_key=event.key,
            source_metadata=event.metadata,
            dedup_key=f"FILE:{event.metadata.get('path', event.key)}",
            detected_at=event.detected_at,
            status="QUEUED",
        )
        async_session.add(work_item)
        await async_session.flush()

        # Step 8: Process the work item through the pipeline
        collect_output = {"data": [{"timestamp": "2026-01-01", "value": 42.5}], "record_count": 1}
        algo_output = {"filtered_data": [{"timestamp": "2026-01-01", "value": 42.5}], "filtered_count": 1}
        transfer_output = {"bytes_written": 128, "output_path": "/tmp/output.json"}

        results = [
            ExecutionResult(success=True, output=collect_output, summary={"records": 1}, duration_ms=50),
            ExecutionResult(success=True, output=algo_output, summary={"filtered": 1}, duration_ms=30),
            ExecutionResult(success=True, output=transfer_output, summary={"bytes": 128}, duration_ms=20),
        ]

        dispatcher = _mock_dispatcher_fn(results)
        resolver = _mock_resolver_fn(async_session, steps)

        orchestrator = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher, snapshot_resolver=resolver,
        )
        execution = await orchestrator.process_work_item(work_item.id)

        # Verify
        assert execution.status == "COMPLETED", f"Pipeline should complete, got: {execution.status}"
        assert execution.duration_ms > 0
        assert dispatcher.dispatch.call_count == 3, "All 3 steps should be dispatched"

        await async_session.refresh(work_item)
        assert work_item.status == "COMPLETED"
        assert work_item.execution_count == 1
        assert work_item.last_completed_at is not None

        # Verify event logs
        log_stmt = select(ExecutionEventLog).where(
            ExecutionEventLog.execution_id == execution.id
        )
        log_result = await async_session.execute(log_stmt)
        event_logs = list(log_result.scalars().all())
        codes = [log.event_code for log in event_logs]
        assert "EXECUTION_START" in codes
        assert "COLLECT_START" in codes
        assert "COLLECT_DONE" in codes
        assert "ALGORITHM_START" in codes
        assert "ALGORITHM_DONE" in codes
        assert "TRANSFER_START" in codes
        assert "TRANSFER_DONE" in codes
        assert "EXECUTION_END" in codes


# ---------------------------------------------------------------------------
# Scenario 2: API Monitoring with Reprocess
# ---------------------------------------------------------------------------


class TestScenarioApiMonitoringReprocess:
    """
    Scenario: Monitor external API, reprocess on failure.

    1. Define REST API collector
    2. Define JSON Transform algorithm (threshold-based)
    3. Define REST API transfer
    4. Create pipeline and activate
    5. Mock API returns data -> WorkItem created
    6. Algorithm fails (bad threshold)
    7. User updates recipe (new threshold)
    8. Reprocess -> succeeds
    9. Verify full execution history with both attempts
    """

    @pytest.mark.asyncio
    async def test_scenario_api_monitoring_with_reprocess(
        self,
        async_session: AsyncSession,
        sample_pipeline,
        sample_algorithm_instance,
    ):
        """End-to-end API monitoring with reprocess after failure."""
        pipeline, steps = sample_pipeline
        algo_inst, algo_ver = sample_algorithm_instance

        # Step 4: Activate
        activation = PipelineActivation(
            pipeline_instance_id=pipeline.id,
            status="RUNNING",
        )
        async_session.add(activation)
        await async_session.flush()

        # Step 5: Create work item (simulating API poll detection)
        work_item = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="API_RESPONSE",
            source_key="api-response-hash-abc",
            source_metadata={"url": "https://api.example.com/data", "status_code": 200},
            dedup_key="API_RESPONSE:abc123",
            status="QUEUED",
        )
        async_session.add(work_item)
        await async_session.flush()

        # Step 6: Algorithm fails (threshold too aggressive)
        fail_results = [
            ExecutionResult(success=True, output={"data": [{"value": 3.5}]}, summary={}, duration_ms=10),
            ExecutionResult(
                success=False, output={}, summary={}, duration_ms=5,
                logs=[{"level": "ERROR", "message": "Value 3.5 exceeds threshold 2.5"}],
            ),
        ]
        dispatcher1 = _mock_dispatcher_fn(fail_results)
        resolver1 = _mock_resolver_fn(async_session, steps)

        orchestrator1 = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher1, snapshot_resolver=resolver1,
        )
        exec1 = await orchestrator1.process_work_item(work_item.id)
        assert exec1.status == "FAILED"

        # Step 7: User updates recipe (threshold 2.5 -> 5.0)
        engine = RecipeEngine(async_session)
        new_recipe = await engine.create_recipe(
            instance_type="ALGORITHM",
            instance_id=algo_inst.id,
            config_json={"threshold": 5.0, "field_name": "value"},
            change_note="Increased threshold to accommodate higher values",
            created_by="operator-bob",
        )
        await engine.publish_recipe("ALGORITHM", algo_inst.id, new_recipe.version_no)

        # Step 8: Reprocess
        rr = ReprocessRequest(
            work_item_id=work_item.id,
            requested_by="operator-bob",
            reason="Retry with increased threshold (2.5 -> 5.0)",
            use_latest_recipe=True,
            status="PENDING",
        )
        async_session.add(rr)
        await async_session.flush()

        dispatcher2 = _mock_dispatcher_fn()  # all succeed
        resolver2 = _mock_resolver_fn(async_session, steps)
        orchestrator2 = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher2, snapshot_resolver=resolver2,
        )
        exec2 = await orchestrator2.reprocess_work_item(rr.id)

        # Step 9: Verify full history
        assert exec2.status == "COMPLETED"
        assert exec2.trigger_type == "REPROCESS"

        # Both executions exist
        exec_stmt = select(WorkItemExecution).where(
            WorkItemExecution.work_item_id == work_item.id
        ).order_by(WorkItemExecution.execution_no)
        result = await async_session.execute(exec_stmt)
        all_execs = list(result.scalars().all())

        assert len(all_execs) == 2, "Should have 2 executions"
        assert all_execs[0].status == "FAILED"
        assert all_execs[0].trigger_type == "INITIAL"
        assert all_execs[1].status == "COMPLETED"
        assert all_execs[1].trigger_type == "REPROCESS"

        # Both have snapshots
        snap_stmt = select(ExecutionSnapshot).where(
            ExecutionSnapshot.execution_id.in_([e.id for e in all_execs])
        )
        snap_result = await async_session.execute(snap_stmt)
        snapshots = list(snap_result.scalars().all())
        assert len(snapshots) == 2, "Both executions should have snapshots"

        # Work item is now COMPLETED
        await async_session.refresh(work_item)
        assert work_item.status == "COMPLETED"
        assert work_item.execution_count == 2


# ---------------------------------------------------------------------------
# Scenario 3: Recipe Change Workflow
# ---------------------------------------------------------------------------


class TestScenarioRecipeChange:
    """
    Scenario: Non-developer changes algorithm parameters.

    1. Pipeline running with recipe v1
    2. WorkItems processed with v1
    3. Operator creates recipe v2 (change threshold)
    4. New WorkItems use v2
    5. Old WorkItems still show v1 in their snapshots
    6. Recipe diff shows changes between v1 and v2
    """

    @pytest.mark.asyncio
    async def test_scenario_recipe_change_workflow(
        self,
        async_session: AsyncSession,
        sample_pipeline,
        sample_algorithm_instance,
    ):
        """End-to-end recipe change workflow."""
        pipeline, steps = sample_pipeline
        algo_inst, algo_ver_v1 = sample_algorithm_instance

        activation = PipelineActivation(
            pipeline_instance_id=pipeline.id,
            status="RUNNING",
        )
        async_session.add(activation)
        await async_session.flush()

        # Step 1-2: Process a work item with recipe v1
        wi1 = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="FILE",
            source_key="batch-001.csv",
            dedup_key="FILE:batch-001",
            status="QUEUED",
        )
        async_session.add(wi1)
        await async_session.flush()

        dispatcher1 = _mock_dispatcher_fn()
        resolver1 = _mock_resolver_fn(async_session, steps)
        orch1 = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher1, snapshot_resolver=resolver1,
        )
        exec1 = await orch1.process_work_item(wi1.id)
        assert exec1.status == "COMPLETED"

        # Capture v1 snapshot hash for later comparison
        snap1_stmt = select(ExecutionSnapshot).where(
            ExecutionSnapshot.execution_id == exec1.id
        )
        snap1_result = await async_session.execute(snap1_stmt)
        snap1 = snap1_result.scalar_one()
        v1_hash = snap1.snapshot_hash

        # Step 3: Operator creates recipe v2
        engine = RecipeEngine(async_session)
        v2 = await engine.create_recipe(
            instance_type="ALGORITHM",
            instance_id=algo_inst.id,
            config_json={"threshold": 5.0, "field_name": "temperature"},
            change_note="Changed threshold and field for temperature monitoring",
            created_by="operator-charlie",
        )
        await engine.publish_recipe("ALGORITHM", algo_inst.id, v2.version_no)

        # Step 4: Process new work item (will use v2)
        wi2 = WorkItem(
            pipeline_activation_id=activation.id,
            pipeline_instance_id=pipeline.id,
            source_type="FILE",
            source_key="batch-002.csv",
            dedup_key="FILE:batch-002",
            status="QUEUED",
        )
        async_session.add(wi2)
        await async_session.flush()

        dispatcher2 = _mock_dispatcher_fn()
        resolver2 = _mock_resolver_fn(async_session, steps)
        orch2 = ProcessingOrchestrator(
            db=async_session, dispatcher=dispatcher2, snapshot_resolver=resolver2,
        )
        exec2 = await orch2.process_work_item(wi2.id)
        assert exec2.status == "COMPLETED"

        # Step 5: Old work item's snapshot still reflects v1 config
        await async_session.refresh(snap1)
        assert snap1.snapshot_hash == v1_hash, (
            "Old snapshot should be unchanged after recipe update"
        )

        # Step 6: Recipe diff shows changes
        diff = await engine.compare_recipes("ALGORITHM", algo_inst.id, 1, 2)
        assert diff.version_no_1 == 1
        assert diff.version_no_2 == 2

        # threshold changed from 2.5 to 5.0
        assert "threshold" in diff.changed
        assert diff.changed["threshold"]["from"] == 2.5
        assert diff.changed["threshold"]["to"] == 5.0

        # field_name changed from "value" to "temperature"
        assert "field_name" in diff.changed
        assert diff.changed["field_name"]["from"] == "value"
        assert diff.changed["field_name"]["to"] == "temperature"

        # Verify both work items have distinct execution histories
        for wi in [wi1, wi2]:
            await async_session.refresh(wi)
            assert wi.status == "COMPLETED"
            assert wi.execution_count == 1
