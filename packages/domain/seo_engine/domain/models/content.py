"""Content assets, versions, briefs, research, sources, evaluations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import ContentAssetType, ContentStatus, RiskCategory
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


class ContentAsset(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "content_assets"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    asset_type: Mapped[str] = mapped_column(
        String(64), default=ContentAssetType.ARTICLE, nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(String(300), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=ContentStatus.DRAFT, nullable=False)
    risk_category: Mapped[str] = mapped_column(
        String(32), default=RiskCategory.GENERAL, nullable=False
    )
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    primary_keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    canonical_source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    external_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list[ContentVersion]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="ContentVersion.version"
    )


class ContentVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Immutable content version.  Previous versions are never overwritten."""

    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("content_asset_id", "version", name="uq_content_versions_asset_version"),
    )

    content_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    meta_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    synthesis_mode: Mapped[str] = mapped_column(String(32), default="deterministic", nullable=False)
    created_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by_user: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    brief_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    asset: Mapped[ContentAsset] = relationship(back_populates="versions")


class ContentBriefRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "content_briefs"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    content_asset_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), default="create", nullable=False)
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)


class ContentResearchRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "content_research"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    brief_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    questions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    competitor_coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ContentSource(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """A cited source.  ``verified`` is true only if the platform fetched it."""

    __tablename__ = "content_sources"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    research_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    content_asset_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tier: Mapped[str] = mapped_column(String(32), default="tier_6_unverified", nullable=False)
    reliability: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    supports_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentEvaluationRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "content_evaluations"

    content_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    evaluation_type: Mapped[str] = mapped_column(String(64), default="quality_gate", nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    blocking_failures: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evaluated_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ContentRepresentation(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """A derivative of a canonical asset (repurposing output)."""

    __tablename__ = "content_representation"

    content_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    audience: Mapped[str] = mapped_column(Text, default="", nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    format: Mapped[str] = mapped_column(String(64), default="post", nullable=False)
    tone: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    cta: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    canonical_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)


class ContentRepair(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """A tracked remediation applied to content after an evaluation failure."""

    __tablename__ = "content_repairs"

    content_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    repair_type: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resulting_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performed_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)


__all__ = [
    "ContentAsset",
    "ContentBriefRecord",
    "ContentEvaluationRecord",
    "ContentRepair",
    "ContentRepresentation",
    "ContentResearchRecord",
    "ContentSource",
    "ContentVersion",
]
