"""Domain service tests against the live database."""

from __future__ import annotations

import uuid

import pytest
from seo_engine.domain.models.observability import AuditLog, EventRecord
from seo_engine.domain.services import BrandService, IdentityService, WebsiteService
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import CompetitorType, Role
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import (
    AuthenticationError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_tenant

pytestmark = [pytest.mark.integration]


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.test"


# --- Identity ---------------------------------------------------------------
async def test_registration_creates_user_tenant_and_owner_membership(
    session: AsyncSession,
) -> None:
    service = IdentityService(session)
    result = await service.register(
        email=_unique_email(),
        password="a-sufficiently-long-password",
        name="Ada Lovelace",
        organisation_name="Analytical Engines",
    )
    assert result.membership.role == Role.OWNER
    assert result.tenant.slug.startswith("analytical-engines")
    assert result.tokens.access_token
    assert result.user.password_hash and "password" not in result.user.password_hash


async def test_duplicate_registration_is_rejected(session: AsyncSession) -> None:
    service = IdentityService(session)
    email = _unique_email()
    await service.register(
        email=email, password="a-sufficiently-long-password", name="A", organisation_name="Org"
    )
    with pytest.raises(ConflictError):
        await service.register(
            email=email,
            password="a-sufficiently-long-password",
            name="A",
            organisation_name="Org",
        )


async def test_login_succeeds_and_wrong_password_fails_identically_to_unknown_user(
    session: AsyncSession,
) -> None:
    service = IdentityService(session)
    email = _unique_email()
    await service.register(
        email=email, password="a-sufficiently-long-password", name="A", organisation_name="Org"
    )

    _, _, tokens = await service.login(email=email, password="a-sufficiently-long-password")
    assert tokens.access_token

    with pytest.raises(AuthenticationError, match="invalid email or password"):
        await service.login(email=email, password="the-wrong-password!!")
    with pytest.raises(AuthenticationError, match="invalid email or password"):
        await service.login(email=_unique_email(), password="a-sufficiently-long-password")


async def test_refresh_rereads_the_role_rather_than_trusting_the_token(
    session: AsyncSession,
) -> None:
    service = IdentityService(session)
    email = _unique_email()
    result = await service.register(
        email=email, password="a-sufficiently-long-password", name="A", organisation_name="Org"
    )
    result.membership.role = Role.VIEWER
    await session.flush()

    tokens = await service.refresh(result.tokens.refresh_token)
    from seo_engine.shared.security import decode_token

    assert decode_token(tokens.access_token)["role"] == Role.VIEWER.value


async def test_a_tenant_cannot_lose_its_last_owner(session: AsyncSession) -> None:
    service = IdentityService(session)
    result = await service.register(
        email=_unique_email(),
        password="a-sufficiently-long-password",
        name="A",
        organisation_name="Org",
    )
    principal = Principal.build(
        user_id=result.user.id,
        tenant_id=result.tenant.id,
        email=result.user.email,
        role=Role.OWNER,
    )
    with pytest.raises(ValidationError, match="at least one owner"):
        await service.change_role(principal, user_id=result.user.id, role=Role.VIEWER)


async def test_an_admin_cannot_invite_an_owner(session: AsyncSession) -> None:
    tenant, user, _ = await make_tenant(session, "acme")
    admin = Principal.build(user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.ADMIN)
    with pytest.raises(PermissionDeniedError, match="higher than your own"):
        await IdentityService(session).invite_member(
            admin, email=_unique_email(), name="X", role=Role.OWNER
        )


# --- Brand ------------------------------------------------------------------
async def test_creating_a_brand_emits_an_event_and_an_audit_entry(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await BrandService(session, principal).create(
        name="Acme Diagnostics", industry="healthcare", website="https://acme.test"
    )

    events = await session.execute(
        select(EventRecord).where(EventRecord.aggregate_id == str(brand.id))
    )
    assert [e.event_type for e in events.scalars()] == [EventType.BRAND_CREATED]

    audits = await session.execute(select(AuditLog).where(AuditLog.resource_id == str(brand.id)))
    entry = audits.scalars().one()
    assert entry.action == "brand.create"
    assert entry.actor_id == str(principal.user_id)


async def test_a_viewer_cannot_create_a_brand(session: AsyncSession, tenant_ctx) -> None:
    tenant, user, _ = tenant_ctx
    viewer = Principal.build(
        user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.VIEWER
    )
    with pytest.raises(PermissionDeniedError):
        await BrandService(session, viewer).create(name="Nope")


async def test_brand_update_rejects_unknown_fields(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme")
    with pytest.raises(ValidationError, match="cannot be updated"):
        await service.update(brand.id, tenant_id=uuid.uuid4())


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("https://www.Example.com/path", "example.com"),
        ("Example.com", "example.com"),
        ("http://example.com:8080", "example.com"),
    ],
)
async def test_competitor_domains_are_normalised(
    session: AsyncSession, tenant_ctx, supplied: str, expected: str
) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name=f"Acme {uuid.uuid4().hex[:6]}")
    competitor = await service.add_competitor(brand.id, name="Rival", domain=supplied)
    assert competitor.domain == expected


async def test_a_business_competitor_is_not_assumed_to_be_a_search_competitor(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme")
    competitor = await service.add_competitor(brand.id, name="Rival", domain="rival.test")
    assert competitor.competitor_types == [CompetitorType.BUSINESS.value]
    assert CompetitorType.SERP.value not in competitor.competitor_types


async def test_invalid_competitor_domain_is_rejected(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme")
    with pytest.raises(ValidationError, match="valid domain"):
        await service.add_competitor(brand.id, name="Rival", domain="not-a-domain")


async def test_claims_require_explicit_human_approval(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme")

    claim = await service.add_claim(brand.id, claim="Accredited by the national body")
    assert claim.approved is False
    assert await service.approved_claims(brand.id) == []

    await service.approve_claim(claim.id)
    approved = await service.approved_claims(brand.id)
    assert [c.claim for c in approved] == ["Accredited by the national body"]


async def test_a_prohibited_claim_can_never_be_approved(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme")
    claim = await service.add_claim(brand.id, claim="Cures all illness", is_prohibited=True)
    with pytest.raises(ValidationError, match="prohibited claim cannot be approved"):
        await service.approve_claim(claim.id)
    assert claim.id in {c.id for c in await service.prohibited_claims(brand.id)}


async def test_brand_profile_returns_the_whole_graph(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    service = BrandService(session, principal)
    brand = await service.create(name="Acme Diagnostics", industry="healthcare")
    await service.add_goal(
        brand.id, goal_type="growth", description="Increase qualified organic leads"
    )
    await service.add_service(brand.id, name="DNA testing")
    await service.add_audience(brand.id, name="Prospective parents")
    await service.add_location(brand.id, name="Lagos", city="Lagos", country="NG")
    await service.add_competitor(brand.id, name="Rival", domain="rival.test")

    profile = await service.profile(brand.id)
    assert profile["brand"].name == "Acme Diagnostics"
    assert [g.description for g in profile["goals"]] == ["Increase qualified organic leads"]
    assert len(profile["services"]) == 1
    assert len(profile["audiences"]) == 1
    assert len(profile["locations"]) == 1
    assert len(profile["competitors"]) == 1


# --- Website ----------------------------------------------------------------
async def test_adding_a_website_normalises_the_url_and_derives_robots(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await BrandService(session, principal).create(name="Acme")
    website = await WebsiteService(session, principal).add_website(
        brand.id, url="https://www.Acme.test/en"
    )
    assert website.domain == "acme.test"
    assert website.protocol == "https"
    assert website.robots_url == "https://acme.test/robots.txt"


async def test_the_same_website_cannot_be_connected_twice(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await BrandService(session, principal).create(name="Acme")
    service = WebsiteService(session, principal)
    await service.add_website(brand.id, url="https://acme.test")
    with pytest.raises(ConflictError):
        await service.add_website(brand.id, url="http://www.acme.test/")


async def test_only_one_crawl_may_run_per_website(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await BrandService(session, principal).create(name="Acme")
    service = WebsiteService(session, principal)
    website = await service.add_website(brand.id, url="https://acme.test")

    await service.create_crawl_job(website.id)
    with pytest.raises(ConflictError, match="already in progress"):
        await service.create_crawl_job(website.id)


async def test_an_analyst_may_crawl_but_not_add_a_website(
    session: AsyncSession, tenant_ctx
) -> None:
    tenant, user, owner = tenant_ctx
    brand = await BrandService(session, owner).create(name="Acme")
    website = await WebsiteService(session, owner).add_website(brand.id, url="https://acme.test")

    analyst = Principal.build(
        user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.ANALYST
    )
    service = WebsiteService(session, analyst)
    assert (await service.create_crawl_job(website.id)) is not None
    with pytest.raises(PermissionDeniedError):
        await service.add_website(brand.id, url="https://other.test")
