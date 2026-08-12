"""Brand graph: the institutional model of the customer's business."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from seo_engine.schemas.enums import CompetitorType, RiskLevel
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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Brand(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "brands"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    primary_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    business_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_category: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    goals: Mapped[list[BrandGoal]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    services: Mapped[list[BrandService]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    products: Mapped[list[BrandProduct]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    audiences: Mapped[list[BrandAudience]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    locations: Mapped[list[BrandLocation]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    competitors: Mapped[list[BrandCompetitor]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


def _brand_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class BrandGoal(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_goals"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    goal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="goals")


class BrandService(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_services"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    landing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    revenue_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="services")


class BrandProduct(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_products"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    landing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="products")


class BrandAudience(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_audiences"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pains: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    vocabulary: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="audiences")


class BrandLocation(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_locations"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_area: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    landing_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gbp_location_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="locations")


class BrandClaim(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Approved commercial claims.  Writers must retrieve these before drafting."""

    __tablename__ = "brand_claims"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    risk: Mapped[str] = mapped_column(String(32), default=RiskLevel.LOW, nullable=False)
    is_prohibited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BrandVoiceProfile(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_voice_profiles"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    tone: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reading_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    person: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_terminology: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    forbidden_terminology: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    style_rules: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    examples: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BrandCompetitor(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "brand_competitors"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    competitor_types: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: [CompetitorType.BUSINESS.value], nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    discovered_via: Mapped[str] = mapped_column(String(64), default="user", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_analysed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    brand: Mapped[Brand] = relationship(back_populates="competitors")


class CompetitorObservation(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "competitor_observations"

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_competitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="crawl", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Project(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Strategic container giving agents scope context."""

    __tablename__ = "projects"

    brand_id: Mapped[uuid.UUID] = _brand_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


__all__ = [
    "Brand",
    "BrandAudience",
    "BrandClaim",
    "BrandCompetitor",
    "BrandGoal",
    "BrandLocation",
    "BrandProduct",
    "BrandService",
    "BrandVoiceProfile",
    "CompetitorObservation",
    "Project",
]
