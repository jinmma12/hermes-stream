"""Vessel NiFi Integration Module.

NOTE: NiFi integration is handled by the .NET Engine service.
The Python reference implementations are preserved in engine/reference/infrastructure/nifi/.

The client, config, and model modules are kept in this package for
backward compatibility. They will be removed once .NET Engine NiFi
integration is complete.
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
