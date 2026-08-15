"""Integration service: connections, credentials, adapter resolution and sync.

Two properties matter most here:

* **An integration is never described as connected when it is not.** The
  connection's ``mode`` records whether it is production or the development
  adapter, and every normalised row synced through a development adapter carries
  ``provenance=synthetic_demo`` and ``is_synthetic=True``.
* **Raw and normalised data are separate.** The provider payload is stored
  verbatim in ``provider_raw_responses``; the normalised tables reference it, so
  a normalisation bug can be replayed rather than silently rewriting history.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from seo_engine.domain.models.integrations import (
    GA4Connection,
    GA4Conversion,
    GA4Metric,
    GA4Property,
    GSCConnection,
    GSCPerformance,
    GSCProperty,
    GSCSitemap,
    IntegrationConnection,
    IntegrationCredential,
    ProviderRawResponse,
)
from seo_engine.domain.repositories import repository_for
from seo_engine.events.bus import emit
from seo_engine.integrations.base import ProviderAdapter, ProviderResponse
from seo_engine.integrations.cms.adapters import DevelopmentCMSAdapter, WordPressAdapter
from seo_engine.integrations.google.analytics import (
    LIKELY_LEAD_EVENTS,
    DevelopmentAnalyticsAdapter,
    GoogleAnalyticsAdapter,
)
from seo_engine.integrations.google.oauth import OAuthTokens
from seo_engine.integrations.google.search_console import (
    DevelopmentSearchConsoleAdapter,
    GoogleSearchConsoleAdapter,
)
from seo_engine.observability.audit import record_audit
from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import (
    P_ANALYTICS_READ,
    P_INTEGRATION_CONNECT,
    P_INTEGRATION_READ,
    Principal,
)
from seo_engine.schemas.enums import (
    DataProvenance,
    IntegrationMode,
    IntegrationProvider,
    IntegrationStatus,
)
from seo_engine.schemas.events import EventType
from seo_engine.shared.config import get_settings
from seo_engine.shared.errors import IntegrationNotConnectedError, ValidationError
from seo_engine.shared.ids import utcnow
from seo_engine.shared.secrets import get_secret_provider
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

ConnectionRepository = repository_for(IntegrationConnection)
CredentialRepository = repository_for(IntegrationCredential)
RawResponseRepository = repository_for(ProviderRawResponse)


class IntegrationService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.connections = ConnectionRepository(session, principal.tenant_id)
        self.credentials = CredentialRepository(session, principal.tenant_id)
        self.raw = RawResponseRepository(session, principal.tenant_id)

    # -- connections -------------------------------------------------------
    async def connect(
        self,
        brand_id: uuid.UUID,
        provider: IntegrationProvider | str,
        *,
        tokens: OAuthTokens | None = None,
        settings_payload: dict[str, Any] | None = None,
        account_label: str | None = None,
    ) -> IntegrationConnection:
        """Create or refresh a connection.

        With no credentials the connection is still created — but in
        ``DEVELOPMENT_ADAPTER`` mode, and the health detail says exactly why.
        """
        self.principal.require(P_INTEGRATION_CONNECT)
        provider = IntegrationProvider(provider)

        mode = (
            IntegrationMode.PRODUCTION
            if tokens is not None
            else IntegrationMode.DEVELOPMENT_ADAPTER
        )
        record = await self.connections.find_one(
            IntegrationConnection.brand_id == brand_id,
            IntegrationConnection.provider == provider.value,
        )
        if record is None:
            record = self.connections.add(
                IntegrationConnection(
                    brand_id=brand_id,
                    provider=provider.value,
                    mode=mode.value,
                    connected_by=self.principal.user_id,
                    settings={},
                    capabilities=[],
                )
            )
        record.mode = mode.value
        record.settings = settings_payload or record.settings or {}
        record.account_label = account_label or record.account_label
        await self.session.flush()

        if tokens is not None:
            await self._store_credentials(record, tokens)

        adapter = await self.adapter_for(record)
        health = await adapter.health_check()
        record.status = health.status.value
        record.last_health_check_at = utcnow()
        record.last_health_status = "healthy" if health.healthy else "unhealthy"
        record.last_error = None if health.healthy else health.detail
        record.capabilities = [c.name for c in await adapter.capabilities()]
        await self.session.flush()

        await emit(
            self.session,
            EventType.ANALYTICS_SYNCED
            if provider
            in {IntegrationProvider.GOOGLE_SEARCH_CONSOLE, IntegrationProvider.GOOGLE_ANALYTICS_4}
            else EventType.WEBSITE_CONNECTED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="integration_connection",
            aggregate_id=str(record.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"provider": provider.value, "mode": mode.value, "status": record.status},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="integration.connect",
            resource_type="integration_connection",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=brand_id,
            reason=f"connected {provider.value} in {mode.value} mode",
        )
        return record

    async def _store_credentials(
        self, connection: IntegrationConnection, tokens: OAuthTokens
    ) -> IntegrationCredential:
        ref, material = get_secret_provider().encrypt(tokens.to_payload())
        existing = await self.credentials.find_one(
            IntegrationCredential.connection_id == connection.id
        )
        if existing is None:
            existing = self.credentials.add(
                IntegrationCredential(
                    connection_id=connection.id,
                    provider=connection.provider,
                    credential_ref=ref,
                    encrypted_payload=material,
                    scopes=tokens.scopes,
                    expires_at=tokens.expires_at,
                )
            )
        else:
            existing.credential_ref = ref
            existing.encrypted_payload = material
            existing.scopes = tokens.scopes
            existing.expires_at = tokens.expires_at
            existing.rotated_at = utcnow()
        await self.session.flush()
        return existing

    async def _load_tokens(self, connection: IntegrationConnection) -> OAuthTokens | None:
        credential = await self.credentials.find_one(
            IntegrationCredential.connection_id == connection.id
        )
        if credential is None or not credential.encrypted_payload:
            return None
        payload = get_secret_provider().decrypt(
            credential.credential_ref, credential.encrypted_payload
        )
        return OAuthTokens.from_payload(payload)

    async def get_connection(
        self, brand_id: uuid.UUID, provider: IntegrationProvider | str
    ) -> IntegrationConnection | None:
        self.principal.require(P_INTEGRATION_READ)
        return await self.connections.find_one(
            IntegrationConnection.brand_id == brand_id,
            IntegrationConnection.provider == IntegrationProvider(provider).value,
        )

    async def list_connections(self, brand_id: uuid.UUID) -> list[IntegrationConnection]:
        self.principal.require(P_INTEGRATION_READ)
        return list(await self.connections.list(IntegrationConnection.brand_id == brand_id))

    async def connected_providers(self, brand_id: uuid.UUID) -> set[str]:
        """Providers usable for this brand, in either mode.

        The agent runtime uses this to decide which tools are available. A
        development-adapter connection counts as available, because the tool
        *works* — its data is simply labelled synthetic everywhere it lands.
        """
        rows = await self.connections.list(
            IntegrationConnection.brand_id == brand_id,
            IntegrationConnection.status == IntegrationStatus.CONNECTED,
        )
        return {row.provider for row in rows}

    async def adapter_for(self, connection: IntegrationConnection) -> ProviderAdapter:
        """Resolve the adapter for a connection: production if we hold usable
        credentials, otherwise the clearly-labelled development adapter."""
        provider = IntegrationProvider(connection.provider)
        tokens = await self._load_tokens(connection)
        settings = get_settings()

        if provider is IntegrationProvider.GOOGLE_SEARCH_CONSOLE:
            if tokens and settings.google_oauth_configured():
                return GoogleSearchConsoleAdapter(tokens)
            return DevelopmentSearchConsoleAdapter(
                site_url=(connection.settings or {}).get(
                    "site_url", "https://demo.seo-engine.local/"
                )
            )

        if provider is IntegrationProvider.GOOGLE_ANALYTICS_4:
            if tokens and settings.google_oauth_configured():
                return GoogleAnalyticsAdapter(tokens)
            return DevelopmentAnalyticsAdapter(
                property_id=(connection.settings or {}).get("property_id", "000000000")
            )

        if provider is IntegrationProvider.WORDPRESS:
            credentials = connection.settings or {}
            if credentials.get("site_url") and credentials.get("username"):
                secret = await self._load_tokens(connection)
                password = (secret.access_token if secret else None) or ""
                if password:
                    return WordPressAdapter(
                        site_url=credentials["site_url"],
                        username=credentials["username"],
                        application_password=password,
                    )
            return DevelopmentCMSAdapter()

        if provider is IntegrationProvider.GENERIC_CMS:
            return DevelopmentCMSAdapter(
                site_url=(connection.settings or {}).get(
                    "site_url", "https://demo.seo-engine.local"
                )
            )

        raise ValidationError(
            f"no adapter is implemented for {provider.value}",
            {
                "provider": provider.value,
                "note": (
                    "The adapter contract exists; the production connector for this "
                    "provider has not been built yet."
                ),
            },
        )

    async def require_adapter(
        self, brand_id: uuid.UUID, provider: IntegrationProvider | str
    ) -> tuple[IntegrationConnection, ProviderAdapter]:
        connection = await self.get_connection(brand_id, provider)
        if connection is None:
            raise IntegrationNotConnectedError(
                f"{IntegrationProvider(provider).value} is not connected for this brand",
                {"provider": IntegrationProvider(provider).value},
            )
        return connection, await self.adapter_for(connection)

    # -- raw storage -------------------------------------------------------
    async def store_raw(
        self, connection: IntegrationConnection, response: ProviderResponse
    ) -> ProviderRawResponse:
        record = self.raw.add(
            ProviderRawResponse(
                connection_id=connection.id,
                provider=connection.provider,
                endpoint=response.endpoint,
                request_params=_jsonable(response.request_params),
                response_payload=response.payload,
                status_code=response.status_code,
                mode=response.mode.value,
                fetched_at=utcnow(),
            )
        )
        await self.session.flush()
        return record

    # -- Search Console sync ----------------------------------------------
    async def sync_search_console(
        self,
        brand_id: uuid.UUID,
        *,
        website_id: uuid.UUID | None = None,
        days: int = 28,
        row_limit: int = 500,
    ) -> dict[str, Any]:
        """Pull performance, sitemaps and property data into normalised tables."""
        self.principal.require(P_ANALYTICS_READ)
        connection, adapter = await self.require_adapter(
            brand_id, IntegrationProvider.GOOGLE_SEARCH_CONSOLE
        )
        synthetic = connection.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value
        provenance = DataProvenance.SYNTHETIC_DEMO if synthetic else DataProvenance.OBSERVED

        gsc_repo = repository_for(GSCConnection)(self.session, self.principal.tenant_id)
        gsc = await gsc_repo.find_one(GSCConnection.connection_id == connection.id)
        if gsc is None:
            gsc = gsc_repo.add(
                GSCConnection(
                    connection_id=connection.id,
                    brand_id=brand_id,
                    mode=connection.mode,
                    google_account_email=connection.account_label,
                )
            )
            await self.session.flush()

        properties = await adapter.list_properties()
        await self.store_raw(connection, properties)

        property_repo = repository_for(GSCProperty)(self.session, self.principal.tenant_id)
        site_url = (connection.settings or {}).get("site_url")
        for entry in properties.payload.get("siteEntry", []):
            existing = await property_repo.find_one(
                GSCProperty.gsc_connection_id == gsc.id,
                GSCProperty.site_url == entry["siteUrl"],
            )
            if existing is None:
                property_repo.add(
                    GSCProperty(
                        gsc_connection_id=gsc.id,
                        site_url=entry["siteUrl"],
                        permission_level=entry.get("permissionLevel"),
                        is_selected=site_url in (None, entry["siteUrl"]),
                    )
                )
            site_url = site_url or entry["siteUrl"]
        await self.session.flush()

        if not site_url:
            raise IntegrationNotConnectedError(
                "no Search Console property is available for this brand", {}
            )
        gsc.selected_property = site_url

        end = date.today()
        start = end - timedelta(days=days)
        performance = await adapter.query_performance(
            site_url=site_url,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            dimensions=["query", "page", "date"],
            row_limit=row_limit,
        )
        raw_record = await self.store_raw(connection, performance)

        perf_repo = repository_for(GSCPerformance)(self.session, self.principal.tenant_id)
        await perf_repo.delete_where(
            GSCPerformance.brand_id == brand_id, GSCPerformance.site_url == site_url
        )
        rows = performance.payload.get("rows", [])
        for row in rows:
            keys = row.get("keys", [])
            perf_repo.add(
                GSCPerformance(
                    brand_id=brand_id,
                    website_id=website_id,
                    site_url=site_url,
                    date=_parse_date(keys[2]) if len(keys) > 2 else end,
                    query=keys[0] if keys else None,
                    page=keys[1] if len(keys) > 1 else None,
                    clicks=int(row.get("clicks", 0)),
                    impressions=int(row.get("impressions", 0)),
                    ctr=float(row.get("ctr", 0.0)),
                    position=float(row.get("position", 0.0)),
                    provenance=provenance.value,
                    raw_response_id=raw_record.id,
                    is_synthetic=synthetic,
                    data_label="SYNTHETIC DEMO DATA" if synthetic else None,
                )
            )

        sitemaps = await adapter.list_sitemaps(site_url=site_url)
        await self.store_raw(connection, sitemaps)
        sitemap_repo = repository_for(GSCSitemap)(self.session, self.principal.tenant_id)
        await sitemap_repo.delete_where(
            GSCSitemap.brand_id == brand_id, GSCSitemap.site_url == site_url
        )
        for entry in sitemaps.payload.get("sitemap", []):
            contents = entry.get("contents", [{}])[0]
            sitemap_repo.add(
                GSCSitemap(
                    brand_id=brand_id,
                    site_url=site_url,
                    path=entry.get("path", ""),
                    sitemap_type=entry.get("type"),
                    is_pending=bool(entry.get("isPending", False)),
                    is_sitemaps_index=bool(entry.get("isSitemapsIndex", False)),
                    warnings=int(entry.get("warnings", 0) or 0),
                    errors=int(entry.get("errors", 0) or 0),
                    submitted_urls=int(contents.get("submitted", 0) or 0),
                    indexed_urls=int(contents.get("indexed", 0) or 0)
                    if contents.get("indexed")
                    else None,
                )
            )

        connection.last_synced_at = utcnow()
        await self.session.flush()

        await emit(
            self.session,
            EventType.ANALYTICS_SYNCED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="integration_connection",
            aggregate_id=str(connection.id),
            payload={
                "provider": IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value,
                "rows": len(rows),
                "mode": connection.mode,
                "provenance": provenance.value,
            },
        )
        return {
            "site_url": site_url,
            "rows": len(rows),
            "mode": connection.mode,
            "provenance": provenance.value,
            "synthetic": synthetic,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
        }

    async def top_queries(
        self, brand_id: uuid.UUID, *, limit: int = 100
    ) -> list[tuple[str, int, int, float]]:
        """Aggregated observed queries, for the keyword pipeline's demand signal."""
        from sqlalchemy import func, select

        repo = repository_for(GSCPerformance)(self.session, self.principal.tenant_id)
        statement = (
            select(
                GSCPerformance.query,
                func.sum(GSCPerformance.impressions),
                func.sum(GSCPerformance.clicks),
                func.avg(GSCPerformance.position),
            )
            .where(
                GSCPerformance.tenant_id == self.principal.tenant_id,
                GSCPerformance.brand_id == brand_id,
                GSCPerformance.query.is_not(None),
            )
            .group_by(GSCPerformance.query)
            .order_by(func.sum(GSCPerformance.impressions).desc())
            .limit(limit)
        )
        rows = await self.session.execute(statement)
        _ = repo  # repository construction pins the session to this tenant
        return [
            (query, int(impressions or 0), int(clicks or 0), float(position or 0.0))
            for query, impressions, clicks, position in rows.all()
        ]

    # -- GA4 sync ----------------------------------------------------------
    async def sync_analytics(self, brand_id: uuid.UUID, *, days: int = 28) -> dict[str, Any]:
        self.principal.require(P_ANALYTICS_READ)
        connection, adapter = await self.require_adapter(
            brand_id, IntegrationProvider.GOOGLE_ANALYTICS_4
        )
        synthetic = connection.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value
        provenance = DataProvenance.SYNTHETIC_DEMO if synthetic else DataProvenance.OBSERVED

        ga4_repo = repository_for(GA4Connection)(self.session, self.principal.tenant_id)
        ga4 = await ga4_repo.find_one(GA4Connection.connection_id == connection.id)
        if ga4 is None:
            ga4 = ga4_repo.add(
                GA4Connection(
                    connection_id=connection.id,
                    brand_id=brand_id,
                    mode=connection.mode,
                    google_account_email=connection.account_label,
                )
            )
            await self.session.flush()

        properties = await adapter.list_properties()
        await self.store_raw(connection, properties)

        property_repo = repository_for(GA4Property)(self.session, self.principal.tenant_id)
        property_id = (connection.settings or {}).get("property_id")
        for summary in properties.payload.get("accountSummaries", []):
            for item in summary.get("propertySummaries", []):
                resolved = item["property"].split("/")[-1]
                existing = await property_repo.find_one(
                    GA4Property.ga4_connection_id == ga4.id,
                    GA4Property.property_id == resolved,
                )
                if existing is None:
                    property_repo.add(
                        GA4Property(
                            ga4_connection_id=ga4.id,
                            property_id=resolved,
                            display_name=item.get("displayName", ""),
                            account_name=summary.get("displayName"),
                            is_selected=property_id in (None, resolved),
                        )
                    )
                property_id = property_id or resolved
        await self.session.flush()

        if not property_id:
            raise IntegrationNotConnectedError(
                "no Analytics property is available for this brand", {}
            )
        ga4.selected_property_id = property_id

        end = date.today()
        start = end - timedelta(days=days)

        traffic = await adapter.run_report(
            property_id=property_id,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            dimensions=["date", "landingPage", "sessionDefaultChannelGroup"],
            metrics=[
                "sessions",
                "totalUsers",
                "newUsers",
                "engagedSessions",
                "engagementRate",
                "averageSessionDuration",
                "conversions",
                "totalRevenue",
            ],
        )
        traffic_raw = await self.store_raw(connection, traffic)

        metric_repo = repository_for(GA4Metric)(self.session, self.principal.tenant_id)
        await metric_repo.delete_where(GA4Metric.brand_id == brand_id)
        traffic_rows = traffic.payload.get("rows", [])
        for row in traffic_rows:
            dimensions = [d["value"] for d in row.get("dimensionValues", [])]
            values = [v["value"] for v in row.get("metricValues", [])]
            metric_repo.add(
                GA4Metric(
                    brand_id=brand_id,
                    property_id=property_id,
                    date=_parse_date(dimensions[0]) if dimensions else end,
                    landing_page=dimensions[1] if len(dimensions) > 1 else None,
                    session_default_channel_group=dimensions[2] if len(dimensions) > 2 else None,
                    sessions=_int(values, 0),
                    users=_int(values, 1),
                    new_users=_int(values, 2),
                    engaged_sessions=_int(values, 3),
                    engagement_rate=_float(values, 4),
                    average_session_duration=_float(values, 5),
                    conversions=_float(values, 6),
                    total_revenue=_float(values, 7),
                    provenance=provenance.value,
                    raw_response_id=traffic_raw.id,
                    is_synthetic=synthetic,
                    data_label="SYNTHETIC DEMO DATA" if synthetic else None,
                )
            )

        conversions = await adapter.conversion_events(
            property_id=property_id, start_date=start.isoformat(), end_date=end.isoformat()
        )
        conversions_raw = await self.store_raw(connection, conversions)

        conversion_repo = repository_for(GA4Conversion)(self.session, self.principal.tenant_id)
        await conversion_repo.delete_where(GA4Conversion.brand_id == brand_id)
        conversion_rows = conversions.payload.get("rows", [])
        for row in conversion_rows:
            dimensions = [d["value"] for d in row.get("dimensionValues", [])]
            values = [v["value"] for v in row.get("metricValues", [])]
            event_name = dimensions[0] if dimensions else "unknown"
            conversion_repo.add(
                GA4Conversion(
                    brand_id=brand_id,
                    property_id=property_id,
                    date=end,
                    event_name=event_name,
                    landing_page=dimensions[1] if len(dimensions) > 1 else None,
                    session_default_channel_group=dimensions[2] if len(dimensions) > 2 else None,
                    event_count=_float(values, 0),
                    conversions=_float(values, 1),
                    event_value=_float(values, 2),
                    # Flagged for the user's confirmation, never assumed.
                    is_qualified_lead_event=event_name.lower() in LIKELY_LEAD_EVENTS,
                    provenance=provenance.value,
                    raw_response_id=conversions_raw.id,
                    is_synthetic=synthetic,
                    data_label="SYNTHETIC DEMO DATA" if synthetic else None,
                )
            )

        connection.last_synced_at = utcnow()
        await self.session.flush()

        await emit(
            self.session,
            EventType.ANALYTICS_SYNCED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="integration_connection",
            aggregate_id=str(connection.id),
            payload={
                "provider": IntegrationProvider.GOOGLE_ANALYTICS_4.value,
                "traffic_rows": len(traffic_rows),
                "conversion_rows": len(conversion_rows),
                "mode": connection.mode,
                "provenance": provenance.value,
            },
        )
        return {
            "property_id": property_id,
            "traffic_rows": len(traffic_rows),
            "conversion_rows": len(conversion_rows),
            "mode": connection.mode,
            "provenance": provenance.value,
            "synthetic": synthetic,
            "window": {"start": start.isoformat(), "end": end.isoformat()},
        }

    async def organic_conversion_baseline(
        self, brand_id: uuid.UUID
    ) -> tuple[float | None, DataProvenance, str]:
        """Baseline for the 'qualified organic leads' mission.

        Returns ``(value, provenance, source)``. When nothing is connected the
        value is ``None`` — the mission then runs without a baseline and says so,
        rather than starting from an invented number.
        """
        from sqlalchemy import func, select

        repo = repository_for(GA4Conversion)(self.session, self.principal.tenant_id)
        statement = select(
            func.sum(GA4Conversion.conversions), func.min(GA4Conversion.provenance)
        ).where(
            GA4Conversion.tenant_id == self.principal.tenant_id,
            GA4Conversion.brand_id == brand_id,
            GA4Conversion.is_qualified_lead_event.is_(True),
            GA4Conversion.session_default_channel_group == "Organic Search",
        )
        row = (await self.session.execute(statement)).one_or_none()
        _ = repo
        if row is None or row[0] is None:
            return None, DataProvenance.UNKNOWN, "no analytics data available"
        return (
            float(row[0]),
            DataProvenance(row[1]) if row[1] else DataProvenance.UNKNOWN,
            "google_analytics_4",
        )


def _parse_date(value: str) -> date:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return date.today()


def _int(values: list[str], index: int) -> int:
    try:
        return int(float(values[index]))
    except (IndexError, ValueError):
        return 0


def _float(values: list[str], index: int) -> float:
    try:
        return float(values[index])
    except (IndexError, ValueError):
        return 0.0


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID | date | datetime):
        return str(value)
    return value


__all__ = ["IntegrationService"]
