"""Event store and audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.shared.db import (
    Base,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class EventRecord(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Append-only internal event store."""

    __tablename__ = "events"

    event_ref: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    aggregate_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="system", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Who did what, when, why, with which evidence, under which policy."""

    __tablename__ = "audit_logs"

    actor_type: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="success", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    policy_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = ["AuditLog", "EventRecord"]
