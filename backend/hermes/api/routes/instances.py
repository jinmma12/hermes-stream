"""API routes for Instance CRUD and Recipe management (Layer 2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.domain.models.definition import (
    AlgorithmDefinition,
    CollectorDefinition,
    TransferDefinition,
)
from hermes.domain.models.instance import (
    AlgorithmInstance,
    AlgorithmInstanceVersion,
    CollectorInstance,
    CollectorInstanceVersion,
    TransferInstance,
    TransferInstanceVersion,
)
from hermes.domain.services.recipe_engine import RecipeEngine
from hermes.infrastructure.database.session import get_db

router = APIRouter(prefix="/api/v1/instances", tags=["instances"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class InstanceCreate(BaseModel):
    definition_id: uuid.UUID
    name: str = Field(..., max_length=256)
    description: str | None = None


class InstanceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class InstanceOut(BaseModel):
    id: uuid.UUID
    definition_id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


class RecipeCreate(BaseModel):
    config_json: dict[str, Any] = Field(default_factory=dict)
    change_note: str | None = None
    created_by: str | None = None


class RecipeOut(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    def_version_id: uuid.UUID
    version_no: int
    config_json: dict[str, Any]
    is_current: bool
    created_by: str | None = None
    change_note: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class RecipeDiffOut(BaseModel):
    version_id_1: uuid.UUID
    version_id_2: uuid.UUID
    version_no_1: int
    version_no_2: int
    added: dict[str, Any]
    removed: dict[str, Any]
    changed: dict[str, dict[str, Any]]


# ---------------------------------------------------------------------------
# Model mapping
# ---------------------------------------------------------------------------

_KIND_MAP: dict[str, dict[str, Any]] = {
    "collectors": {
        "instance": CollectorInstance,
        "version": CollectorInstanceVersion,
        "definition": CollectorDefinition,
        "type": "COLLECTOR",
    },
    "algorithms": {
        "instance": AlgorithmInstance,
        "version": AlgorithmInstanceVersion,
        "definition": AlgorithmDefinition,
        "type": "ALGORITHM",
    },
    "transfers": {
        "instance": TransferInstance,
        "version": TransferInstanceVersion,
        "definition": TransferDefinition,
        "type": "TRANSFER",
    },
}


def _get_config(kind: str) -> dict[str, Any]:
    cfg = _KIND_MAP.get(kind)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown instance type: {kind}")
    return cfg


# ---------------------------------------------------------------------------
# Instance endpoints
# ---------------------------------------------------------------------------


@router.get("/{kind}", response_model=list[InstanceOut])
async def list_instances(
    kind: str,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all instances of a given kind."""
    cfg = _get_config(kind)
    inst_cls = cfg["instance"]
    stmt = select(inst_cls).order_by(inst_cls.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{kind}", response_model=InstanceOut, status_code=status.HTTP_201_CREATED)
async def create_instance(
    kind: str,
    body: InstanceCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new instance."""
    cfg = _get_config(kind)
    inst_cls = cfg["instance"]
    def_cls = cfg["definition"]

    definition = await db.get(def_cls, body.definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Definition not found")

    instance = inst_cls(
        definition_id=body.definition_id,
        name=body.name,
        description=body.description,
    )
    db.add(instance)
    await db.flush()
    return instance


@router.get("/{kind}/{instance_id}", response_model=InstanceOut)
async def get_instance(
    kind: str,
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a single instance by ID."""
    cfg = _get_config(kind)
    inst_cls = cfg["instance"]
    instance = await db.get(inst_cls, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance


@router.put("/{kind}/{instance_id}", response_model=InstanceOut)
async def update_instance(
    kind: str,
    instance_id: uuid.UUID,
    body: InstanceUpdate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Update instance metadata."""
    cfg = _get_config(kind)
    inst_cls = cfg["instance"]
    instance = await db.get(inst_cls, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")

    if body.name is not None:
        instance.name = body.name
    if body.description is not None:
        instance.description = body.description
    if body.status is not None:
        instance.status = body.status

    await db.flush()
    return instance


# ---------------------------------------------------------------------------
# Recipe (Instance Version) endpoints
# ---------------------------------------------------------------------------


@router.get("/{kind}/{instance_id}/recipes", response_model=list[RecipeOut])
async def list_recipes(
    kind: str,
    instance_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """List all recipe versions for an instance."""
    cfg = _get_config(kind)
    engine = RecipeEngine(db)
    versions = await engine.get_recipe_history(cfg["type"], instance_id)
    return versions


@router.post(
    "/{kind}/{instance_id}/recipes",
    response_model=RecipeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_recipe(
    kind: str,
    instance_id: uuid.UUID,
    body: RecipeCreate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Create a new recipe version for an instance."""
    cfg = _get_config(kind)
    engine = RecipeEngine(db)
    try:
        version = await engine.create_recipe(
            instance_type=cfg["type"],
            instance_id=instance_id,
            config_json=body.config_json,
            change_note=body.change_note,
            created_by=body.created_by,
        )
        return version
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{kind}/{instance_id}/recipes/{version_no}", response_model=RecipeOut)
async def get_recipe(
    kind: str,
    instance_id: uuid.UUID,
    version_no: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a specific recipe version."""
    cfg = _get_config(kind)
    engine = RecipeEngine(db)
    version = await engine.get_recipe_by_version(cfg["type"], instance_id, version_no)
    if version is None:
        raise HTTPException(status_code=404, detail="Recipe version not found")
    return version


@router.get("/{kind}/{instance_id}/recipes/diff", response_model=RecipeDiffOut)
async def diff_recipes(
    kind: str,
    instance_id: uuid.UUID,
    from_version: int = Query(..., alias="from"),
    to_version: int = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Compare two recipe versions."""
    cfg = _get_config(kind)
    engine = RecipeEngine(db)
    try:
        diff = await engine.compare_recipes(
            cfg["type"], instance_id, from_version, to_version
        )
        return diff
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{kind}/{instance_id}/recipes/{version_no}/publish", response_model=RecipeOut)
async def publish_recipe(
    kind: str,
    instance_id: uuid.UUID,
    version_no: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Publish a recipe version, making it the current active recipe."""
    cfg = _get_config(kind)
    engine = RecipeEngine(db)
    try:
        version = await engine.publish_recipe(cfg["type"], instance_id, version_no)
        return version
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
