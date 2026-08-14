"""Shared pytest configuration and database fixtures."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from seo_engine.domain.models.identity import Tenant, TenantUser, User
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import Role
from seo_engine.shared.config import override_settings, reset_settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(scope="session", autouse=True)
def _test_settings() -> None:
    override_settings(
        environment="test",
        jwt_secret="test-secret-not-for-production",
        llm_provider="deterministic",
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/seo_engine",
        ),
    )
    yield
    reset_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def engine():
    """Function-scoped: an async engine must not outlive its event loop."""
    from seo_engine.shared.config import get_settings

    eng = create_async_engine(get_settings().database_url, poolclass=None)
    try:
        async with eng.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment dependent
        await eng.dispose()
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session that is always rolled back, so tests never leave residue."""
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with maker() as sess:
        try:
            yield sess
        finally:
            await sess.rollback()


@pytest.fixture
async def second_session(engine) -> AsyncIterator[AsyncSession]:
    """A second independent session, for cross-tenant isolation tests."""
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with maker() as sess:
        try:
            yield sess
        finally:
            await sess.rollback()


async def make_tenant(session: AsyncSession, label: str = "acme") -> tuple[Tenant, User, Principal]:
    """Create a tenant, an owner user and the matching principal."""
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name=f"{label.title()} Ltd", slug=f"{label}-{suffix}")
    user = User(email=f"owner-{suffix}@{label}.test", name="Owner", status="active")
    session.add_all([tenant, user])
    await session.flush()
    session.add(TenantUser(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER, is_default=True))
    await session.flush()
    principal = Principal.build(
        user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.OWNER
    )
    return tenant, user, principal


@pytest.fixture
async def tenant_ctx(session: AsyncSession):
    return await make_tenant(session)
