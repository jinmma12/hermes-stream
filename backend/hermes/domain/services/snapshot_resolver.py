"""Snapshot resolver - captures and resolves execution-time configuration."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.execution import ExecutionSnapshot
from hermes.domain.models.instance import (
    AlgorithmInstance,
    AlgorithmInstanceVersion,
    CollectorInstance,
    CollectorInstanceVersion,
    TransferInstance,
    TransferInstanceVersion,
)
from hermes.domain.models.pipeline import PipelineInstance, PipelineStep

logger = logging.getLogger(__name__)

# Maps ref_type to (InstanceModel, VersionModel)
_REF_TYPE_MAP: dict[str, tuple[type, type]] = {
    "COLLECTOR": (CollectorInstance, CollectorInstanceVersion),
    "ALGORITHM": (AlgorithmInstance, AlgorithmInstanceVersion),
    "TRANSFER": (TransferInstance, TransferInstanceVersion),
}


@dataclass
class StepConfig:
    """Resolved configuration for a single pipeline step."""

    step_id: uuid.UUID
    step_order: int
    step_type: str
    ref_type: str
    ref_id: uuid.UUID
    execution_type: str
    execution_ref: str | None
    resolved_config: dict[str, Any]
    version_no: int


@dataclass
class ResolvedConfig:
    """The full resolved configuration for an execution."""

    pipeline_config: dict[str, Any] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)

    def get_config_for_step(self, step: PipelineStep) -> StepConfig | None:
        """Look up the resolved config for a specific pipeline step."""
        for sc in self.steps:
            if sc.step_id == step.id:
                return sc
        return None


class SnapshotResolver:
    """Captures and resolves execution-time configuration snapshots."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def capture(
        self,
        pipeline: PipelineInstance,
        steps: list[PipelineStep],
        execution_id: uuid.UUID,
        use_latest_recipe: bool = True,
    ) -> ExecutionSnapshot:
        """Capture the current configuration of all steps at execution time.

        Creates an ``ExecutionSnapshot`` that preserves the exact config
        used, so it can be audited later even if recipes change.
        """
        pipeline_config: dict[str, Any] = {
            "id": str(pipeline.id),
            "name": pipeline.name,
            "monitoring_type": pipeline.monitoring_type,
            "monitoring_config": pipeline.monitoring_config,
        }

        collector_configs: dict[str, Any] = {}
        algorithm_configs: dict[str, Any] = {}
        transfer_configs: dict[str, Any] = {}

        config_buckets = {
            "COLLECTOR": collector_configs,
            "ALGORITHM": algorithm_configs,
            "TRANSFER": transfer_configs,
        }

        for step in steps:
            if not step.is_enabled:
                continue

            ref_type = step.ref_type.upper()
            models = _REF_TYPE_MAP.get(ref_type)
            if models is None:
                logger.warning("Unknown ref_type %s for step %s", ref_type, step.id)
                continue

            inst_cls, ver_cls = models

            if use_latest_recipe:
                # Use current (published) version
                stmt = (
                    select(ver_cls)
                    .where(
                        ver_cls.instance_id == step.ref_id,
                        ver_cls.is_current == True,  # noqa: E712
                    )
                    .limit(1)
                )
            else:
                # Use latest version by version_no
                stmt = (
                    select(ver_cls)
                    .where(ver_cls.instance_id == step.ref_id)
                    .order_by(ver_cls.version_no.desc())
                    .limit(1)
                )

            result = await self.db.execute(stmt)
            version = result.scalar_one_or_none()

            step_config: dict[str, Any] = {
                "step_id": str(step.id),
                "step_order": step.step_order,
                "step_type": step.step_type,
                "ref_type": step.ref_type,
                "ref_id": str(step.ref_id),
            }

            if version is not None:
                step_config["config_json"] = version.config_json
                step_config["version_no"] = version.version_no
                step_config["def_version_id"] = str(version.def_version_id)

                # Fetch execution_type and execution_ref from definition version
                from hermes.domain.models.definition import (
                    AlgorithmDefinitionVersion,
                    CollectorDefinitionVersion,
                    TransferDefinitionVersion,
                )
                def_ver_map = {
                    "COLLECTOR": CollectorDefinitionVersion,
                    "ALGORITHM": AlgorithmDefinitionVersion,
                    "TRANSFER": TransferDefinitionVersion,
                }
                def_ver_cls = def_ver_map[ref_type]
                def_ver = await self.db.get(def_ver_cls, version.def_version_id)
                if def_ver is not None:
                    step_config["execution_type"] = def_ver.execution_type
                    step_config["execution_ref"] = def_ver.execution_ref

            bucket = config_buckets.get(ref_type, collector_configs)
            bucket[str(step.id)] = step_config

        # Compute snapshot hash for comparison
        all_config = {
            "pipeline": pipeline_config,
            "collectors": collector_configs,
            "algorithms": algorithm_configs,
            "transfers": transfer_configs,
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(all_config, sort_keys=True, default=str).encode()
        ).hexdigest()[:32]

        snapshot = ExecutionSnapshot(
            execution_id=execution_id,
            pipeline_config=pipeline_config,
            collector_config=collector_configs,
            algorithm_config=algorithm_configs,
            transfer_config=transfer_configs,
            snapshot_hash=snapshot_hash,
        )
        self.db.add(snapshot)
        await self.db.flush()

        logger.info(
            "Captured snapshot for execution %s (hash=%s)",
            execution_id,
            snapshot_hash,
        )
        return snapshot

    async def resolve(self, snapshot_id: uuid.UUID) -> ResolvedConfig:
        """Load a snapshot and return its resolved configuration."""
        snapshot = await self.db.get(ExecutionSnapshot, snapshot_id)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_id} not found")

        resolved = ResolvedConfig(
            pipeline_config=snapshot.pipeline_config or {},
        )

        # Merge all step configs from collector, algorithm, transfer buckets
        for bucket in (
            snapshot.collector_config or {},
            snapshot.algorithm_config or {},
            snapshot.transfer_config or {},
        ):
            for _step_id, step_data in bucket.items():
                if not isinstance(step_data, dict):
                    continue
                resolved.steps.append(
                    StepConfig(
                        step_id=uuid.UUID(step_data["step_id"]),
                        step_order=step_data.get("step_order", 0),
                        step_type=step_data.get("step_type", ""),
                        ref_type=step_data.get("ref_type", ""),
                        ref_id=uuid.UUID(step_data["ref_id"]),
                        execution_type=step_data.get("execution_type", "PLUGIN"),
                        execution_ref=step_data.get("execution_ref"),
                        resolved_config=step_data.get("config_json", {}),
                        version_no=step_data.get("version_no", 0),
                    )
                )

        resolved.steps.sort(key=lambda s: s.step_order)
        return resolved
