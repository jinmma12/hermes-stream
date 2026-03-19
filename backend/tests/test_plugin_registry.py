"""Tests for the Plugin Registry - discovery, registration, and lookup.

Covers directory scanning, manifest validation, lookup by type+name,
type filtering, duplicate handling, and graceful not-found behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.plugins.registry import (
    MANIFEST_FILENAME,
    PluginManifest,
    PluginRegistry,
    PluginType,
)

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestPluginDiscovery:
    """Tests for discover_plugins_in_directory."""

    def test_discover_plugins_in_directory(self, tmp_path: Path):
        """Registry finds all hermes-plugin.json files recursively."""
        for name in ("plugin-a", "plugin-b", "nested/plugin-c"):
            plugin_dir = tmp_path / name
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "main.py").write_text("# entrypoint\n")
            manifest = {
                "name": name.replace("nested/", ""),
                "version": "1.0.0",
                "type": "COLLECTOR",
                "description": f"Test plugin {name}",
                "runtime": "python3",
                "entrypoint": "main.py",
            }
            (plugin_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest))

        registry = PluginRegistry()
        discovered = registry.discover_plugins(tmp_path)

        assert len(discovered) == 3, "Should discover all 3 plugins"
        assert registry.count == 3

    def test_discover_in_nonexistent_directory(self, tmp_path: Path):
        """Discovering in a missing directory returns empty list, no crash."""
        registry = PluginRegistry()
        result = registry.discover_plugins(tmp_path / "does-not-exist")
        assert result == []

    def test_discover_skips_invalid_manifests(self, tmp_path: Path):
        """Invalid manifests are skipped without stopping discovery."""
        # Valid plugin
        valid_dir = tmp_path / "valid-plugin"
        valid_dir.mkdir()
        (valid_dir / "main.py").write_text("# ok\n")
        (valid_dir / MANIFEST_FILENAME).write_text(json.dumps({
            "name": "valid",
            "version": "1.0.0",
            "type": "COLLECTOR",
            "description": "ok",
            "runtime": "python3",
            "entrypoint": "main.py",
        }))

        # Invalid plugin (missing required fields)
        invalid_dir = tmp_path / "bad-plugin"
        invalid_dir.mkdir()
        (invalid_dir / MANIFEST_FILENAME).write_text(json.dumps({"name": "bad"}))

        registry = PluginRegistry()
        discovered = registry.discover_plugins(tmp_path)
        assert len(discovered) == 1, "Only valid plugin should be registered"
        assert discovered[0].name == "valid"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    """Tests for registering and looking up plugins."""

    def test_register_plugin_with_valid_manifest(self, make_manifest):
        """A valid manifest can be registered and looked up."""
        manifest, _ = make_manifest(name="my-collector", plugin_type="COLLECTOR")
        registry = PluginRegistry()
        registry.register_plugin(manifest)

        assert registry.count == 1
        found = registry.get_plugin(PluginType.COLLECTOR, "my-collector")
        assert found is not None
        assert found.name == "my-collector"

    def test_reject_invalid_manifest_missing_required(self):
        """PluginManifest.from_dict raises ValueError on missing required fields."""
        with pytest.raises(ValueError, match="missing required fields"):
            PluginManifest.from_dict(
                {"name": "incomplete"},
                plugin_dir=Path("."),
            )

    def test_reject_invalid_manifest_bad_type(self):
        """PluginManifest.from_dict raises ValueError on invalid plugin type."""
        data = {
            "name": "bad-type",
            "version": "1.0.0",
            "type": "INVALID_TYPE",
            "description": "nope",
            "runtime": "python3",
            "entrypoint": "main.py",
        }
        with pytest.raises(ValueError, match="Invalid plugin type"):
            PluginManifest.from_dict(data, plugin_dir=Path("."))

    def test_get_plugin_by_type_and_name(self, plugin_registry: PluginRegistry):
        """get_plugin returns the correct manifest for a known (type, name)."""
        result = plugin_registry.get_plugin("COLLECTOR", "rest-api-collector")
        assert result is not None
        assert result.name == "rest-api-collector"
        assert result.type == PluginType.COLLECTOR

    def test_list_plugins_by_type_filter(self, plugin_registry: PluginRegistry):
        """list_plugins with type_filter returns only matching plugins."""
        collectors = plugin_registry.list_plugins(type_filter="COLLECTOR")
        assert len(collectors) == 1
        assert collectors[0].type == PluginType.COLLECTOR

        all_plugins = plugin_registry.list_plugins()
        assert len(all_plugins) == 3

    def test_plugin_manifest_schema_validation(self, make_manifest):
        """inputSchema in a valid manifest is preserved as a dict."""
        schema = {
            "type": "object",
            "required": ["url"],
            "properties": {"url": {"type": "string"}},
        }
        manifest, _ = make_manifest(
            name="schema-plugin", input_schema=schema
        )
        assert manifest.input_schema == schema

    def test_duplicate_plugin_registration(self, make_manifest):
        """Registering the same (type, name) replaces the old entry with a warning."""
        m1, _ = make_manifest(name="dup-plugin", plugin_type="COLLECTOR")
        m2, _ = make_manifest(name="dup-plugin", plugin_type="COLLECTOR")
        m2 = PluginManifest(
            name="dup-plugin",
            version="2.0.0",
            type=PluginType.COLLECTOR,
            description="updated",
            author="test",
            license="MIT",
            runtime="python3",
            entrypoint="main.py",
            input_schema={},
            plugin_dir=m2[1] if isinstance(m2, tuple) else Path("."),
        )

        registry = PluginRegistry()
        registry.register_plugin(m1)
        assert registry.count == 1

        registry.register_plugin(m2)
        assert registry.count == 1, "Duplicate should replace, not add"

        found = registry.get_plugin("COLLECTOR", "dup-plugin")
        assert found is not None
        assert found.version == "2.0.0", "Should have the newer version"

    def test_plugin_not_found(self, plugin_registry: PluginRegistry):
        """get_plugin returns None for unknown (type, name)."""
        result = plugin_registry.get_plugin("COLLECTOR", "nonexistent-plugin")
        assert result is None, "Non-existent plugin should return None"

    def test_unregister_plugin(self, plugin_registry: PluginRegistry):
        """unregister_plugin removes a known plugin and returns True."""
        removed = plugin_registry.unregister_plugin("COLLECTOR", "rest-api-collector")
        assert removed is True
        assert plugin_registry.get_plugin("COLLECTOR", "rest-api-collector") is None

    def test_unregister_unknown_returns_false(self, plugin_registry: PluginRegistry):
        """unregister_plugin returns False for unknown plugins."""
        removed = plugin_registry.unregister_plugin("COLLECTOR", "no-such-plugin")
        assert removed is False

    def test_manifest_key_property(self):
        """PluginManifest.key returns TYPE:name."""
        m = PluginManifest(
            name="my-algo",
            version="1.0.0",
            type=PluginType.ALGORITHM,
            description="test",
            author="a",
            license="MIT",
            runtime="python3",
            entrypoint="main.py",
            input_schema={},
        )
        assert m.key == "ALGORITHM:my-algo"

    def test_manifest_entrypoint_path(self, tmp_path: Path):
        """PluginManifest.entrypoint_path computes the full path."""
        m = PluginManifest(
            name="ep-test",
            version="1.0.0",
            type=PluginType.TRANSFER,
            description="test",
            author="a",
            license="MIT",
            runtime="python3",
            entrypoint="run.py",
            input_schema={},
            plugin_dir=tmp_path / "ep-test",
        )
        assert m.entrypoint_path == tmp_path / "ep-test" / "run.py"
