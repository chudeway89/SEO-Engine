"""Integration tests against a real PostgreSQL database.

Skipped automatically when ``DATABASE_URL`` does not point at a reachable
server, so the unit suite still runs anywhere.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from seo_engine.domain.models import Brand, Tenant
from seo_engine.shared.config import get_settings
from seo_engine.shared.db import Base, bind_tenant
from seo_engine.shared.errors import TenantIsolationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def engine():
    """Function-scoped: an async engine must not outlive its event loop."""
    settings = get_settings()
    eng = create_async_engine(settings.database_url, poolclass=None)
    try:
        async with eng.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncSession:
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()


async def test_every_expected_table_exists(engine) -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select table_name from information_schema.tables where table_schema = 'public'"
            )
        )
        present = {row[0] for row in rows}

    expected = set(Base.metadata.tables) | {"alembic_version"}
    missing = expected - present
    assert not missing, f"migrations are missing tables: {sorted(missing)}"


async def test_pgvector_extension_is_installed(engine) -> None:
    async with engine.connect() as conn:
        row = await conn.execute(
            sa.text("select extversion from pg_extension where extname='vector'")
        )
        assert row.scalar_one_or_none() is not None


async def test_every_tenant_owned_table_has_a_non_nullable_tenant_id() -> None:
    offenders: list[str] = []
    for name, table in Base.metadata.tables.items():
        column = table.columns.get("tenant_id")
        if column is None:
            continue
        if column.nullable:
            offenders.append(name)
    assert not offenders, f"tenant_id must be NOT NULL on: {sorted(offenders)}"


async def test_flush_guard_blocks_cross_tenant_writes(session: AsyncSession) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()

    session.add(Tenant(id=tenant_a, name="Tenant A", slug=f"a-{tenant_a.hex[:8]}"))
    session.add(Tenant(id=tenant_b, name="Tenant B", slug=f"b-{tenant_b.hex[:8]}"))
    await session.flush()

    bind_tenant(session, tenant_a)
    session.add(Brand(tenant_id=tenant_b, name="Foreign brand", slug=f"f-{uuid.uuid4().hex[:8]}"))

    with pytest.raises(TenantIsolationError):
        await session.flush()
