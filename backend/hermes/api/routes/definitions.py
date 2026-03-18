"""API routes for Definition CRUD (Layer 1: What CAN exist)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.definition import (
    AlgorithmDefinition,
    AlgorithmDefinitionVersion,
    CollectorDefinition,
    CollectorDefinitionVersion,
    TransferDefinition,
    TransferDefinitionVersion,
)
from vessel.infrastructure.database.session import get_db

router = APIRouter(prefix="/api/v1/definitions", tags=["definitions"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class DefinitionCreate(BaseModel):
    code: str = Field(..., max_length=128)
    name: str = Field(..., max_length=256)
    description: str | None = None
    category: str | None = None
    icon_url: str | None = None


class DefinitionOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    category: str | None = None
    icon_url: str | None = None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class DefinitionVersionCreate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    execution_type: str = "PLUGIN"
    execution_ref: str | None = None


class DefinitionVersionOut(BaseModel):
    id: uuid.UUID
    definition_id: uuid.UUID
    version_no: int
    input_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    output_schema: dict[str, Any]
    default_config: dict[str, Any]
    execution_type: str
    execution_ref: str | None = None
    is_published: bool
    created_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helper to map type string to model classes
# ---------------------------------------------------------------------------

_DEF_MAP: dict[str, tuple[type, type]] = {
    "collectors": (CollectorDefinition, CollectorDefinitionVersion),
    "algorithms": (AlgorithmDefinition, AlgorithmDefinitionVersion),
    "transfers": (TransferDefinition, TransferDefinitionVersion),
}


def _get_models(kind: str) -> tuple[type, type]:
    models = _DEF_MAP.get(kind)
    if models is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown definition type: {kind}",
        )
    return models


# ---------------------------------------------------------------------------
# Endpoints (same pattern for collectors, algorithms, transfers)
# ---------------------------------------------------------------------------


@router.get("/{kind}", response_model=list[DefinitionOut])
async def list_definitions(
    kind: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all definitions of a given kind."""
    def_cls, _ = _get_models(kind)
    stmt = select(def_cls).order_by(def_cls.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{kind}", response_model=DefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_definition(
    kind: str,
    body: DefinitionCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new definition."""
    def_cls, _ = _get_models(kind)
    definition = def_cls(
        code=body.code,
        name=body.name,
        description=body.description,
        category=body.category,
        icon_url=body.icon_url,
    )
    db.add(definition)
    await db.flush()
    return definition


@router.get("/{kind}/{def_id}", response_model=DefinitionOut)
async def get_definition(
    kind: str,
    def_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a single definition by ID."""
    def_cls, _ = _get_models(kind)
    definition = await db.get(def_cls, def_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition not found")
    return definition


@router.get("/{kind}/{def_id}/versions", response_model=list[DefinitionVersionOut])
async def list_definition_versions(
    kind: str,
    def_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all versions of a definition."""
    _, ver_cls = _get_models(kind)
    stmt = (
        select(ver_cls)
        .where(ver_cls.definition_id == def_id)
        .order_by(ver_cls.version_no.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/{kind}/{def_id}/versions",
    response_model=DefinitionVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_definition_version(
    kind: str,
    def_id: uuid.UUID,
    body: DefinitionVersionCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new version for a definition."""
    def_cls, ver_cls = _get_models(kind)

    definition = await db.get(def_cls, def_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition not found")

    # Determine next version number
    stmt = (
        select(ver_cls)
        .where(ver_cls.definition_id == def_id)
        .order_by(ver_cls.version_no.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()
    next_version = (latest.version_no + 1) if latest else 1

    version = ver_cls(
        definition_id=def_id,
        version_no=next_version,
        input_schema=body.input_schema,
        ui_schema=body.ui_schema,
        output_schema=body.output_schema,
        default_config=body.default_config,
        execution_type=body.execution_type,
        execution_ref=body.execution_ref,
    )
    db.add(version)
    await db.flush()
    return version
