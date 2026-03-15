"""Monitoring layer models - 'What IS running' (activations)."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vessel.domain.models.base import Base


class PipelineActivation(Base):
    __tablename__ = "pipeline_activations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    pipeline_instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_instances.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="STARTING")
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column()
    last_heartbeat_at: Mapped[datetime | None] = mapped_column()
    last_polled_at: Mapped[datetime | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    pipeline_instance: Mapped["PipelineInstance"] = relationship(  # type: ignore[name-defined]
        back_populates="activations",
    )
    work_items: Mapped[list["WorkItem"]] = relationship(  # type: ignore[name-defined]
        back_populates="pipeline_activation",
    )
