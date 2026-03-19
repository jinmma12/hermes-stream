"""Definition layer models - 'What CAN exist' (plugin catalog)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hermes.domain.models.base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Collector Definitions
# ---------------------------------------------------------------------------


class CollectorDefinition(TimestampMixin, Base):
    __tablename__ = "collector_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    icon_url: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    versions: Mapped[list["CollectorDefinitionVersion"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", order_by="CollectorDefinitionVersion.version_no"
    )


class CollectorDefinitionVersion(Base):
    __tablename__ = "collector_definition_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("collector_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ui_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    default_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    execution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_ref: Mapped[str | None] = mapped_column(String(512))
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    definition: Mapped["CollectorDefinition"] = relationship(back_populates="versions")


# ---------------------------------------------------------------------------
# Algorithm Definitions
# ---------------------------------------------------------------------------


class AlgorithmDefinition(TimestampMixin, Base):
    __tablename__ = "algorithm_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    icon_url: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    versions: Mapped[list["AlgorithmDefinitionVersion"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", order_by="AlgorithmDefinitionVersion.version_no"
    )


class AlgorithmDefinitionVersion(Base):
    __tablename__ = "algorithm_definition_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("algorithm_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ui_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    default_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    execution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_ref: Mapped[str | None] = mapped_column(String(512))
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    definition: Mapped["AlgorithmDefinition"] = relationship(back_populates="versions")


# ---------------------------------------------------------------------------
# Transfer Definitions
# ---------------------------------------------------------------------------


class TransferDefinition(TimestampMixin, Base):
    __tablename__ = "transfer_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    icon_url: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="DRAFT")

    versions: Mapped[list["TransferDefinitionVersion"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", order_by="TransferDefinitionVersion.version_no"
    )


class TransferDefinitionVersion(Base):
    __tablename__ = "transfer_definition_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transfer_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ui_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    default_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    execution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_ref: Mapped[str | None] = mapped_column(String(512))
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    definition: Mapped["TransferDefinition"] = relationship(back_populates="versions")
