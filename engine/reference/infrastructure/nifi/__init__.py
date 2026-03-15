"""Vessel NiFi Integration Module.

Provides a bridge between Apache NiFi (1.9.x+) and the Vessel data processing
platform, enabling seamless management of legacy NiFi flows through Vessel's
simplified UI, per-item tracking, and Recipe system.

Key components:
- NiFiClient: Async REST API client for NiFi
- NiFiVesselBridge: Maps NiFi concepts to Vessel concepts
- NiFiFlowExecutor: Executes NiFi flows as Vessel pipeline steps
- NiFiConfig: Configuration for NiFi connectivity
"""

from vessel.infrastructure.nifi.client import NiFiClient
from vessel.infrastructure.nifi.config import NiFiConfig
from vessel.infrastructure.nifi.models import (
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
