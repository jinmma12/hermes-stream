"""Vessel Plugin System.

Provides plugin discovery, registration, and subprocess-based execution
using a language-agnostic JSON line protocol over stdin/stdout.
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
