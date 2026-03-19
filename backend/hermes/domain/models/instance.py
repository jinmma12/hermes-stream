"""Instance layer models - 'What IS configured' (recipes)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hermes.domain.models.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Collector Instances
# ---------------------------------------------------------------------------


class CollectorInstance(TimestampMixin, Base):
    __tablename__ = "collector_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collector_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    definition: Mapped["CollectorDefinition"] = relationship()  # type: ignore[name-defined]
    versions: Mapped[list["CollectorInstanceVersion"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="CollectorInstanceVersion.version_no"
    )


class CollectorInstanceVersion(Base):
    __tablename__ = "collector_instance_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collector_instances.id", ondelete="CASCADE"), nullable=False
    )
    def_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collector_definition_versions.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    secret_binding_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_by: Mapped[str | None] = mapped_column(String(256))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    instance: Mapped["CollectorInstance"] = relationship(back_populates="versions")
    def_version: Mapped["CollectorDefinitionVersion"] = relationship()  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Algorithm Instances
# ---------------------------------------------------------------------------


class AlgorithmInstance(TimestampMixin, Base):
    __tablename__ = "algorithm_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    definition: Mapped["AlgorithmDefinition"] = relationship()  # type: ignore[name-defined]
    versions: Mapped[list["AlgorithmInstanceVersion"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="AlgorithmInstanceVersion.version_no"
    )


class AlgorithmInstanceVersion(Base):
    __tablename__ = "algorithm_instance_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_instances.id", ondelete="CASCADE"), nullable=False
    )
    def_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_definition_versions.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    secret_binding_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_by: Mapped[str | None] = mapped_column(String(256))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    instance: Mapped["AlgorithmInstance"] = relationship(back_populates="versions")
    def_version: Mapped["AlgorithmDefinitionVersion"] = relationship()  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# Transfer Instances
# ---------------------------------------------------------------------------


class TransferInstance(TimestampMixin, Base):
    __tablename__ = "transfer_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transfer_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    definition: Mapped["TransferDefinition"] = relationship()  # type: ignore[name-defined]
    versions: Mapped[list["TransferInstanceVersion"]] = relationship(
        back_populates="instance", cascade="all, delete-orphan", order_by="TransferInstanceVersion.version_no"
    )


class TransferInstanceVersion(Base):
    __tablename__ = "transfer_instance_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transfer_instances.id", ondelete="CASCADE"), nullable=False
    )
    def_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transfer_definition_versions.id", ondelete="RESTRICT"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    secret_binding_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_by: Mapped[str | None] = mapped_column(String(256))
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    instance: Mapped["TransferInstance"] = relationship(back_populates="versions")
    def_version: Mapped["TransferDefinitionVersion"] = relationship()  # type: ignore[name-defined]
