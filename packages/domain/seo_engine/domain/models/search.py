"""Keyword, SERP and search-question tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import DataProvenance
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
from sqlalchemy.orm import Mapped, mapped_column


class Keyword(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("brand_id", "normalised", "country", name="uq_keywords_brand_norm"),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    normalised: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    country: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="seed", nullable=False)
    is_branded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_question: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    primary_intent: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("keyword_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mapped_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    mapping_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class KeywordVariant(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "keyword_variants"

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variant: Mapped[str] = mapped_column(Text, nullable=False)
    variant_type: Mapped[str] = mapped_column(String(64), default="lexical", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="expansion", nullable=False)


class KeywordCluster(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base
):
    __tablename__ = "keyword_clusters"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    head_keyword: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    keyword_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opportunity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    mapped_urls: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    recommended_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)


class KeywordMetricRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """A metric value for a keyword.  ``provenance`` is mandatory (Rule 14)."""

    __tablename__ = "keyword_metrics"

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.UNKNOWN, nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KeywordRanking(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "keyword_rankings"

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[float] = mapped_column(Float, nullable=False)
    device: Mapped[str] = mapped_column(String(32), default="desktop", nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    search_engine: Mapped[str] = mapped_column(String(32), default="google", nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="gsc", nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SERPSnapshotRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "serp_snapshots"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    engine: Mapped[str] = mapped_column(String(32), default="google", nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    device: Mapped[str] = mapped_column(String(32), default="desktop", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SERPResultRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "serp_results"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("serp_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_type: Mapped[str] = mapped_column(String(64), default="organic", nullable=False)
    is_brand: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SearchIntentRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Intent classification history, so reclassification is auditable."""

    __tablename__ = "search_intents"

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    distribution: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    primary_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    classifier: Mapped[str] = mapped_column(String(64), default="lexical_v1", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SearchQuestionRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "search_questions"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalised: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    answered_by_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


__all__ = [
    "Keyword",
    "KeywordCluster",
    "KeywordMetricRecord",
    "KeywordRanking",
    "KeywordVariant",
    "SERPResultRecord",
    "SERPSnapshotRecord",
    "SearchIntentRecord",
    "SearchQuestionRecord",
]
