"""Pydantic schemas for execution layer API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Work Item Step Execution
# ---------------------------------------------------------------------------


class WorkItemStepExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    pipeline_step_id: uuid.UUID
    step_type: str
    step_order: int
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    input_summary: dict[str, Any] | None
    output_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    retry_attempt: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Work Item Execution
# ---------------------------------------------------------------------------


class WorkItemExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_item_id: uuid.UUID
    execution_no: int
    trigger_type: str
    trigger_source: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    reprocess_request_id: uuid.UUID | None
    created_at: datetime
    step_executions: list[WorkItemStepExecutionResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Work Item
# ---------------------------------------------------------------------------


class WorkItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_activation_id: uuid.UUID
    pipeline_instance_id: uuid.UUID
    source_type: str
    source_key: str
    source_metadata: dict[str, Any]
    dedup_key: str | None
    detected_at: datetime
    status: str
    current_execution_id: uuid.UUID | None
    execution_count: int
    last_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkItemListResponse(BaseModel):
    items: list[WorkItemResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# Execution Event Log
# ---------------------------------------------------------------------------


class ExecutionEventLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    step_execution_id: uuid.UUID | None
    event_type: str
    event_code: str
    message: str | None
    detail_json: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Reprocess Request
# ---------------------------------------------------------------------------


class ReprocessRequestCreate(BaseModel):
    work_item_id: uuid.UUID
    requested_by: str = Field(..., max_length=256)
    reason: str | None = None
    start_from_step: int | None = Field(None, gt=0)
    use_latest_recipe: bool = True


class ReprocessRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    work_item_id: uuid.UUID
    requested_by: str
    requested_at: datetime
    reason: str | None
    start_from_step: int | None
    use_latest_recipe: bool
    status: str
    approved_by: str | None
    execution_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class BulkReprocessRequest(BaseModel):
    """Request to reprocess multiple work items at once."""

    work_item_ids: list[uuid.UUID] = Field(..., min_length=1)
    requested_by: str = Field(..., max_length=256)
    reason: str | None = None
    start_from_step: int | None = Field(None, gt=0)
    use_latest_recipe: bool = True
