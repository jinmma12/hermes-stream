"""Pipeline models - configured data pipelines with ordered steps."""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hermes.domain.models.base import Base, TimestampMixin


class PipelineInstance(TimestampMixin, Base):
    __tablename__ = "pipeline_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    monitoring_type: Mapped[str | None] = mapped_column(String(20))
    monitoring_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    steps: Mapped[list["PipelineStep"]] = relationship(
        back_populates="pipeline_instance",
        cascade="all, delete-orphan",
        order_by="PipelineStep.step_order",
    )
    activations: Mapped[list["PipelineActivation"]] = relationship(  # type: ignore[name-defined]
        back_populates="pipeline_instance",
    )


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    pipeline_instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_instances.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    on_error: Mapped[str] = mapped_column(String(10), nullable=False, server_default="STOP")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    pipeline_instance: Mapped["PipelineInstance"] = relationship(back_populates="steps")
