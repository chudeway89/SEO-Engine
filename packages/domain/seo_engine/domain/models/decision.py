"""Evidence, opportunities, recommendations, actions, outcomes, policies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import (
    ActionStatus,
    DataProvenance,
    OpportunityStatus,
    RecommendationStatus,
    RiskLevel,
)
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


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("tenant_id", "ref", name="uq_evidence_tenant_ref"),)

    ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), default=DataProvenance.OBSERVED, nullable=False
    )
    source_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_observation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRelationship(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "evidence_relationships"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relationship: Mapped[str] = mapped_column(String(64), default="supports", nullable=False)


class Opportunity(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "opportunities"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    opportunity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_impact: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    seo_impact: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    effort: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    strategic_fit: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default=RiskLevel.LOW, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    priority_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=OpportunityStatus.DETECTED, nullable=False, index=True
    )
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    detected_by_agent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Recommendation(
    UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base
):
    __tablename__ = "recommendations"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    problem: Mapped[str] = mapped_column(Text, default="", nullable=False)
    opportunity_statement: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, default="", nullable=False)
    business_impact: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    seo_impact: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    effort: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default=RiskLevel.LOW, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    strategic_fit: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False, index=True)
    priority_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_hypothesis: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    dependencies: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    proposed_action: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    target_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approval_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=RecommendationStatus.PROPOSED, nullable=False, index=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Action(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_actions_idempotency"),
    )

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True
    )
    executor_agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default=RiskLevel.LOW, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    policy_decision: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ActionStatus.PROPOSED, nullable=False, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    integration_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionApproval(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "action_approvals"

    action_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    decided_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ActionOutcome(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Measured result of an executed action.  Fundamental to learning."""

    __tablename__ = "action_outcomes"

    action_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_window_days: Mapped[int] = mapped_column(Integer, default=28, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Experiment(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "experiments"

    brand_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    control: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    variant: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class Policy(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_policies_tenant_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), default="global", nullable=False, index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    risk_threshold: Mapped[str] = mapped_column(
        String(32), default=RiskLevel.MEDIUM, nullable=False
    )
    approval_mode: Mapped[str] = mapped_column(
        String(32), default="approval_required", nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


__all__ = [
    "Action",
    "ActionApproval",
    "ActionOutcome",
    "Evidence",
    "EvidenceRelationship",
    "Experiment",
    "Opportunity",
    "Policy",
    "Recommendation",
]
