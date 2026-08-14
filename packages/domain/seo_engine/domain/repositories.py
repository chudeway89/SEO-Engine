"""Tenant-scoped data access.

This is the only sanctioned route to the database for application code.  Its one
job is to make it *impossible* to forget the tenant predicate:

* :class:`TenantScopedRepository` injects ``WHERE tenant_id = :tenant`` into
  every statement it issues, including updates and deletes;
* it refuses to accept a pre-built statement that already mentions another
  tenant;
* the session it works on is bound to the tenant, so the ``before_flush`` guard
  in ``seo_engine.shared.db`` catches anything that slips past.

Rule 10 is therefore enforced in three independent places, and the security
tests assert each one separately.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from seo_engine.shared.db import Base, bind_tenant, bound_tenant
from seo_engine.shared.errors import NotFoundError, TenantIsolationError, ValidationError
from sqlalchemy import Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

ModelT = TypeVar("ModelT", bound=Base)


class TenantScopedRepository(Generic[ModelT]):
    """Base repository.  Every query is scoped to exactly one tenant."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        if tenant_id is None:  # pragma: no cover - defensive
            raise ValidationError("a tenant_id is required to open a repository")
        self.session = session
        self.tenant_id = tenant_id
        existing = bound_tenant(session)
        if existing is not None and existing != tenant_id:
            raise TenantIsolationError(
                "session is already bound to a different tenant",
                {"session_tenant": str(existing), "requested_tenant": str(tenant_id)},
            )
        bind_tenant(session, tenant_id)

    # -- statement construction ----------------------------------------
    @property
    def _tenant_column(self) -> Any:
        column = getattr(self.model, "tenant_id", None)
        if column is None:  # pragma: no cover - guarded by a schema test
            raise TenantIsolationError(
                f"{self.model.__name__} is not tenant-owned and cannot be used "
                "with a tenant-scoped repository",
                {"model": self.model.__name__},
            )
        return column

    def select(self) -> Select[tuple[ModelT]]:
        """A SELECT already narrowed to this tenant."""
        return select(self.model).where(self._tenant_column == self.tenant_id)

    def scoped(self, statement: Select[Any]) -> Select[Any]:
        """Narrow a caller-built SELECT to this tenant."""
        return statement.where(self._tenant_column == self.tenant_id)

    # -- reads -----------------------------------------------------------
    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(self.select().where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def get_or_raise(self, entity_id: uuid.UUID) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            # Deliberately indistinguishable from "exists in another tenant".
            raise NotFoundError(
                f"{self.model.__name__} not found",
                {"id": str(entity_id), "type": self.model.__name__},
            )
        return entity

    async def list(
        self,
        *criteria: Any,
        limit: int | None = None,
        offset: int = 0,
        order_by: Any = None,
    ) -> Sequence[ModelT]:
        statement = self.select()
        if criteria:
            statement = statement.where(*criteria)
        if order_by is not None:
            statement = statement.order_by(order_by)
        if offset:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def count(self, *criteria: Any) -> int:
        statement = (
            select(func.count())
            .select_from(self.model)
            .where(self._tenant_column == self.tenant_id)
        )
        if criteria:
            statement = statement.where(*criteria)
        result = await self.session.execute(statement)
        return int(result.scalar_one())

    async def find_one(self, *criteria: Any) -> ModelT | None:
        result = await self.session.execute(self.select().where(*criteria).limit(1))
        return result.scalar_one_or_none()

    async def exists(self, *criteria: Any) -> bool:
        return await self.find_one(*criteria) is not None

    # -- writes ----------------------------------------------------------
    def add(self, entity: ModelT) -> ModelT:
        """Attach a new row, forcing this repository's tenant onto it."""
        current = getattr(entity, "tenant_id", None)
        if current is not None and current != self.tenant_id:
            raise TenantIsolationError(
                "cannot persist a record belonging to a different tenant",
                {
                    "model": self.model.__name__,
                    "repository_tenant": str(self.tenant_id),
                    "record_tenant": str(current),
                },
            )
        entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        return entity

    def add_all(self, entities: Sequence[ModelT]) -> Sequence[ModelT]:
        for entity in entities:
            self.add(entity)
        return entities

    async def update_where(self, criteria: Sequence[Any], values: dict[str, Any]) -> int:
        if "tenant_id" in values:
            raise TenantIsolationError(
                "tenant_id may not be reassigned through an update",
                {"model": self.model.__name__},
            )
        statement = (
            update(self.model)
            .where(self._tenant_column == self.tenant_id, *criteria)
            .values(**values)
        )
        result = await self.session.execute(statement)
        return int(result.rowcount or 0)

    async def delete_where(self, *criteria: Any) -> int:
        statement = delete(self.model).where(self._tenant_column == self.tenant_id, *criteria)
        result = await self.session.execute(statement)
        return int(result.rowcount or 0)

    async def delete(self, entity: ModelT) -> None:
        if getattr(entity, "tenant_id", None) != self.tenant_id:
            raise TenantIsolationError(
                "cannot delete a record belonging to a different tenant",
                {"model": self.model.__name__},
            )
        await self.session.delete(entity)

    async def flush(self) -> None:
        await self.session.flush()


class PlatformRepository(Generic[ModelT]):
    """For genuinely tenant-independent catalogues (roles, plans, agents).

    Kept as a separate type so that "this table has no tenant_id" is an explicit,
    reviewable decision rather than an omission.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        if hasattr(self.model, "tenant_id"):  # pragma: no cover - defensive
            raise TenantIsolationError(
                f"{self.model.__name__} is tenant-owned; use TenantScopedRepository",
                {"model": self.model.__name__},
            )

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(select(self.model).where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def find_one(self, *criteria: Any) -> ModelT | None:
        result = await self.session.execute(select(self.model).where(*criteria).limit(1))
        return result.scalar_one_or_none()

    async def list(self, *criteria: Any, order_by: Any = None) -> Sequence[ModelT]:
        statement = select(self.model)
        if criteria:
            statement = statement.where(*criteria)
        if order_by is not None:
            statement = statement.order_by(order_by)
        result = await self.session.execute(statement)
        return result.scalars().all()

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    async def flush(self) -> None:
        await self.session.flush()


def repository_for(model: type[ModelT]) -> type[TenantScopedRepository[ModelT]]:
    """Build a concrete tenant-scoped repository class for ``model``."""
    return type(  # type: ignore[return-value]
        f"{model.__name__}Repository",
        (TenantScopedRepository,),
        {"model": model},
    )


__all__ = ["PlatformRepository", "TenantScopedRepository", "repository_for"]
