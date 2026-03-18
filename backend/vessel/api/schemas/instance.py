"""Pydantic schemas for instance layer API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Recipe (shared across all instance types)
# ---------------------------------------------------------------------------


class RecipeCreate(BaseModel):
    """Create a new recipe version for an instance."""

    config_json: dict[str, Any] = Field(default_factory=dict)
    secret_binding_json: dict[str, Any] = Field(default_factory=dict)
    def_version_id: uuid.UUID
    change_note: str | None = None
    created_by: str | None = None


class RecipeResponse(BaseModel):
    """Response for a recipe version."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instance_id: uuid.UUID
    def_version_id: uuid.UUID
    version_no: int
    config_json: dict[str, Any]
    secret_binding_json: dict[str, Any]
    is_current: bool
    created_by: str | None
    change_note: str | None
    created_at: datetime


class RecipeDiffResponse(BaseModel):
    """Diff between two recipe versions."""

    from_version: int
    to_version: int
    config_diff: dict[str, Any]
    secret_binding_diff: dict[str, Any]


# ---------------------------------------------------------------------------
# Collector Instance
# ---------------------------------------------------------------------------


class CollectorInstanceCreate(BaseModel):
    definition_id: uuid.UUID
    name: str = Field(..., max_length=256)
    description: str | None = None
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DISABLED|ARCHIVED)$")
    initial_recipe: RecipeCreate | None = None


class CollectorInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_recipe: RecipeResponse | None = None


# ---------------------------------------------------------------------------
# Algorithm Instance
# ---------------------------------------------------------------------------


class AlgorithmInstanceCreate(BaseModel):
    definition_id: uuid.UUID
    name: str = Field(..., max_length=256)
    description: str | None = None
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DISABLED|ARCHIVED)$")
    initial_recipe: RecipeCreate | None = None


class AlgorithmInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_recipe: RecipeResponse | None = None


# ---------------------------------------------------------------------------
# Transfer Instance
# ---------------------------------------------------------------------------


class TransferInstanceCreate(BaseModel):
    definition_id: uuid.UUID
    name: str = Field(..., max_length=256)
    description: str | None = None
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DISABLED|ARCHIVED)$")
    initial_recipe: RecipeCreate | None = None


class TransferInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    name: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    current_recipe: RecipeResponse | None = None
