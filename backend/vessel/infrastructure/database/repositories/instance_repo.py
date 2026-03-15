"""Repository for instance layer CRUD, recipe versioning."""

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vessel.domain.models.base import Base

InstanceT = TypeVar("InstanceT", bound=Base)
VersionT = TypeVar("VersionT", bound=Base)


class InstanceRepository(Generic[InstanceT, VersionT]):
    """Generic CRUD repository for all three instance types with recipe versioning.

    Usage:
        collector_inst_repo = InstanceRepository(
            CollectorInstance, CollectorInstanceVersion,
            version_fk_attr="instance_id",
        )
    """

    def __init__(
        self,
        instance_model: type[InstanceT],
        version_model: type[VersionT],
        version_fk_attr: str = "instance_id",
    ) -> None:
        self.instance_model = instance_model
        self.version_model = version_model
        self.version_fk_attr = version_fk_attr

    # ------------------------------------------------------------------
    # Instance CRUD
    # ------------------------------------------------------------------

    async def create(self, db: AsyncSession, **kwargs: Any) -> InstanceT:
        """Create a new instance."""
        instance = self.instance_model(**kwargs)
        db.add(instance)
        await db.flush()
        return instance

    async def get_by_id(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
        *,
        with_versions: bool = False,
    ) -> InstanceT | None:
        """Get an instance by ID, optionally loading versions."""
        stmt = select(self.instance_model).where(self.instance_model.id == instance_id)  # type: ignore[attr-defined]
        if with_versions:
            stmt = stmt.options(selectinload(self.instance_model.versions))  # type: ignore[attr-defined]
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        db: AsyncSession,
        *,
        definition_id: uuid.UUID | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[InstanceT], int]:
        """List instances with optional filters."""
        stmt = select(self.instance_model)
        count_stmt = select(func.count()).select_from(self.instance_model)

        if definition_id is not None:
            stmt = stmt.where(self.instance_model.definition_id == definition_id)  # type: ignore[attr-defined]
            count_stmt = count_stmt.where(self.instance_model.definition_id == definition_id)  # type: ignore[attr-defined]
        if status is not None:
            stmt = stmt.where(self.instance_model.status == status)  # type: ignore[attr-defined]
            count_stmt = count_stmt.where(self.instance_model.status == status)  # type: ignore[attr-defined]

        stmt = stmt.order_by(self.instance_model.created_at.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]

        total = (await db.execute(count_stmt)).scalar_one()
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
        **kwargs: Any,
    ) -> InstanceT | None:
        """Update an instance's fields."""
        obj = await self.get_by_id(db, instance_id)
        if obj is None:
            return None
        for key, value in kwargs.items():
            setattr(obj, key, value)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, instance_id: uuid.UUID) -> bool:
        """Delete an instance by ID."""
        obj = await self.get_by_id(db, instance_id)
        if obj is None:
            return False
        await db.delete(obj)
        await db.flush()
        return True

    # ------------------------------------------------------------------
    # Recipe versioning
    # ------------------------------------------------------------------

    async def create_recipe(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
        *,
        def_version_id: uuid.UUID,
        config_json: dict[str, Any] | None = None,
        secret_binding_json: dict[str, Any] | None = None,
        created_by: str | None = None,
        change_note: str | None = None,
    ) -> VersionT:
        """Create a new recipe version, marking it as current and unsetting previous current."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        next_no = await self._next_version_no(db, instance_id)

        # Unset any existing is_current
        await db.execute(
            update(self.version_model)
            .where(fk_col == instance_id, self.version_model.is_current.is_(True))  # type: ignore[attr-defined]
            .values(is_current=False)
        )

        version = self.version_model(
            **{
                self.version_fk_attr: instance_id,
                "def_version_id": def_version_id,
                "version_no": next_no,
                "config_json": config_json or {},
                "secret_binding_json": secret_binding_json or {},
                "is_current": True,
                "created_by": created_by,
                "change_note": change_note,
            }
        )
        db.add(version)
        await db.flush()
        return version

    async def get_current_recipe(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
    ) -> VersionT | None:
        """Get the current (active) recipe version for an instance."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = select(self.version_model).where(
            fk_col == instance_id,
            self.version_model.is_current.is_(True),  # type: ignore[attr-defined]
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_recipe_by_version_no(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
        version_no: int,
    ) -> VersionT | None:
        """Get a specific recipe version by number."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = select(self.version_model).where(
            fk_col == instance_id,
            self.version_model.version_no == version_no,  # type: ignore[attr-defined]
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_recipes(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
    ) -> list[VersionT]:
        """List all recipe versions for an instance."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = (
            select(self.version_model)
            .where(fk_col == instance_id)
            .order_by(self.version_model.version_no)  # type: ignore[attr-defined]
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def rollback_recipe(
        self,
        db: AsyncSession,
        instance_id: uuid.UUID,
        target_version_no: int,
    ) -> VersionT | None:
        """Set a previous version as current (rollback)."""
        fk_col = getattr(self.version_model, self.version_fk_attr)

        target = await self.get_recipe_by_version_no(db, instance_id, target_version_no)
        if target is None:
            return None

        # Unset current
        await db.execute(
            update(self.version_model)
            .where(fk_col == instance_id, self.version_model.is_current.is_(True))  # type: ignore[attr-defined]
            .values(is_current=False)
        )

        target.is_current = True  # type: ignore[attr-defined]
        await db.flush()
        return target

    async def _next_version_no(self, db: AsyncSession, instance_id: uuid.UUID) -> int:
        """Calculate the next version number for an instance."""
        fk_col = getattr(self.version_model, self.version_fk_attr)
        stmt = select(func.coalesce(func.max(self.version_model.version_no), 0)).where(  # type: ignore[attr-defined]
            fk_col == instance_id
        )
        result = await db.execute(stmt)
        return result.scalar_one() + 1
