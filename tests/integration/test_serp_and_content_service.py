"""SERP integration and content service tests.

The production SERP adapter runs against an in-process fake endpoint, so the
real request construction, key handling, error mapping and normalisation all
execute. The development adapter is tested for the property that matters: what
it returns is labelled synthetic at every layer, and its domains cannot be
mistaken for real competitors.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from seo_engine.domain.models.integrations import ProviderRawResponse
from seo_engine.domain.services import BrandService, ContentService, IntegrationService
from seo_engine.domain.services.content import EVALUATION_GATE, content_hash
from seo_engine.domain.services.search import SearchService
from seo_engine.integrations.serp.adapters import (
    DevelopmentSERPAdapter,
    SerpApiAdapter,
    normalise_serp,
)
from seo_engine.schemas.content import (
    ContentBrief,
    ContentDraft,
    ContentEvaluation,
    ContentSection,
    RepurposedAsset,
)
from seo_engine.schemas.enums import (
    ContentStatus,
    DataProvenance,
    IntegrationMode,
    IntegrationProvider,
    SourceTier,
)
from seo_engine.schemas.evidence import SourceReference
from seo_engine.shared.errors import (
    ConflictError,
    CredentialError,
    IntegrationError,
    IntegrationNotConnectedError,
    PermissionDeniedError,
)
from seo_engine.shared.ids import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

OBSERVED_PAGE = {
    "search_parameters": {"q": "nipt test cost"},
    "organic_results": [
        {
            "position": 1,
            "link": "https://www.rival.test/nipt-cost",
            "title": "NIPT cost",
            "snippet": "Prices from...",
        },
        {"position": 2, "link": "https://acme.test/prenatal", "title": "Prenatal screening"},
        {"position": 3, "title": "a result with no link is skipped"},
    ],
    "ads": [{"position": 1, "link": "https://ads.test/offer", "description": "Book now"}],
    "related_questions": [{"question": "How much is an NIPT test?"}, {"snippet": "no question"}],
    "related_searches": [{"query": "nipt test near me"}],
    "answer_box": {"type": "organic_result"},
}


# --- normaliser --------------------------------------------------------------
def test_normaliser_splits_organic_and_paid_and_reads_features() -> None:
    result = normalise_serp(
        OBSERVED_PAGE,
        query="nipt test cost",
        provider="serpapi",
        mode=IntegrationMode.PRODUCTION,
        country="gb",
    )
    snapshot = result.snapshot
    assert snapshot.provenance is DataProvenance.OBSERVED
    assert snapshot.available is True
    organic = [r for r in snapshot.results if r.result_type == "organic"]
    paid = [r for r in snapshot.results if r.result_type == "paid"]
    assert [r.domain for r in organic] == ["rival.test", "acme.test"]
    assert [r.domain for r in paid] == ["ads.test"]
    assert {"featured_snippet", "people_also_ask", "paid_ads", "related_searches"} <= set(
        snapshot.features
    )
    assert "local_pack" not in snapshot.features, "absent payload keys are not features"
    assert result.questions == ["How much is an NIPT test?"]
    assert result.related_searches == ["nipt test near me"]


def test_a_provider_error_is_an_unavailable_page_not_an_empty_one() -> None:
    result = normalise_serp(
        {"error": "Invalid API key."},
        query="q",
        provider="serpapi",
        mode=IntegrationMode.PRODUCTION,
    )
    assert result.snapshot.available is False
    assert result.snapshot.unavailable_reason == "Invalid API key."
    assert result.snapshot.results == []


def test_an_empty_results_page_is_still_an_observation() -> None:
    result = normalise_serp(
        {"error": "Google hasn't returned any results for this query."},
        query="q",
        provider="serpapi",
        mode=IntegrationMode.PRODUCTION,
    )
    assert result.snapshot.available is True
    assert result.snapshot.results == []


# --- production adapter -----------------------------------------------------
def _serp_app(*, status: int = 200, seen: list[httpx.Request] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        if request.url.path == "/account.json":
            return httpx.Response(200, json={"plan": "test"})
        return httpx.Response(200, json=OBSERVED_PAGE)

    return httpx.MockTransport(handler)


async def test_production_adapter_sends_the_key_but_never_stores_it() -> None:
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=_serp_app(seen=seen)) as client:
        adapter = SerpApiAdapter("secret-key", base_url="https://serp.test", client=client)
        response = await adapter.search(query="nipt test cost", country="GB", language="en")

    assert seen[-1].url.params["api_key"] == "secret-key"
    assert seen[-1].url.params["gl"] == "gb"
    assert "api_key" not in response.request_params, "the key must not reach raw storage"
    assert response.mode is IntegrationMode.PRODUCTION
    assert response.notice is None
    assert response.payload["organic_results"][0]["position"] == 1


async def test_production_adapter_maps_auth_and_rate_limit_failures() -> None:
    async with httpx.AsyncClient(transport=_serp_app(status=401)) as client:
        adapter = SerpApiAdapter("bad", base_url="https://serp.test", client=client)
        with pytest.raises(CredentialError):
            await adapter.search(query="q")
        health = await adapter.health_check()
        assert health.healthy is False

    async with httpx.AsyncClient(transport=_serp_app(status=429)) as client:
        adapter = SerpApiAdapter("k", base_url="https://serp.test", client=client)
        with pytest.raises(IntegrationError) as caught:
            await adapter.search(query="q")
        assert caught.value.details.get("retryable") is True


# --- development adapter ----------------------------------------------------
async def test_development_adapter_is_labelled_and_uses_reserved_domains() -> None:
    adapter = DevelopmentSERPAdapter()
    response = await adapter.search(query="how much does a dna test cost")
    assert response.mode is IntegrationMode.DEVELOPMENT_ADAPTER
    assert response.notice, "development responses must carry the synthetic notice"
    assert response.payload["synthetic"] is True

    result = normalise_serp(
        response.payload,
        query="how much does a dna test cost",
        provider="serp_development_adapter",
        mode=response.mode,
    )
    assert result.snapshot.provenance is DataProvenance.SYNTHETIC_DEMO
    assert result.snapshot.results
    assert all(r.domain.endswith(".example") for r in result.snapshot.results)
    assert result.questions, "a question-like query carries people-also-ask in development"


async def test_development_adapter_is_deterministic() -> None:
    adapter = DevelopmentSERPAdapter()
    first = await adapter.search(query="dna testing")
    second = await adapter.search(query="dna testing")
    assert first.payload == second.payload


# --- service ----------------------------------------------------------------
async def _brand(session: AsyncSession, principal):
    return await BrandService(session, principal).create(name=f"Acme {uuid.uuid4().hex[:6]}")


async def test_connecting_serp_without_a_key_uses_the_development_adapter(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    connection = await IntegrationService(session, principal).connect(
        brand.id, IntegrationProvider.SERP_API
    )
    assert connection.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value
    assert "search" in connection.capabilities


async def test_a_serp_lookup_is_persisted_synthetic_and_readable(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    integrations = IntegrationService(session, principal)
    await integrations.connect(brand.id, IntegrationProvider.SERP_API)

    normalised = await integrations.serp_lookup(brand.id, "dna testing", brand_domain="acme.test")
    assert normalised.snapshot.provenance is DataProvenance.SYNTHETIC_DEMO

    raw = (
        (
            await session.execute(
                select(ProviderRawResponse).where(ProviderRawResponse.provider == "serp_api")
            )
        )
        .scalars()
        .all()
    )
    assert raw and all(r.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value for r in raw)
    assert all("api_key" not in r.request_params for r in raw)

    snapshots = await SearchService(session, principal).latest_snapshots(brand.id)
    assert [s.query for s in snapshots] == ["dna testing"]
    assert snapshots[0].provenance is DataProvenance.SYNTHETIC_DEMO
    assert snapshots[0].results


async def test_a_serp_lookup_without_a_connection_raises(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    with pytest.raises(IntegrationNotConnectedError):
        await IntegrationService(session, principal).serp_lookup(brand.id, "dna testing")


# --- content service --------------------------------------------------------
def _brief() -> ContentBrief:
    return ContentBrief(
        title="How much does a DNA test cost?",
        primary_topic="dna test cost",
        primary_keyword="dna test cost",
        audience="Expectant parents",
        business_goal="Qualified enquiries",
        unique_value_proposition="Accredited laboratory pricing explained",
        required_sections=["What affects the price"],
    )


def _draft(body: str = "What affects the price depends on the test.") -> ContentDraft:
    return ContentDraft(
        title="How much does a DNA test cost?",
        meta_description="Pricing explained.",
        slug="dna-test-cost",
        sections=[ContentSection(heading="What affects the price", body=body)],
        body_markdown=f"## What affects the price\n\n{body}",
    )


async def test_versions_are_immutable_and_hash_tracked(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    content = ContentService(session, principal)

    brief = await content.save_brief(brand.id, _brief(), created_by_agent="CNT-003")
    again = await content.save_brief(brand.id, _brief(), created_by_agent="CNT-003")
    assert again.id == brief.id, "re-briefing the same topic revises the open brief"

    asset = await content.create_asset(brand.id, title="DNA test cost", slug="dna-test-cost")
    v1 = await content.add_version(asset, _draft(), change_summary="first", brief_id=brief.id)
    v2 = await content.add_version(asset, _draft("Updated copy."), change_summary="second")

    versions = await content.list_versions(asset.id)
    assert [v.version for v in versions] == [1, 2]
    assert versions[0].body_markdown == v1.body_markdown, "v1 must not be overwritten"
    assert asset.current_version == 2
    assert asset.content_hash == content_hash(v2.body_markdown)
    assert content.draft_contract(v2).sections[0].body == "Updated copy."


async def test_an_agent_scoped_service_cannot_approve_content(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    human = ContentService(session, principal)
    agent = ContentService(session, principal, acting_as_agent=True)

    asset = await agent.create_asset(brand.id, title="t", slug="t")
    version = await agent.add_version(asset, _draft(), change_summary="v1")
    await agent.set_status(asset.id, ContentStatus.IN_REVIEW, reason="passed gate")

    with pytest.raises(PermissionDeniedError):
        await agent.set_status(asset.id, ContentStatus.APPROVED, reason="self-approval")

    # A person can approve, but only once the quality gate has passed.
    with pytest.raises(ConflictError):
        await human.approve(asset.id)
    await agent.record_evaluation(
        asset.id,
        ContentEvaluation(overall_score=80, passed=True),
        version_id=version.id,
        evaluation_type=EVALUATION_GATE,
        evaluated_by_agent="CNT-009",
    )
    approved = await human.approve(asset.id, note="reviewed")
    assert approved.status == ContentStatus.APPROVED.value


async def test_illegal_transitions_are_refused(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    content = ContentService(session, principal)
    asset = await content.create_asset(brand.id, title="t", slug="t2")
    with pytest.raises(ConflictError):
        await content.set_status(asset.id, ContentStatus.PUBLISHED, reason="skip review")
    with pytest.raises(ConflictError):
        await content.mark_published(asset.id, url="https://acme.test/t", external_ref={})


async def test_a_source_is_verified_only_by_a_fetch(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    content = ContentService(session, principal)

    fetched = SourceReference(
        url="https://www.nhs.uk/conditions/nipt",
        title="NIPT",
        retrieved_at=utcnow(),
        tier=SourceTier.TIER_2_AUTHORITATIVE,
        verified=True,
    )
    mentioned = fetched.model_copy(update={"verified": False})
    assert await content.add_sources(brand.id, [fetched]) == 1
    assert await content.add_sources(brand.id, [mentioned]) == 0
    sources = await content.list_sources(brand.id)
    assert len(sources) == 1 and sources[0].verified is True


async def test_derivatives_replace_their_unpublished_predecessor(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    content = ContentService(session, principal)
    asset = await content.create_asset(brand.id, title="t", slug="t3")
    derivative = RepurposedAsset(
        platform="linkedin",
        audience="clinicians",
        objective="awareness",
        format="post",
        tone="calm",
        cta="Read more",
        body="v1",
        canonical_source_url="https://acme.test/t3",
    )
    await content.save_representations(asset.id, [derivative])
    await content.save_representations(asset.id, [derivative.model_copy(update={"body": "v2"})])
    rows = await content.list_representations(asset.id)
    assert [(r.platform, r.body) for r in rows] == [("linkedin", "v2")]
    assert rows[0].canonical_source_url == "https://acme.test/t3"


async def test_content_is_tenant_scoped(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    from seo_engine.shared.errors import NotFoundError

    from tests.conftest import make_tenant

    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")
    bob_brand = await _brand(second_session, bob)
    bob_asset = await ContentService(second_session, bob).create_asset(
        bob_brand.id, title="Bob's draft", slug="bob-draft"
    )
    await second_session.commit()
    try:
        with pytest.raises(NotFoundError):
            await ContentService(session, alice).get_asset(bob_asset.id)
        assert await ContentService(session, alice).list_assets(bob_brand.id) == []
    finally:
        await second_session.delete(bob_brand)
        await second_session.commit()
