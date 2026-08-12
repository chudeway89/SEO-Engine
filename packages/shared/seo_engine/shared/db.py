"""Database engine, session management and the tenant-scoped base classes.

Tenant isolation is enforced structurally, not by convention:

* every tenant-owned table inherits :class:`TenantOwnedMixin` which makes
  ``tenant_id`` non-nullable and indexed;
* all reads and writes go through
  :class:`seo_engine.domain.repositories.TenantScopedRepository`, which injects
  ``WHERE tenant_id = :tenant`` into every statement it issues;
* a defensive ``before_flush`` hook rejects any object whose ``tenant_id`` was
  mutated to a different tenant inside a session bound to a tenant context.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from seo_engine.shared.config import get_settings
from sqlalchemy import DateTime, MetaData, String, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[str]: JSONB,
        list[dict[str, Any]]: JSONB,
    }

    def as_dict(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantOwnedMixin:
    """Marks a table as tenant-owned.  ``tenant_id`` is mandatory and indexed."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)


class SyntheticDataMixin:
    """Marks rows that are demo/seed data so the UI can label them honestly."""

    is_synthetic: Mapped[bool] = mapped_column(default=False, nullable=False)
    data_label: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, autoflush=False
        )
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope.  Commits on success, rolls back on any exception."""
    maker = get_sessionmaker()
    session = maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Defensive tenant guard
# ---------------------------------------------------------------------------
TENANT_CONTEXT_KEY = "seo_engine_tenant_id"


def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Pin a session to one tenant so the flush guard can police writes."""
    session.info[TENANT_CONTEXT_KEY] = tenant_id


def bound_tenant(session: AsyncSession) -> uuid.UUID | None:
    return session.info.get(TENANT_CONTEXT_KEY)


@event.listens_for(AsyncSession.sync_session_class, "before_flush")
def _guard_tenant_on_flush(session: Any, flush_context: Any, instances: Any) -> None:
    from seo_engine.shared.errors import TenantIsolationError

    tenant_id = session.info.get(TENANT_CONTEXT_KEY)
    if tenant_id is None:
        return
    for obj in list(session.new) + list(session.dirty):
        obj_tenant = getattr(obj, "tenant_id", None)
        if obj_tenant is None:
            continue
        if obj_tenant != tenant_id:
            raise TenantIsolationError(
                "attempted to write a record belonging to a different tenant",
                {
                    "entity": type(obj).__name__,
                    "session_tenant": str(tenant_id),
                    "record_tenant": str(obj_tenant),
                },
            )


__all__ = [
    "Base",
    "SyntheticDataMixin",
    "TenantOwnedMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "bind_tenant",
    "bound_tenant",
    "dispose_engine",
    "get_engine",
    "get_sessionmaker",
    "session_scope",
]
