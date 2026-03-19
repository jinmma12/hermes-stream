"""Hermes Plugin System.

NOTE: Plugin execution is handled by the .NET Engine service.
The Python reference implementations are preserved in engine/reference/plugins/.

The protocol, registry, and executor modules are kept in this package for
backward compatibility with existing tests. They will be removed once
.NET Engine plugin tests fully replace them.
"""

from hermes.plugins.executor import PluginExecutor, PluginResult
from hermes.plugins.protocol import HermesMessage, MessageType, PluginProtocol
from hermes.plugins.registry import PluginRegistry

__all__ = [
    "MessageType",
    "PluginProtocol",
    "HermesMessage",
    "PluginRegistry",
    "PluginExecutor",
    "PluginResult",
]
