"""SQL-level migration tests for stage_runtime_states.

These tests go beyond ORM create_all by:
1. Creating the base schema without stage_runtime_states
2. Applying the migration SQL
3. Verifying constraints at the DB level

Uses raw SQL to simulate a real migration path.
SQLite limitations: no COMMENT ON, no TIMESTAMPTZ (mapped to TEXT).
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hermes.domain.models.base import Base

TIMEOUT = 15

# SQLite-compatible version of the migration SQL
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS stage_runtime_states (
    id TEXT PRIMARY KEY,
    pipeline_activation_id TEXT NOT NULL REFERENCES pipeline_activations(id) ON DELETE CASCADE,
    pipeline_step_id TEXT NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    runtime_status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    stopped_at TEXT,
    stopped_by VARCHAR(256),
    resumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    CONSTRAINT uq_stage_runtime_activation_step UNIQUE (pipeline_activation_id, pipeline_step_id)
);
"""


@pytest.fixture
async def migration_engine():
    """Create a fresh engine, apply base schema WITHOUT stage_runtime_states,
    then apply migration SQL to simulate a real migration path."""
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB

    # Remap JSONB for SQLite
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Create all tables EXCEPT stage_runtime_states (simulating pre-migration state)
    async with engine.begin() as conn:
        # Create all tables first
        await conn.run_sync(Base.metadata.create_all)
        # Drop stage_runtime_states to simulate pre-migration
        await conn.execute(text("DROP TABLE IF EXISTS stage_runtime_states"))

    yield engine

    await engine.dispose()


@pytest.fixture
async def migration_session(migration_engine):
    """Session on the pre-migration engine."""
    factory = async_sessionmaker(
        bind=migration_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with factory() as session:
        yield session


@pytest.mark.asyncio
async def test_migration_sql_creates_table(migration_engine):
    """Applying migration SQL creates the stage_runtime_states table."""
    async def _run():
        from sqlalchemy import inspect

        # Before migration: table should not exist
        async with migration_engine.connect() as conn:
            tables_before = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert "stage_runtime_states" not in tables_before

        # Apply migration
        async with migration_engine.begin() as conn:
            await conn.execute(text(MIGRATION_SQL))

        # After migration: table should exist
        async with migration_engine.connect() as conn:
            tables_after = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
        assert "stage_runtime_states" in tables_after

    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_unique_constraint_rejects_duplicate_at_db_level(migration_engine):
    """The unique constraint must reject duplicate (activation_id, step_id) at DB level."""
    async def _run():
        # Apply migration
        async with migration_engine.begin() as conn:
            await conn.execute(text(MIGRATION_SQL))

        # First we need an activation and step in the DB
        # Insert minimal parent rows
        act_id = str(uuid.uuid4())
        pipe_id = str(uuid.uuid4())
        step_id = str(uuid.uuid4())

        async with migration_engine.begin() as conn:
            # Insert pipeline_instance
            await conn.execute(text(
                "INSERT INTO pipeline_instances (id, name, monitoring_type, monitoring_config, status, created_at, updated_at) "
                "VALUES (:id, 'test', 'FILE_MONITOR', '{}', 'ACTIVE', datetime('now'), datetime('now'))"
            ), {"id": pipe_id})

            # Insert pipeline_step
            await conn.execute(text(
                "INSERT INTO pipeline_steps (id, pipeline_instance_id, step_order, step_type, ref_type, ref_id) "
                "VALUES (:id, :pipe_id, 1, 'COLLECT', 'COLLECTOR', :ref_id)"
            ), {"id": step_id, "pipe_id": pipe_id, "ref_id": str(uuid.uuid4())})

            # Insert activation
            await conn.execute(text(
                "INSERT INTO pipeline_activations (id, pipeline_instance_id, status, started_at, last_heartbeat_at) "
                "VALUES (:id, :pipe_id, 'RUNNING', datetime('now'), datetime('now'))"
            ), {"id": act_id, "pipe_id": pipe_id})

        # First insert: should succeed
        state_id1 = str(uuid.uuid4())
        async with migration_engine.begin() as conn:
            await conn.execute(text(
                "INSERT INTO stage_runtime_states (id, pipeline_activation_id, pipeline_step_id, runtime_status) "
                "VALUES (:id, :act_id, :step_id, 'RUNNING')"
            ), {"id": state_id1, "act_id": act_id, "step_id": step_id})

        # Second insert with same (activation, step): must fail
        state_id2 = str(uuid.uuid4())
        with pytest.raises(IntegrityError):
            async with migration_engine.begin() as conn:
                await conn.execute(text(
                    "INSERT INTO stage_runtime_states (id, pipeline_activation_id, pipeline_step_id, runtime_status) "
                    "VALUES (:id, :act_id, :step_id, 'STOPPED')"
                ), {"id": state_id2, "act_id": act_id, "step_id": step_id})

    await asyncio.wait_for(_run(), timeout=TIMEOUT)


@pytest.mark.asyncio
async def test_fk_rejects_orphan_state(migration_engine):
    """FK constraint must reject stage_runtime_state with nonexistent activation."""
    async def _run():
        async with migration_engine.begin() as conn:
            await conn.execute(text(MIGRATION_SQL))
            # Enable FK enforcement for SQLite
            await conn.execute(text("PRAGMA foreign_keys = ON"))

        fake_act = str(uuid.uuid4())
        fake_step = str(uuid.uuid4())
        state_id = str(uuid.uuid4())

        with pytest.raises(IntegrityError):
            async with migration_engine.begin() as conn:
                await conn.execute(text("PRAGMA foreign_keys = ON"))
                await conn.execute(text(
                    "INSERT INTO stage_runtime_states (id, pipeline_activation_id, pipeline_step_id, runtime_status) "
                    "VALUES (:id, :act_id, :step_id, 'RUNNING')"
                ), {"id": state_id, "act_id": fake_act, "step_id": fake_step})

    await asyncio.wait_for(_run(), timeout=TIMEOUT)
