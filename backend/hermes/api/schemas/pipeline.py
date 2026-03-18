"""Pydantic schemas for pipeline API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Pipeline Step
# ---------------------------------------------------------------------------


class PipelineStepCreate(BaseModel):
    step_order: int = Field(..., gt=0)
    step_type: str = Field(..., pattern=r"^(COLLECT|ALGORITHM|TRANSFER)$")
    ref_type: str = Field(..., pattern=r"^(COLLECTOR|ALGORITHM|TRANSFER)$")
    ref_id: uuid.UUID
    is_enabled: bool = True
    on_error: str = Field("STOP", pattern=r"^(STOP|SKIP|RETRY)$")
    retry_count: int = Field(0, ge=0)
    retry_delay_seconds: int = Field(0, ge=0)


class PipelineStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_instance_id: uuid.UUID
    step_order: int
    step_type: str
    ref_type: str
    ref_id: uuid.UUID
    is_enabled: bool
    on_error: str
    retry_count: int
    retry_delay_seconds: int


# ---------------------------------------------------------------------------
# Pipeline Instance
# ---------------------------------------------------------------------------


class PipelineInstanceCreate(BaseModel):
    name: str = Field(..., max_length=256)
    description: str | None = None
    monitoring_type: str | None = Field(
        None, pattern=r"^(FILE_MONITOR|API_POLL|DB_POLL|EVENT_STREAM)$"
    )
    monitoring_config: dict[str, Any] = Field(default_factory=dict)
    status: str = Field("DRAFT", pattern=r"^(DRAFT|ACTIVE|PAUSED|ARCHIVED)$")
    steps: list[PipelineStepCreate] = Field(default_factory=list)


class PipelineInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    monitoring_type: str | None
    monitoring_config: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    steps: list[PipelineStepResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline Activation
# ---------------------------------------------------------------------------


class PipelineActivationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_instance_id: uuid.UUID
    status: str
    started_at: datetime
    stopped_at: datetime | None
    last_heartbeat_at: datetime | None
    last_polled_at: datetime | None
    error_message: str | None
    worker_id: str | None
    created_at: datetime
