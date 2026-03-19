"""Hermes NiFi Integration Module.

Provides a bridge between Apache NiFi (1.9.x+) and the Hermes data processing
platform, enabling seamless management of legacy NiFi flows through Hermes's
simplified UI, per-item tracking, and Recipe system.

Key components:
- NiFiClient: Async REST API client for NiFi
- NiFiHermesBridge: Maps NiFi concepts to Hermes concepts
- NiFiFlowExecutor: Executes NiFi flows as Hermes pipeline steps
- NiFiConfig: Configuration for NiFi connectivity
"""

from hermes.infrastructure.nifi.client import NiFiClient
from hermes.infrastructure.nifi.config import NiFiConfig
from hermes.infrastructure.nifi.models import (
    Connection,
    FlowFileSummary,
    NiFiRevision,
    Parameter,
    ParameterContext,
    ProcessGroup,
    ProcessGroupStatus,
    Processor,
    ProcessorStatus,
    ProvenanceEvent,
    ProvenanceResults,
    QueueSize,
    SystemDiagnostics,
    Template,
)

__all__ = [
    "NiFiClient",
    "NiFiConfig",
    "Connection",
    "FlowFileSummary",
    "NiFiRevision",
    "Parameter",
    "ParameterContext",
    "ProcessGroup",
    "ProcessGroupStatus",
    "Processor",
    "ProcessorStatus",
    "ProvenanceEvent",
    "ProvenanceResults",
    "QueueSize",
    "SystemDiagnostics",
    "Template",
]
