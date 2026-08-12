"""Agent registry, run history and LLM usage accounting."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import PermissionLevel, RiskLevel
from seo_engine.shared.db import (
    Base,
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


class AgentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Platform-level agent catalogue, synchronised from the manifests on disk."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("agent_id", name="uq_agents_agent_id"),)

    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(64), default="analysis", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), default=RiskLevel.LOW, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    manifest_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)


class AgentCapabilityRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_capabilities"
    __table_args__ = (
        UniqueConstraint("agent_id", "capability", name="uq_agent_capabilities_agent_capability"),
    )

    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(120), nullable=False)
    permission: Mapped[str] = mapped_column(
        String(32), default=PermissionLevel.READ, nullable=False
    )


class AgentToolRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool", name="uq_agent_tools_agent_tool"),)

    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    permission: Mapped[str] = mapped_column(
        String(32), default=PermissionLevel.READ, nullable=False
    )


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "agent_runs"

    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    synthesis_mode: Mapped[str] = mapped_column(String(32), default="deterministic", nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    security_flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    tools_used: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    memory_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMessage(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Structured, non-chain-of-thought record of what an agent did.

    Only observable channels are stored: the objective, tool invocations, tool
    results and the final output.  Private model reasoning is never persisted or
    exposed (Rule 8).
    """

    __tablename__ = "agent_messages"

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_untrusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class AgentOutput(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "agent_outputs"

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    output_type: Mapped[str] = mapped_column(String(64), default="result", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    schema_name: Mapped[str] = mapped_column(String(120), default="AgentResult", nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)


class LLMUsage(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "llm_usage"

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    prompt_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "AgentCapabilityRecord",
    "AgentMessage",
    "AgentOutput",
    "AgentRecord",
    "AgentRun",
    "AgentToolRecord",
    "LLMUsage",
]
