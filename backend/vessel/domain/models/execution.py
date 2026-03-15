"""Execution layer models - 'What HAS happened' (work items, logs)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vessel.domain.models.base import Base, TimestampMixin


class WorkItem(TimestampMixin, Base):
    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    pipeline_activation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_activations.id", ondelete="RESTRICT"), nullable=False
    )
    pipeline_instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_instances.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedup_key: Mapped[str | None] = mapped_column(String(512))
    detected_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DETECTED")
    current_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_item_executions.id", ondelete="SET NULL", use_alter=True)
    )
    execution_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_completed_at: Mapped[datetime | None] = mapped_column()

    pipeline_activation: Mapped["PipelineActivation"] = relationship(  # type: ignore[name-defined]
        back_populates="work_items",
    )
    pipeline_instance: Mapped["PipelineInstance"] = relationship()  # type: ignore[name-defined]
    executions: Mapped[list["WorkItemExecution"]] = relationship(
        back_populates="work_item",
        cascade="all, delete-orphan",
        foreign_keys="WorkItemExecution.work_item_id",
    )
    reprocess_requests: Mapped[list["ReprocessRequest"]] = relationship(
        back_populates="work_item",
        cascade="all, delete-orphan",
    )


class WorkItemExecution(Base):
    __tablename__ = "work_item_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    execution_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="INITIAL")
    trigger_source: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    reprocess_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reprocess_requests.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    work_item: Mapped["WorkItem"] = relationship(
        back_populates="executions",
        foreign_keys=[work_item_id],
    )
    step_executions: Mapped[list["WorkItemStepExecution"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
    )
    snapshot: Mapped["ExecutionSnapshot | None"] = relationship(
        back_populates="execution",
        uselist=False,
    )
    event_logs: Mapped[list["ExecutionEventLog"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class WorkItemStepExecution(Base):
    __tablename__ = "work_item_step_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_item_executions.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_step_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_steps.id", ondelete="RESTRICT"), nullable=False
    )
    step_type: Mapped[str] = mapped_column(String(20), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    started_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    input_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    execution: Mapped["WorkItemExecution"] = relationship(back_populates="step_executions")
    pipeline_step: Mapped["PipelineStep"] = relationship()  # type: ignore[name-defined]
    event_logs: Mapped[list["ExecutionEventLog"]] = relationship(
        back_populates="step_execution",
    )


class ExecutionSnapshot(Base):
    __tablename__ = "execution_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_item_executions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    pipeline_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    collector_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    algorithm_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    transfer_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    snapshot_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    execution: Mapped["WorkItemExecution"] = relationship(back_populates="snapshot")


class ReprocessRequest(TimestampMixin, Base):
    __tablename__ = "reprocess_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(256), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    start_from_step: Mapped[int | None] = mapped_column(Integer)
    use_latest_recipe: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDING")
    approved_by: Mapped[str | None] = mapped_column(String(256))
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_item_executions.id", ondelete="SET NULL", use_alter=True)
    )

    work_item: Mapped["WorkItem"] = relationship(back_populates="reprocess_requests")


class ExecutionEventLog(Base):
    __tablename__ = "execution_event_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_item_executions.id", ondelete="CASCADE"), nullable=False
    )
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_item_step_executions.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="INFO")
    event_code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    execution: Mapped["WorkItemExecution"] = relationship(back_populates="event_logs")
    step_execution: Mapped["WorkItemStepExecution | None"] = relationship(back_populates="event_logs")
