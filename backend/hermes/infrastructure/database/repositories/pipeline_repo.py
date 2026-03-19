"""Repository for pipeline instances, steps, and activation history."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from hermes.domain.models.monitoring import PipelineActivation
from hermes.domain.models.pipeline import PipelineInstance, PipelineStep


class PipelineRepository:
    """CRUD for pipelines, step management, and activation history."""

    # ------------------------------------------------------------------
    # Pipeline CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        db: AsyncSession,
        *,
        name: str,
        description: str | None = None,
        monitoring_type: str | None = None,
        monitoring_config: dict[str, Any] | None = None,
        status: str = "DRAFT",
    ) -> PipelineInstance:
        pipeline = PipelineInstance(
            name=name,
            description=description,
            monitoring_type=monitoring_type,
            monitoring_config=monitoring_config or {},
            status=status,
        )
        db.add(pipeline)
        await db.flush()
        return pipeline

    async def get_by_id(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        *,
        with_steps: bool = False,
    ) -> PipelineInstance | None:
        stmt = select(PipelineInstance).where(PipelineInstance.id == pipeline_id)
        if with_steps:
            stmt = stmt.options(selectinload(PipelineInstance.steps))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[PipelineInstance], int]:
        stmt = select(PipelineInstance)
        count_stmt = select(func.count()).select_from(PipelineInstance)

        if status is not None:
            stmt = stmt.where(PipelineInstance.status == status)
            count_stmt = count_stmt.where(PipelineInstance.status == status)

        stmt = (
            stmt.options(selectinload(PipelineInstance.steps))
            .order_by(PipelineInstance.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        total = (await db.execute(count_stmt)).scalar_one()
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        **kwargs: Any,
    ) -> PipelineInstance | None:
        pipeline = await self.get_by_id(db, pipeline_id)
        if pipeline is None:
            return None
        for key, value in kwargs.items():
            setattr(pipeline, key, value)
        await db.flush()
        return pipeline

    async def delete(self, db: AsyncSession, pipeline_id: uuid.UUID) -> bool:
        pipeline = await self.get_by_id(db, pipeline_id)
        if pipeline is None:
            return False
        await db.delete(pipeline)
        await db.flush()
        return True

    # ------------------------------------------------------------------
    # Step management
    # ------------------------------------------------------------------

    async def add_step(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        *,
        step_order: int,
        step_type: str,
        ref_type: str,
        ref_id: uuid.UUID,
        is_enabled: bool = True,
        on_error: str = "STOP",
        retry_count: int = 0,
        retry_delay_seconds: int = 0,
    ) -> PipelineStep:
        step = PipelineStep(
            pipeline_instance_id=pipeline_id,
            step_order=step_order,
            step_type=step_type,
            ref_type=ref_type,
            ref_id=ref_id,
            is_enabled=is_enabled,
            on_error=on_error,
            retry_count=retry_count,
            retry_delay_seconds=retry_delay_seconds,
        )
        db.add(step)
        await db.flush()
        return step

    async def get_steps(
        self, db: AsyncSession, pipeline_id: uuid.UUID
    ) -> list[PipelineStep]:
        stmt = (
            select(PipelineStep)
            .where(PipelineStep.pipeline_instance_id == pipeline_id)
            .order_by(PipelineStep.step_order)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_step(
        self,
        db: AsyncSession,
        step_id: uuid.UUID,
        **kwargs: Any,
    ) -> PipelineStep | None:
        stmt = select(PipelineStep).where(PipelineStep.id == step_id)
        result = await db.execute(stmt)
        step = result.scalar_one_or_none()
        if step is None:
            return None
        for key, value in kwargs.items():
            setattr(step, key, value)
        await db.flush()
        return step

    async def delete_step(self, db: AsyncSession, step_id: uuid.UUID) -> bool:
        stmt = select(PipelineStep).where(PipelineStep.id == step_id)
        result = await db.execute(stmt)
        step = result.scalar_one_or_none()
        if step is None:
            return False
        await db.delete(step)
        await db.flush()
        return True

    async def replace_steps(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        steps_data: list[dict[str, Any]],
    ) -> list[PipelineStep]:
        """Replace all steps in a pipeline with a new ordered list."""
        # Delete existing
        existing = await self.get_steps(db, pipeline_id)
        for step in existing:
            await db.delete(step)
        await db.flush()

        # Create new
        new_steps: list[PipelineStep] = []
        for data in steps_data:
            step = PipelineStep(pipeline_instance_id=pipeline_id, **data)
            db.add(step)
            new_steps.append(step)
        await db.flush()
        return new_steps

    # ------------------------------------------------------------------
    # Activation history
    # ------------------------------------------------------------------

    async def get_activations(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[PipelineActivation]:
        stmt = select(PipelineActivation).where(
            PipelineActivation.pipeline_instance_id == pipeline_id
        )
        if status is not None:
            stmt = stmt.where(PipelineActivation.status == status)
        stmt = stmt.order_by(PipelineActivation.started_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_activation(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
    ) -> PipelineActivation | None:
        stmt = select(PipelineActivation).where(
            PipelineActivation.pipeline_instance_id == pipeline_id,
            PipelineActivation.status.in_(["STARTING", "RUNNING"]),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_activation(
        self,
        db: AsyncSession,
        pipeline_id: uuid.UUID,
        *,
        worker_id: str | None = None,
    ) -> PipelineActivation:
        activation = PipelineActivation(
            pipeline_instance_id=pipeline_id,
            worker_id=worker_id,
        )
        db.add(activation)
        await db.flush()
        return activation
