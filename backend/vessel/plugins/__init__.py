"""Vessel Plugin System.

NOTE: Plugin execution is handled by the .NET Engine service.
The Python reference implementations are preserved in engine/reference/plugins/.

The protocol, registry, and executor modules are kept in this package for
backward compatibility with existing tests. They will be removed once
.NET Engine plugin tests fully replace them.
"""

from vessel.plugins.protocol import MessageType, PluginProtocol, VesselMessage
from vessel.plugins.registry import PluginRegistry
from vessel.plugins.executor import PluginExecutor, PluginResult

__all__ = [
    "MessageType",
    "PluginProtocol",
    "VesselMessage",
    "PluginRegistry",
    "PluginExecutor",
    "PluginResult",
]
