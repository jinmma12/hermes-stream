"""Pydantic schemas for definition layer API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Collector Definition
# ---------------------------------------------------------------------------


class CollectorDefinitionCreate(BaseModel):
    code: str = Field(..., max_length=128)
    name: str = Field(..., max_length=256)
    description: str | None = None
    category: str | None = Field(None, max_length=128)
    icon_url: str | None = Field(None, max_length=512)
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DEPRECATED|ARCHIVED)$")


class CollectorDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str | None
    icon_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CollectorDefinitionVersionCreate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    execution_type: str = Field(..., pattern=r"^(PLUGIN|SCRIPT|HTTP|DOCKER|NIFI_FLOW)$")
    execution_ref: str | None = Field(None, max_length=512)
    is_published: bool = False


class CollectorDefinitionVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    version_no: int
    input_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    output_schema: dict[str, Any]
    default_config: dict[str, Any]
    execution_type: str
    execution_ref: str | None
    is_published: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Algorithm Definition
# ---------------------------------------------------------------------------


class AlgorithmDefinitionCreate(BaseModel):
    code: str = Field(..., max_length=128)
    name: str = Field(..., max_length=256)
    description: str | None = None
    category: str | None = Field(None, max_length=128)
    icon_url: str | None = Field(None, max_length=512)
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DEPRECATED|ARCHIVED)$")


class AlgorithmDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str | None
    icon_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class AlgorithmDefinitionVersionCreate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    execution_type: str = Field(..., pattern=r"^(PLUGIN|SCRIPT|HTTP|DOCKER|NIFI_FLOW)$")
    execution_ref: str | None = Field(None, max_length=512)
    is_published: bool = False


class AlgorithmDefinitionVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    version_no: int
    input_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    output_schema: dict[str, Any]
    default_config: dict[str, Any]
    execution_type: str
    execution_ref: str | None
    is_published: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Transfer Definition
# ---------------------------------------------------------------------------


class TransferDefinitionCreate(BaseModel):
    code: str = Field(..., max_length=128)
    name: str = Field(..., max_length=256)
    description: str | None = None
    category: str | None = Field(None, max_length=128)
    icon_url: str | None = Field(None, max_length=512)
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|DEPRECATED|ARCHIVED)$")


class TransferDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str | None
    icon_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class TransferDefinitionVersionCreate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    execution_type: str = Field(..., pattern=r"^(PLUGIN|SCRIPT|HTTP|DOCKER|NIFI_FLOW)$")
    execution_ref: str | None = Field(None, max_length=512)
    is_published: bool = False


class TransferDefinitionVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    definition_id: uuid.UUID
    version_no: int
    input_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    output_schema: dict[str, Any]
    default_config: dict[str, Any]
    execution_type: str
    execution_ref: str | None
    is_published: bool
    created_at: datetime
