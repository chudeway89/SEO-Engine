"""Integration connections, credentials and provider data tables.

Raw provider responses are stored separately from normalised records so that a
normalisation bug can be replayed and so no analysis silently rewrites history.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from seo_engine.schemas.enums import DataProvenance, IntegrationMode, IntegrationStatus
from seo_engine.shared.db import (
    Base,
    SyntheticDataMixin,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class IntegrationConnection(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Generic connection record for every provider."""

    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "brand_id", "provider", name="uq_integration_connections_scope"
        ),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=IntegrationStatus.NOT_CONNECTED, nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(32), default=IntegrationMode.DEVELOPMENT_ADAPTER, nullable=False
    )
    account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class IntegrationCredential(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Only *references* and encrypted material live here — never plaintext."""

    __tablename__ = "integration_credentials"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Fernet-encrypted payload when the local secret provider is in use.
    encrypted_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderRawResponse(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Untouched provider payloads, kept separate from normalised tables."""

    __tablename__ = "provider_raw_responses"

    connection_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(
        String(32), default=IntegrationMode.DEVELOPMENT_ADAPTER, nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Google Search Console
# ---------------------------------------------------------------------------
class GSCConnection(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "gsc_connections"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    google_account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    selected_property: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(32), default=IntegrationMode.DEVELOPMENT_ADAPTER, nullable=False
    )


class GSCProperty(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "gsc_properties"
    __table_args__ = (
        UniqueConstraint("gsc_connection_id", "site_url", name="uq_gsc_properties_site"),
    )

    gsc_connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("gsc_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    site_url: Mapped[str] = mapped_column(String(500), nullable=False)
    permission_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    property_type: Mapped[str] = mapped_column(String(32), default="url_prefix", nullable=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GSCPerformance(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base
):
    __tablename__ = "gsc_performance"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    website_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    site_url: Mapped[str] = mapped_column(String(500), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True)
    search_appearance: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    raw_response_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class GSCInspection(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "gsc_inspections"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    site_url: Mapped[str] = mapped_column(String(500), nullable=False)
    inspected_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    verdict: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coverage_state: Mapped[str | None] = mapped_column(String(200), nullable=True)
    indexing_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    robots_txt_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_fetch_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    google_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_response_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    inspected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GSCSitemap(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "gsc_sitemaps"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    site_url: Mapped[str] = mapped_column(String(500), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sitemap_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_sitemaps_index: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warnings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_urls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    indexed_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_submitted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_downloaded: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# Google Analytics 4
# ---------------------------------------------------------------------------
class GA4Connection(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "ga4_connections"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    google_account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    selected_property_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(32), default=IntegrationMode.DEVELOPMENT_ADAPTER, nullable=False
    )


class GA4Property(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "ga4_properties"
    __table_args__ = (
        UniqueConstraint("ga4_connection_id", "property_id", name="uq_ga4_properties_property"),
    )

    ga4_connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ga4_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    time_zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GA4Metric(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "ga4_metrics"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    landing_page: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_default_channel_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engaged_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_session_duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    raw_response_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class GA4Conversion(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base
):
    __tablename__ = "ga4_conversions"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    landing_page: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_default_channel_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event_count: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conversions: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    event_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_qualified_lead_event: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    raw_response_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


__all__ = [
    "GA4Connection",
    "GA4Conversion",
    "GA4Metric",
    "GA4Property",
    "GSCConnection",
    "GSCInspection",
    "GSCPerformance",
    "GSCProperty",
    "GSCSitemap",
    "IntegrationConnection",
    "IntegrationCredential",
    "ProviderRawResponse",
]
