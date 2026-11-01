"""Cross-tenant isolation tests.

Rule 10: a tenant must never retrieve another tenant's data, memory,
credentials, recommendations, analytics, content or actions.  Isolation is
enforced in three independent layers (ADR-0005) and each is asserted separately
here, so a regression in one layer cannot hide behind another.
"""

from __future__ import annotations

import uuid

import pytest
from seo_engine.domain.models.brand import Brand
from seo_engine.domain.models.decision import Recommendation
from seo_engine.domain.models.memory import Memory
from seo_engine.domain.repositories import repository_for
from seo_engine.domain.services import BrandService
from seo_engine.shared.errors import NotFoundError, TenantIsolationError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_tenant

pytestmark = [pytest.mark.security, pytest.mark.integration]

BrandRepo = repository_for(Brand)
MemoryRepo = repository_for(Memory)
RecommendationRepo = repository_for(Recommendation)


async def test_repository_select_never_returns_another_tenants_row(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    BrandRepo(session, alice.tenant_id).add(
        Brand(name="Alice Brand", slug=f"a{uuid.uuid4().hex[:6]}")
    )
    BrandRepo(second_session, bob.tenant_id).add(
        Brand(name="Bob Brand", slug=f"b{uuid.uuid4().hex[:6]}")
    )
    await session.flush()
    await second_session.flush()

    alice_brands = await BrandRepo(session, alice.tenant_id).list()
    assert {b.name for b in alice_brands} == {"Alice Brand"}


async def test_get_by_id_across_tenants_reports_not_found_not_forbidden(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    """A 403 would confirm the resource exists.  404 leaks nothing."""
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    bob_brand = BrandRepo(second_session, bob.tenant_id).add(
        Brand(name="Bob Brand", slug=f"b{uuid.uuid4().hex[:6]}")
    )
    await second_session.commit()

    try:
        with pytest.raises(NotFoundError) as excinfo:
            await BrandRepo(session, alice.tenant_id).get_or_raise(bob_brand.id)
        assert excinfo.value.http_status == 404
    finally:
        await second_session.delete(bob_brand)
        await second_session.commit()


async def test_repository_refuses_to_write_a_foreign_tenant_row(session: AsyncSession) -> None:
    _, _, alice = await make_tenant(session, "alice")
    foreign = uuid.uuid4()
    with pytest.raises(TenantIsolationError):
        BrandRepo(session, alice.tenant_id).add(
            Brand(tenant_id=foreign, name="Foreign", slug=f"f{uuid.uuid4().hex[:6]}")
        )


async def test_repository_forces_its_own_tenant_onto_new_rows(session: AsyncSession) -> None:
    _, _, alice = await make_tenant(session, "alice")
    brand = BrandRepo(session, alice.tenant_id).add(
        Brand(name="No tenant set", slug=f"n{uuid.uuid4().hex[:6]}")
    )
    assert brand.tenant_id == alice.tenant_id


async def test_a_session_cannot_be_rebound_to_a_second_tenant(session: AsyncSession) -> None:
    _, _, alice = await make_tenant(session, "alice")
    BrandRepo(session, alice.tenant_id)
    with pytest.raises(TenantIsolationError, match="already bound"):
        BrandRepo(session, uuid.uuid4())


async def test_tenant_id_cannot_be_reassigned_by_update(session: AsyncSession) -> None:
    _, _, alice = await make_tenant(session, "alice")
    repo = BrandRepo(session, alice.tenant_id)
    repo.add(Brand(name="Alice", slug=f"a{uuid.uuid4().hex[:6]}"))
    await session.flush()
    with pytest.raises(TenantIsolationError, match="may not be reassigned"):
        await repo.update_where([], {"tenant_id": uuid.uuid4()})


async def test_delete_where_only_touches_the_callers_tenant(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    BrandRepo(session, alice.tenant_id).add(Brand(name="A", slug=f"a{uuid.uuid4().hex[:6]}"))
    bob_repo = BrandRepo(second_session, bob.tenant_id)
    bob_repo.add(Brand(name="B", slug=f"b{uuid.uuid4().hex[:6]}"))
    await session.flush()
    await second_session.commit()

    try:
        removed = await BrandRepo(session, alice.tenant_id).delete_where()
        assert removed == 1
        assert await bob_repo.count() == 1
    finally:
        await bob_repo.delete_where()
        await second_session.commit()


async def test_memory_is_never_shared_across_tenants(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    MemoryRepo(second_session, bob.tenant_id).add(
        Memory(key="pricing", content="Bob's confidential pricing strategy", source="user")
    )
    await second_session.commit()

    try:
        found = await MemoryRepo(session, alice.tenant_id).list()
        assert found == []
    finally:
        await MemoryRepo(second_session, bob.tenant_id).delete_where()
        await second_session.commit()


async def test_recommendations_are_never_shared_across_tenants(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    bob_brand = BrandRepo(second_session, bob.tenant_id).add(
        Brand(name="Bob", slug=f"b{uuid.uuid4().hex[:6]}")
    )
    await second_session.flush()
    RecommendationRepo(second_session, bob.tenant_id).add(
        Recommendation(
            brand_id=bob_brand.id,
            recommendation_type="content_update",
            title="Bob's confidential plan",
        )
    )
    await second_session.commit()

    try:
        assert await RecommendationRepo(session, alice.tenant_id).list() == []
    finally:
        await RecommendationRepo(second_session, bob.tenant_id).delete_where()
        await second_session.delete(bob_brand)
        await second_session.commit()


async def test_service_layer_refuses_a_foreign_brand(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    """The whole stack, not just the repository: service → repo → session."""
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    bob_brand = BrandRepo(second_session, bob.tenant_id).add(
        Brand(name="Bob", slug=f"b{uuid.uuid4().hex[:6]}")
    )
    await second_session.commit()

    try:
        service = BrandService(session, alice)
        with pytest.raises(NotFoundError):
            await service.get(bob_brand.id)
        with pytest.raises(NotFoundError):
            await service.update(bob_brand.id, name="hijacked")
        with pytest.raises(NotFoundError):
            await service.add_competitor(bob_brand.id, name="X", domain="x.test")
    finally:
        await second_session.delete(bob_brand)
        await second_session.commit()
