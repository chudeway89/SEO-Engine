"""Integration adapter and sync tests.

The production adapters are exercised against an in-process fake Google API
through httpx, so the real request construction, auth headers, error mapping and
normalisation all run. The development adapters are tested for the property that
matters most: everything they produce is labelled synthetic, everywhere.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from seo_engine.domain.models.integrations import (
    GA4Conversion,
    GSCPerformance,
    ProviderRawResponse,
)
from seo_engine.domain.services import BrandService, IntegrationService
from seo_engine.integrations.base import DEVELOPMENT_NOTICE
from seo_engine.integrations.cms.adapters import DevelopmentCMSAdapter
from seo_engine.integrations.google.analytics import (
    DevelopmentAnalyticsAdapter,
    GoogleAnalyticsAdapter,
)
from seo_engine.integrations.google.oauth import OAuthTokens, build_authorisation_url
from seo_engine.integrations.google.search_console import (
    DevelopmentSearchConsoleAdapter,
    GoogleSearchConsoleAdapter,
)
from seo_engine.schemas.enums import (
    DataProvenance,
    IntegrationMode,
    IntegrationProvider,
    IntegrationStatus,
)
from seo_engine.shared.config import override_settings
from seo_engine.shared.errors import (
    CredentialError,
    IntegrationNotConnectedError,
    ValidationError,
)
from seo_engine.shared.ids import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


# --- OAuth ------------------------------------------------------------------
def test_authorisation_url_requires_configuration() -> None:
    override_settings(google_client_id=None, google_client_secret=None)
    try:
        with pytest.raises(ValidationError, match="not configured"):
            build_authorisation_url(scopes=["x"])
    finally:
        override_settings(google_client_id=None, google_client_secret=None)


def test_authorisation_url_requests_offline_access() -> None:
    """Without access_type=offline there is no refresh token, and the
    connection silently dies at the first token expiry."""
    override_settings(google_client_id="cid", google_client_secret="secret")
    try:
        url, state = build_authorisation_url(scopes=["https://example.test/scope"])
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert f"state={state}" in url
    finally:
        override_settings(google_client_id=None, google_client_secret=None)


def test_tokens_expiring_shortly_are_treated_as_expired() -> None:
    from datetime import timedelta

    fresh = OAuthTokens(
        access_token="a", refresh_token="r", expires_at=utcnow() + timedelta(hours=1), scopes=[]
    )
    stale = OAuthTokens(
        access_token="a", refresh_token="r", expires_at=utcnow() + timedelta(seconds=5), scopes=[]
    )
    assert fresh.is_expired is False
    assert stale.is_expired is True


# --- Production adapters against a fake Google -------------------------------
def _google_app(*, unauthorised: bool = False):
    async def app(scope, receive, send):
        path = scope["path"]
        headers = dict(scope["headers"])
        authorised = headers.get(b"authorization") == b"Bearer good-token"

        async def respond(status: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})

        if unauthorised or not authorised:
            await respond(401, {"error": {"message": "Invalid Credentials"}})
            return

        if path == "/webmasters/v3/sites":
            await respond(
                200,
                {"siteEntry": [{"siteUrl": "https://acme.test/", "permissionLevel": "siteOwner"}]},
            )
        elif path.endswith("/searchAnalytics/query"):
            await respond(
                200,
                {
                    "rows": [
                        {
                            "keys": ["dna test cost", "https://acme.test/pricing", "2026-08-01"],
                            "clicks": 12,
                            "impressions": 480,
                            "ctr": 0.025,
                            "position": 8.4,
                        }
                    ]
                },
            )
        elif path.endswith("/sitemaps"):
            await respond(
                200,
                {
                    "sitemap": [
                        {
                            "path": "https://acme.test/sitemap.xml",
                            "errors": "0",
                            "warnings": "0",
                            "contents": [{"submitted": "12", "indexed": "10"}],
                        }
                    ]
                },
            )
        elif path.endswith("/accountSummaries"):
            await respond(
                200,
                {
                    "accountSummaries": [
                        {
                            "displayName": "Acme",
                            "propertySummaries": [
                                {"property": "properties/12345", "displayName": "Acme web"}
                            ],
                        }
                    ]
                },
            )
        elif path.endswith(":runReport"):
            await respond(
                200,
                {
                    "rows": [
                        {
                            "dimensionValues": [
                                {"value": "20260801"},
                                {"value": "/pricing"},
                                {"value": "Organic Search"},
                            ],
                            "metricValues": [
                                {"value": "120"},
                                {"value": "96"},
                                {"value": "60"},
                                {"value": "70"},
                                {"value": "0.58"},
                                {"value": "94.2"},
                                {"value": "4"},
                                {"value": "480"},
                            ],
                        }
                    ]
                },
            )
        else:
            await respond(404, {"error": {"message": f"no route for {path}"}})

    return app


def _tokens(access_token: str = "good-token") -> OAuthTokens:
    from datetime import timedelta

    return OAuthTokens(
        access_token=access_token,
        refresh_token="refresh",
        expires_at=utcnow() + timedelta(hours=1),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )


async def test_production_search_console_adapter_parses_a_real_response() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_google_app()),
        base_url="https://www.googleapis.com",
    ) as client:
        adapter = GoogleSearchConsoleAdapter(_tokens(), client=client)

        health = await adapter.health_check()
        assert health.healthy is True
        assert health.mode is IntegrationMode.PRODUCTION

        performance = await adapter.query_performance(
            site_url="https://acme.test/",
            start_date="2026-08-01",
            end_date="2026-08-28",
            dimensions=["query", "page", "date"],
        )
        assert performance.mode is IntegrationMode.PRODUCTION
        assert performance.notice is None, "real data must carry no synthetic notice"
        assert performance.payload["rows"][0]["impressions"] == 480


async def test_production_adapter_maps_a_401_to_a_credential_error() -> None:
    """An auth failure must never be retried as if it were transient."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_google_app(unauthorised=True)),
        base_url="https://www.googleapis.com",
    ) as client:
        adapter = GoogleSearchConsoleAdapter(_tokens("bad"), client=client)
        with pytest.raises(CredentialError):
            await adapter.list_properties()

        health = await adapter.health_check()
        assert health.healthy is False
        assert health.status is IntegrationStatus.EXPIRED


async def test_production_analytics_adapter_parses_a_real_report() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_google_app()),
        base_url="https://analyticsdata.googleapis.com",
    ) as client:
        adapter = GoogleAnalyticsAdapter(_tokens(), client=client)
        report = await adapter.run_report(
            property_id="12345",
            start_date="2026-08-01",
            end_date="2026-08-28",
            dimensions=["date", "landingPage", "sessionDefaultChannelGroup"],
            metrics=["sessions"],
        )
        assert report.payload["rows"][0]["metricValues"][0]["value"] == "120"


# --- Development adapters ---------------------------------------------------
async def test_development_adapters_label_every_response_as_synthetic() -> None:
    """Rule 1: the architecture may be exercised; the data may not lie."""
    gsc = DevelopmentSearchConsoleAdapter()
    response = await gsc.query_performance(
        site_url="https://demo.test/",
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["query", "page", "date"],
    )
    assert response.mode is IntegrationMode.DEVELOPMENT_ADAPTER
    assert response.is_synthetic is True
    assert response.notice == DEVELOPMENT_NOTICE
    assert "must never be presented as real" in response.notice

    ga4 = DevelopmentAnalyticsAdapter()
    report = await ga4.run_report(
        property_id="1",
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["date", "landingPage"],
        metrics=["sessions"],
    )
    assert report.is_synthetic is True


async def test_development_adapter_health_explains_why_it_is_in_use() -> None:
    health = await DevelopmentSearchConsoleAdapter().health_check()
    assert health.mode is IntegrationMode.DEVELOPMENT_ADAPTER
    assert (
        "no real Search Console data" in health.detail.lower()
        or "development adapter" in health.detail.lower()
    )


async def test_development_data_is_deterministic() -> None:
    first = await DevelopmentSearchConsoleAdapter().query_performance(
        site_url="https://demo.test/",
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["query"],
    )
    second = await DevelopmentSearchConsoleAdapter().query_performance(
        site_url="https://demo.test/",
        start_date="2026-08-01",
        end_date="2026-08-28",
        dimensions=["query"],
    )
    assert first.payload == second.payload


async def test_development_cms_is_draft_first() -> None:
    """Creating a draft must never publish as a side effect."""
    cms = DevelopmentCMSAdapter()
    created = await cms.create_draft(
        title="A guide", body_markdown="# A guide", slug="a-guide", metadata={}
    )
    assert created.payload["status"] == "draft"

    external_id = created.payload["id"]
    updated = await cms.update_draft(
        external_id=external_id, title="A better guide", body_markdown="# Better", metadata={}
    )
    assert updated.payload["status"] == "draft"

    published = await cms.publish(external_id=external_id)
    assert published.payload["status"] == "published"


# --- Service-level sync -----------------------------------------------------
async def _brand(session: AsyncSession, principal):
    return await BrandService(session, principal).create(name=f"Acme {uuid.uuid4().hex[:6]}")


async def test_connecting_without_credentials_uses_the_development_adapter(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)

    connection = await service.connect(brand.id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE)
    assert connection.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value
    assert connection.status == IntegrationStatus.CONNECTED.value
    assert connection.capabilities


async def test_search_console_sync_marks_every_row_synthetic_in_development(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)
    await service.connect(brand.id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE)

    summary = await service.sync_search_console(brand.id, days=28)
    assert summary["synthetic"] is True
    assert summary["rows"] > 0

    rows = await session.execute(select(GSCPerformance).where(GSCPerformance.brand_id == brand.id))
    stored = list(rows.scalars())
    assert stored
    assert all(r.provenance == DataProvenance.SYNTHETIC_DEMO.value for r in stored)
    assert all(r.is_synthetic is True for r in stored)
    assert all(r.data_label == "SYNTHETIC DEMO DATA" for r in stored)


async def test_raw_responses_are_stored_separately_from_normalised_rows(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)
    await service.connect(brand.id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE)
    await service.sync_search_console(brand.id, days=14)

    raw = await session.execute(
        select(ProviderRawResponse).where(
            ProviderRawResponse.provider == IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value
        )
    )
    records = list(raw.scalars())
    assert records, "the untouched provider payload must be retained"
    assert all(r.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value for r in records)

    normalised = await session.execute(
        select(GSCPerformance).where(GSCPerformance.brand_id == brand.id).limit(1)
    )
    assert normalised.scalars().first().raw_response_id is not None


async def test_top_queries_aggregate_for_the_keyword_pipeline(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)
    await service.connect(brand.id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE)
    await service.sync_search_console(brand.id, days=28)

    queries = await service.top_queries(brand.id, limit=10)
    assert queries
    query, impressions, clicks, position = queries[0]
    assert isinstance(query, str) and impressions > 0
    assert clicks >= 0 and position > 0


async def test_analytics_sync_flags_likely_lead_events_for_confirmation(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)
    await service.connect(brand.id, IntegrationProvider.GOOGLE_ANALYTICS_4)

    summary = await service.sync_analytics(brand.id, days=28)
    assert summary["synthetic"] is True

    rows = await session.execute(select(GA4Conversion).where(GA4Conversion.brand_id == brand.id))
    conversions = list(rows.scalars())
    assert conversions
    assert any(c.is_qualified_lead_event for c in conversions)
    assert all(c.provenance == DataProvenance.SYNTHETIC_DEMO.value for c in conversions)


async def test_a_baseline_is_none_when_nothing_is_connected(
    session: AsyncSession, tenant_ctx
) -> None:
    """A mission with no baseline says so, rather than starting from a guess."""
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    value, provenance, source = await IntegrationService(
        session, principal
    ).organic_conversion_baseline(brand.id)

    assert value is None
    assert provenance is DataProvenance.UNKNOWN
    assert "no analytics data" in source


async def test_a_baseline_carries_its_provenance_once_synced(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = IntegrationService(session, principal)
    await service.connect(brand.id, IntegrationProvider.GOOGLE_ANALYTICS_4)
    await service.sync_analytics(brand.id, days=28)

    value, provenance, source = await service.organic_conversion_baseline(brand.id)
    assert value is not None and value > 0
    assert provenance is DataProvenance.SYNTHETIC_DEMO
    assert source == "google_analytics_4"


async def test_syncing_an_unconnected_provider_raises(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    with pytest.raises(IntegrationNotConnectedError):
        await IntegrationService(session, principal).sync_search_console(brand.id)


async def test_connections_are_tenant_scoped(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    from tests.conftest import make_tenant

    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    bob_brand = await BrandService(second_session, bob).create(name="Bob brand")
    await IntegrationService(second_session, bob).connect(
        bob_brand.id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE
    )
    await second_session.commit()

    try:
        assert await IntegrationService(session, alice).list_connections(bob_brand.id) == []
    finally:
        from seo_engine.domain.models.integrations import IntegrationConnection
        from seo_engine.domain.repositories import repository_for

        await repository_for(IntegrationConnection)(second_session, bob.tenant_id).delete_where()
        await second_session.commit()
