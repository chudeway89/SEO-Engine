"""Website, crawl and page-level tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import CrawlJobStatus
from seo_engine.shared.db import (
    Base,
    SyntheticDataMixin,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Website(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("brand_id", "domain", name="uq_websites_brand_domain"),)

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(8), default="https", nullable=False)
    base_path: Mapped[str] = mapped_column(String(255), default="/", nullable=False)
    cms: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    crawl_frequency: Mapped[str] = mapped_column(String(32), default="weekly", nullable=False)
    robots_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sitemap_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    crawl_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.domain}"


class CrawlJob(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "crawl_jobs"

    website_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=CrawlJobStatus.QUEUED, nullable=False)
    trigger: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    robots: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    sitemap_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    pages_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stopped_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    crawl_pages: Mapped[list[CrawlPageRecord]] = relationship(
        back_populates="crawl_job", cascade="all, delete-orphan"
    )


class CrawlPageRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Raw crawl observation for one URL in one job (immutable history)."""

    __tablename__ = "crawl_pages"

    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    html_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    redirect_chain: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    raw_extract: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: Extracted body copy.  ALWAYS untrusted — see shared.untrusted.
    text_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_untrusted_external_content: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    injection_findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    crawl_job: Mapped[CrawlJob] = relationship(back_populates="crawl_pages")


class Page(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Current known state of a URL (upserted from the newest crawl)."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("website_id", "url", name="uq_pages_website_url"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, default="/", nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexability: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    indexability_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    headings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    meta_robots: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    hreflang: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    internal_links_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    internal_links_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    external_links_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_orphan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    in_sitemap: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accessibility: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_untrusted_external_content: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PageLink(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "page_links"

    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rel: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_broken: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    target_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PageImage(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "page_images"

    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    src: Mapped[str] = mapped_column(Text, nullable=False)
    alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_alt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loading: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PageSchemaBlock(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "page_schema"

    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(32), default="json-ld", nullable=False)
    schema_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)


class PageIssue(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "page_issues"

    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    check_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    affected_urls: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebsiteScorecard(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Persisted dimension scores per audit run."""

    __tablename__ = "website_scorecards"

    website_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    dimensions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    overall: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    pages_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issues_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    method: Mapped[str] = mapped_column(Text, default="", nullable=False)


__all__ = [
    "CrawlJob",
    "CrawlPageRecord",
    "Page",
    "PageImage",
    "PageIssue",
    "PageLink",
    "PageSchemaBlock",
    "Website",
    "WebsiteScorecard",
]
