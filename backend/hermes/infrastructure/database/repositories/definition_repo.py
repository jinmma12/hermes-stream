"""Generic repository for definition layer CRUD and version management."""

import uuid
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vessel.domain.models.base import Base

DefinitionT = TypeVar("DefinitionT", bound=Base)
VersionT = TypeVar("VersionT", bound=Base)


class DefinitionRepository[DefinitionT: Base, VersionT: Base]:
    """Generic CRUD repository for all three definition types.

    Usage:
        collector_repo = DefinitionRepository(
            CollectorDefinition, CollectorDefinitionVersion,
            version_fk_attr="definition_id",
        )
    """

    def __init__(
        self,
        definition_model: type[DefinitionT],
        version_model: type[VersionT],
        version_fk_attr: str = "definition_id",
    ) -> None:
        self.definition_model = definition_model
        self.version_model = version_model
        self.version_fk_attr = version_fk_attr

    # ------------------------------------------------------------------
    # Definition CRUD
    # ------------------------------------------------------------------

    async def create(self, db: AsyncSession, **kwargs: Any) -> DefinitionT:
        """Create a new definition."""
        instance = self.definition_model(**kwargs)
        db.add(instance)
        await db.flush()
        return instance

    async def get_by_id(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        *,
        with_versions: bool = False,
    ) -> DefinitionT | None:
        """Get a definition by ID, optionally loading versions."""
        stmt = select(self.definition_model).where(self.definition_model.id == definition_id)  # type: ignore[attr-defined]
        if with_versions:
            stmt = stmt.options(selectinload(self.definition_model.versions))  # type: ignore[attr-defined]
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, db: AsyncSession, code: str) -> DefinitionT | None:
        """Get a definition by unique code."""
        stmt = select(self.definition_model).where(self.definition_model.code == code)  # type: ignore[attr-defined]
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        db: AsyncSession,
        *,
        status: str | None = None,
        category: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[DefinitionT], int]:
        """List definitions with optional filters, returning (items, total_count)."""
        stmt = select(self.definition_model)
        count_stmt = select(func.count()).select_from(self.definition_model)

        if status is not None:
            stmt = stmt.where(self.definition_model.status == status)  # type: ignore[attr-defined]
            count_stmt = count_stmt.where(self.definition_model.status == status)  # type: ignore[attr-defined]
        if category is not None:
            stmt = stmt.where(self.definition_model.category == category)  # type: ignore[attr-defined]
            count_stmt = count_stmt.where(self.definition_model.category == category)  # type: ignore[attr-defined]

        stmt = stmt.order_by(self.definition_model.created_at.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]

        total = (await db.execute(count_stmt)).scalar_one()
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        **kwargs: Any,
    ) -> DefinitionT | None:
        """Update a definition's fields."""
        obj = await self.get_by_id(db, definition_id)
        if obj is None:
            return None
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, definition_id: uuid.UUID) -> bool:
        """Delete a definition by ID. Returns True if deleted."""
        obj = await self.get_by_id(db, definition_id)
        if obj is None:
            return False
        await db.delete(obj)
        await db.flush()
        return True

    # ------------------------------------------------------------------
    # Version management
    # ------------------------------------------------------------------

    async def create_version(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
        **kwargs: Any,
    ) -> VersionT:
        """Create a new version for a definition. Auto-increments version_no."""
        next_no = await self._next_version_no(db, definition_id)
        version = self.version_model(
            **{self.version_fk_attr: definition_id, "version_no": next_no, **kwargs}
        )
        db.add(version)
        await db.flush()
        return version

    async def get_version(
        self,
        db: AsyncSession,
        version_id: uuid.UUID,
    ) -> VersionT | None:
        """Get a specific version by ID."""
        stmt = select(self.version_model).where(self.version_model.id == version_id)  # type: ignore[attr-defined]
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_versions(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
    ) -> list[VersionT]:
        """List all versions for a definition, ordered by version_no."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = (
            select(self.version_model)
            .where(fk_col == definition_id)
            .order_by(self.version_model.version_no)  # type: ignore[attr-defined]
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_published_version(
        self,
        db: AsyncSession,
        definition_id: uuid.UUID,
    ) -> VersionT | None:
        """Get the latest published version for a definition."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = (
            select(self.version_model)
            .where(fk_col == definition_id, self.version_model.is_published.is_(True))  # type: ignore[attr-defined]
            .order_by(self.version_model.version_no.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _next_version_no(self, db: AsyncSession, definition_id: uuid.UUID) -> int:
        """Calculate the next version number for a definition."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = select(func.coalesce(func.max(self.version_model.version_no), 0)).where(  # type: ignore[attr-defined]
            fk_col == definition_id
        )
        result = await db.execute(stmt)
        return result.scalar_one() + 1
