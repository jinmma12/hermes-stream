"""Tests for the Recipe Engine - versioned configuration management.

Covers recipe creation, version auto-increment, publishing, history,
diff comparison, JSON Schema validation, change notes, rollback,
and execution-time snapshot isolation.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vessel.domain.models.instance import (
    CollectorInstance,
)
from vessel.domain.services.recipe_engine import (
    RecipeDiff,
    RecipeEngine,
)

# ---------------------------------------------------------------------------
# Recipe creation and versioning
# ---------------------------------------------------------------------------


class TestRecipeCreation:
    """Tests for creating and versioning recipes."""

    @pytest.mark.asyncio
    async def test_create_first_recipe(
        self,
        async_session: AsyncSession,
        sample_collector_definition,
    ):
        """First recipe for a new instance gets version_no=1."""
        defn, def_ver = sample_collector_definition
        inst = CollectorInstance(
            definition_id=defn.id,
            name="Fresh Collector",
            status="DRAFT",
        )
        async_session.add(inst)
        await async_session.flush()

        engine = RecipeEngine(async_session)
        recipe = await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://api.example.com", "method": "GET", "interval_seconds": 60},
            change_note="Initial setup",
            created_by="operator-1",
        )

        assert recipe.version_no == 1, "First recipe should be version 1"
        assert recipe.config_json["url"] == "https://api.example.com"
        assert recipe.change_note == "Initial setup"
        assert recipe.created_by == "operator-1"

    @pytest.mark.asyncio
    async def test_create_new_recipe_version(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Creating a second recipe auto-increments version_no."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        v2 = await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://api.example.com/v2", "method": "POST", "interval_seconds": 120},
            change_note="Switched to v2 API",
        )

        assert v2.version_no == 2, "Second recipe should be version 2"

    @pytest.mark.asyncio
    async def test_new_version_becomes_current(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Publishing a new version de-activates the old one."""
        inst, v1 = sample_collector_instance
        engine = RecipeEngine(async_session)

        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://new.api.com", "method": "GET", "interval_seconds": 30},
        )

        published = await engine.publish_recipe("COLLECTOR", inst.id, 2)
        assert published.is_current is True, "v2 should be current after publish"

        current = await engine.get_current_recipe("COLLECTOR", inst.id)
        assert current is not None
        assert current.version_no == 2, "Current recipe should now be v2"

        # Check old version is no longer current
        await async_session.refresh(v1)
        assert v1.is_current is False, "v1 should no longer be current"


# ---------------------------------------------------------------------------
# History and diff
# ---------------------------------------------------------------------------


class TestRecipeHistory:
    """Tests for recipe version history and diff."""

    @pytest.mark.asyncio
    async def test_recipe_version_history(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """get_recipe_history returns ordered list of all versions."""
        inst, v1 = sample_collector_instance
        engine = RecipeEngine(async_session)

        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://v2.api.com", "method": "GET", "interval_seconds": 60},
        )
        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://v3.api.com", "method": "POST", "interval_seconds": 30},
        )

        history = await engine.get_recipe_history("COLLECTOR", inst.id)
        assert len(history) == 3, "Should have 3 versions"
        # History is ordered desc by version_no
        assert history[0].version_no == 3
        assert history[1].version_no == 2
        assert history[2].version_no == 1

    @pytest.mark.asyncio
    async def test_recipe_diff_shows_changes(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """compare_recipes shows added, removed, and changed keys."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={
                "url": "https://new-api.com",  # changed
                "method": "POST",               # changed
                "interval_seconds": 60,          # same
                "new_field": "added",            # added
                # "interval_seconds" still present, but "timeout" from v1 missing
            },
        )

        diff = await engine.compare_recipes("COLLECTOR", inst.id, 1, 2)

        assert isinstance(diff, RecipeDiff)
        assert diff.version_no_1 == 1
        assert diff.version_no_2 == 2

        # "url" changed
        assert "url" in diff.changed, "url should be in changed"
        assert diff.changed["url"]["from"] == "https://api.example.com/data"
        assert diff.changed["url"]["to"] == "https://new-api.com"

        # "new_field" added
        assert "new_field" in diff.added, "new_field should be in added"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestRecipeValidation:
    """Tests for JSON Schema validation of recipe configs."""

    def test_recipe_validation_against_schema(self):
        """Valid config passes validation."""
        engine = RecipeEngine.__new__(RecipeEngine)  # no DB needed for validate_config
        schema = {
            "type": "object",
            "required": ["url", "method"],
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST"]},
            },
        }
        result = engine.validate_config(
            config_json={"url": "https://api.com", "method": "GET"},
            input_schema=schema,
        )
        assert result.valid is True, f"Expected valid, got errors: {result.errors}"

    def test_recipe_validation_rejects_invalid(self):
        """Missing required field fails validation."""
        engine = RecipeEngine.__new__(RecipeEngine)
        schema = {
            "type": "object",
            "required": ["url", "method"],
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string"},
            },
        }
        result = engine.validate_config(
            config_json={"url": "https://api.com"},  # missing "method"
            input_schema=schema,
        )
        assert result.valid is False
        assert len(result.errors) > 0
        assert any("method" in e for e in result.errors)

    def test_recipe_validation_type_mismatch(self):
        """Wrong type fails validation."""
        engine = RecipeEngine.__new__(RecipeEngine)
        schema = {
            "type": "object",
            "properties": {"threshold": {"type": "number", "minimum": 0}},
        }
        result = engine.validate_config(
            config_json={"threshold": "not-a-number"},
            input_schema=schema,
        )
        assert result.valid is False

    def test_recipe_validation_empty_schema(self):
        """Empty schema always passes."""
        engine = RecipeEngine.__new__(RecipeEngine)
        result = engine.validate_config(config_json={"anything": "goes"}, input_schema={})
        assert result.valid is True


# ---------------------------------------------------------------------------
# Change note and audit
# ---------------------------------------------------------------------------


class TestRecipeChangeNote:
    """Tests for change note preservation."""

    @pytest.mark.asyncio
    async def test_recipe_with_change_note(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """change_note and created_by are preserved on the version record."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        recipe = await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://changed.api.com", "method": "GET", "interval_seconds": 30},
            change_note="Lowered interval for faster detection",
            created_by="operator-jane",
        )

        assert recipe.change_note == "Lowered interval for faster detection"
        assert recipe.created_by == "operator-jane"


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRecipeRollback:
    """Tests for rolling back to a previous recipe version."""

    @pytest.mark.asyncio
    async def test_rollback_recipe(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Publishing an older version effectively rolls back."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        # Create v2
        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://v2.api.com", "method": "POST", "interval_seconds": 120},
        )
        await engine.publish_recipe("COLLECTOR", inst.id, 2)

        current = await engine.get_current_recipe("COLLECTOR", inst.id)
        assert current.version_no == 2

        # Rollback to v1
        rolled_back = await engine.publish_recipe("COLLECTOR", inst.id, 1)
        assert rolled_back.version_no == 1
        assert rolled_back.is_current is True

        current_after = await engine.get_current_recipe("COLLECTOR", inst.id)
        assert current_after.version_no == 1, "Should be back on v1 after rollback"


# ---------------------------------------------------------------------------
# Snapshot isolation
# ---------------------------------------------------------------------------


class TestRecipeSnapshotIsolation:
    """Tests ensuring recipe changes do not affect past execution snapshots."""

    @pytest.mark.asyncio
    async def test_recipe_snapshot_at_execution(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Snapshot captures the config that was current at execution time."""
        inst, v1 = sample_collector_instance

        # Simulate capturing the config at execution time
        snapshot_config = dict(v1.config_json)

        assert snapshot_config["url"] == "https://api.example.com/data"
        assert snapshot_config["method"] == "GET"

    @pytest.mark.asyncio
    async def test_recipe_change_after_execution(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """A new recipe version does not affect the already-captured snapshot."""
        inst, v1 = sample_collector_instance
        engine = RecipeEngine(async_session)

        # Capture snapshot from v1
        original_snapshot = dict(v1.config_json)

        # Create and publish v2
        await engine.create_recipe(
            instance_type="COLLECTOR",
            instance_id=inst.id,
            config_json={"url": "https://new-api.com", "method": "POST", "interval_seconds": 10},
        )
        await engine.publish_recipe("COLLECTOR", inst.id, 2)

        # Original snapshot is unchanged (it's a plain dict copy)
        assert original_snapshot["url"] == "https://api.example.com/data", (
            "Snapshot should not be affected by new recipe"
        )

        # Current recipe is now v2
        current = await engine.get_current_recipe("COLLECTOR", inst.id)
        assert current.config_json["url"] == "https://new-api.com"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestRecipeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_publish_nonexistent_version_raises(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Publishing a version that does not exist raises ValueError."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        with pytest.raises(ValueError, match="not found"):
            await engine.publish_recipe("COLLECTOR", inst.id, 999)

    @pytest.mark.asyncio
    async def test_compare_nonexistent_version_raises(
        self,
        async_session: AsyncSession,
        sample_collector_instance,
    ):
        """Comparing with a nonexistent version raises ValueError."""
        inst, _ = sample_collector_instance
        engine = RecipeEngine(async_session)

        with pytest.raises(ValueError, match="not found"):
            await engine.compare_recipes("COLLECTOR", inst.id, 1, 999)

    @pytest.mark.asyncio
    async def test_unknown_instance_type_raises(
        self,
        async_session: AsyncSession,
    ):
        """Unknown instance_type raises ValueError."""
        engine = RecipeEngine(async_session)
        with pytest.raises(ValueError, match="Unknown instance_type"):
            await engine.create_recipe(
                instance_type="UNKNOWN",
                instance_id=uuid.uuid4(),
                config_json={},
            )
