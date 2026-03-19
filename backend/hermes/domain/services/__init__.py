"""Domain services for Hermes Web API.

Web API services (CRUD, versioning, pipeline management):
- RecipeEngine: Definition/instance version management
- PipelineManager: Pipeline CRUD, step management, activation

Engine services (monitoring, processing, execution) have been moved to
the .NET Engine. Python reference implementations are preserved in
engine/reference/domain/services/ for development reference.

The original Python modules are kept in this package for backward
compatibility with existing tests. They will be removed once .NET
Engine tests fully replace them.
"""

# Web API services (stay in Python)
# Engine services (kept for test compatibility; canonical implementation is .NET)
# See engine/reference/ for the reference Python implementations.
from hermes.domain.services.condition_evaluator import ConditionEvaluator
from hermes.domain.services.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionResult,
)
from hermes.domain.services.monitoring_engine import (
    ApiPollMonitor,
    BaseMonitor,
    DbPollMonitor,
    FileMonitor,
    MonitoringEngine,
)
from hermes.domain.services.pipeline_manager import PipelineManager
from hermes.domain.services.processing_orchestrator import ProcessingOrchestrator
from hermes.domain.services.recipe_engine import RecipeEngine
from hermes.domain.services.snapshot_resolver import SnapshotResolver

__all__ = [
    # Web API services
    "PipelineManager",
    "RecipeEngine",
    # Engine services (test compatibility - canonical impl is .NET)
    "MonitoringEngine",
    "BaseMonitor",
    "FileMonitor",
    "ApiPollMonitor",
    "DbPollMonitor",
    "ProcessingOrchestrator",
    "SnapshotResolver",
    "ExecutionDispatcher",
    "ExecutionResult",
    "ConditionEvaluator",
]
