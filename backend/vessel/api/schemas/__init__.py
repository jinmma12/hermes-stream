"""Pydantic schemas for Vessel API request/response models."""

from vessel.api.schemas.definition import (
    AlgorithmDefinitionCreate,
    AlgorithmDefinitionResponse,
    AlgorithmDefinitionVersionCreate,
    AlgorithmDefinitionVersionResponse,
    CollectorDefinitionCreate,
    CollectorDefinitionResponse,
    CollectorDefinitionVersionCreate,
    CollectorDefinitionVersionResponse,
    TransferDefinitionCreate,
    TransferDefinitionResponse,
    TransferDefinitionVersionCreate,
    TransferDefinitionVersionResponse,
)
from vessel.api.schemas.execution import (
    BulkReprocessRequest,
    ExecutionEventLogResponse,
    ReprocessRequestCreate,
    ReprocessRequestResponse,
    WorkItemExecutionResponse,
    WorkItemListResponse,
    WorkItemResponse,
    WorkItemStepExecutionResponse,
)
from vessel.api.schemas.instance import (
    AlgorithmInstanceCreate,
    AlgorithmInstanceResponse,
    CollectorInstanceCreate,
    CollectorInstanceResponse,
    RecipeCreate,
    RecipeDiffResponse,
    RecipeResponse,
    TransferInstanceCreate,
    TransferInstanceResponse,
)
from vessel.api.schemas.pipeline import (
    PipelineActivationResponse,
    PipelineInstanceCreate,
    PipelineInstanceResponse,
    PipelineStepCreate,
    PipelineStepResponse,
)

__all__ = [
    # Definition schemas
    "CollectorDefinitionCreate",
    "CollectorDefinitionResponse",
    "CollectorDefinitionVersionCreate",
    "CollectorDefinitionVersionResponse",
    "AlgorithmDefinitionCreate",
    "AlgorithmDefinitionResponse",
    "AlgorithmDefinitionVersionCreate",
    "AlgorithmDefinitionVersionResponse",
    "TransferDefinitionCreate",
    "TransferDefinitionResponse",
    "TransferDefinitionVersionCreate",
    "TransferDefinitionVersionResponse",
    # Instance schemas
    "CollectorInstanceCreate",
    "CollectorInstanceResponse",
    "AlgorithmInstanceCreate",
    "AlgorithmInstanceResponse",
    "TransferInstanceCreate",
    "TransferInstanceResponse",
    "RecipeCreate",
    "RecipeResponse",
    "RecipeDiffResponse",
    # Pipeline schemas
    "PipelineInstanceCreate",
    "PipelineInstanceResponse",
    "PipelineStepCreate",
    "PipelineStepResponse",
    "PipelineActivationResponse",
    # Execution schemas
    "WorkItemResponse",
    "WorkItemListResponse",
    "WorkItemExecutionResponse",
    "WorkItemStepExecutionResponse",
    "ReprocessRequestCreate",
    "ReprocessRequestResponse",
    "BulkReprocessRequest",
    "ExecutionEventLogResponse",
]
