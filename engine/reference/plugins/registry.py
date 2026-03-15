"""Plugin Registry - Discovery and registration of Vessel plugins.

Scans plugin directories for vessel-plugin.json manifests, validates them,
and provides lookup by type and name.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "vessel-plugin.json"


class PluginType(str, Enum):
    """Categories of Vessel plugins."""

    COLLECTOR = "COLLECTOR"
    ALGORITHM = "ALGORITHM"
    TRANSFER = "TRANSFER"


@dataclass
class PluginManifest:
    """Parsed contents of a vessel-plugin.json manifest file."""

    name: str
    version: str
    type: PluginType
    description: str
    author: str
    license: str
    runtime: str
    entrypoint: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = field(default_factory=dict)
    ui_schema: dict[str, Any] = field(default_factory=dict)
    plugin_dir: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def from_dict(cls, data: dict[str, Any], plugin_dir: Path) -> PluginManifest:
        """Create a PluginManifest from a parsed JSON dict.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        required = ["name", "version", "type", "description", "runtime", "entrypoint"]
        missing = [f for f in required if f not in data]
        if missing:
            raise ValueError(
                f"Manifest missing required fields: {', '.join(missing)}"
            )

        try:
            plugin_type = PluginType(data["type"].upper())
        except ValueError:
            raise ValueError(
                f"Invalid plugin type '{data['type']}'. "
                f"Must be one of: {', '.join(t.value for t in PluginType)}"
            )

        return cls(
            name=data["name"],
            version=data["version"],
            type=plugin_type,
            description=data["description"],
            author=data.get("author", "unknown"),
            license=data.get("license", ""),
            runtime=data["runtime"],
            entrypoint=data["entrypoint"],
            input_schema=data.get("inputSchema", {}),
            output_schema=data.get("outputSchema", {}),
            ui_schema=data.get("uiSchema", {}),
            plugin_dir=plugin_dir,
        )

    @property
    def entrypoint_path(self) -> Path:
        """Full path to the plugin entrypoint file."""
        return self.plugin_dir / self.entrypoint

    @property
    def key(self) -> str:
        """Unique key for this plugin: TYPE:name."""
        return f"{self.type.value}:{self.name}"


class PluginRegistry:
    """Registry for discovering, registering, and looking up Vessel plugins.

    Plugins are identified by their (type, name) combination.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}

    def discover_plugins(self, plugins_dir: Path | str) -> list[PluginManifest]:
        """Scan a directory tree for vessel-plugin.json manifests.

        Recursively walks the directory, registering any plugin found.

        Args:
            plugins_dir: Root directory to scan.

        Returns:
            List of newly discovered and registered PluginManifest objects.
        """
        plugins_path = Path(plugins_dir)
        if not plugins_path.is_dir():
            logger.warning("Plugins directory does not exist: %s", plugins_path)
            return []

        discovered: list[PluginManifest] = []

        for manifest_path in plugins_path.rglob(MANIFEST_FILENAME):
            try:
                manifest = self._load_manifest(manifest_path)
                self.register_plugin(manifest)
                discovered.append(manifest)
                logger.info(
                    "Discovered plugin: %s (%s) at %s",
                    manifest.name,
                    manifest.type.value,
                    manifest.plugin_dir,
                )
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                logger.error(
                    "Failed to load plugin manifest %s: %s",
                    manifest_path,
                    exc,
                )

        logger.info(
            "Plugin discovery complete: %d plugins found in %s",
            len(discovered),
            plugins_path,
        )
        return discovered

    def register_plugin(self, manifest: PluginManifest) -> None:
        """Register a plugin manifest.

        If a plugin with the same (type, name) already exists, it is replaced
        with a warning.

        Args:
            manifest: The plugin manifest to register.
        """
        key = manifest.key
        if key in self._plugins:
            logger.warning(
                "Replacing already-registered plugin: %s (version %s -> %s)",
                key,
                self._plugins[key].version,
                manifest.version,
            )
        self._plugins[key] = manifest

    def get_plugin(
        self,
        plugin_type: PluginType | str,
        name: str,
    ) -> Optional[PluginManifest]:
        """Look up a plugin by type and name.

        Args:
            plugin_type: The plugin type (COLLECTOR, ALGORITHM, TRANSFER).
            name: The plugin name.

        Returns:
            The PluginManifest if found, None otherwise.
        """
        if isinstance(plugin_type, str):
            plugin_type = PluginType(plugin_type.upper())
        key = f"{plugin_type.value}:{name}"
        return self._plugins.get(key)

    def list_plugins(
        self,
        type_filter: Optional[PluginType | str] = None,
    ) -> list[PluginManifest]:
        """List all registered plugins, optionally filtered by type.

        Args:
            type_filter: If provided, only return plugins of this type.

        Returns:
            List of matching PluginManifest objects.
        """
        if type_filter is None:
            return list(self._plugins.values())

        if isinstance(type_filter, str):
            type_filter = PluginType(type_filter.upper())

        return [
            m for m in self._plugins.values() if m.type == type_filter
        ]

    def unregister_plugin(
        self,
        plugin_type: PluginType | str,
        name: str,
    ) -> bool:
        """Remove a plugin from the registry.

        Returns:
            True if the plugin was found and removed, False otherwise.
        """
        if isinstance(plugin_type, str):
            plugin_type = PluginType(plugin_type.upper())
        key = f"{plugin_type.value}:{name}"
        if key in self._plugins:
            del self._plugins[key]
            return True
        return False

    @property
    def count(self) -> int:
        """Number of registered plugins."""
        return len(self._plugins)

    @staticmethod
    def _load_manifest(manifest_path: Path) -> PluginManifest:
        """Load and parse a single vessel-plugin.json file."""
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PluginManifest.from_dict(data, plugin_dir=manifest_path.parent)
