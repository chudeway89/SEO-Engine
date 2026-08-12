"""Missions, tasks and the task graph."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.schemas.enums import (
    AutomationPolicy,
    MissionStatus,
    TaskPriority,
    TaskStatus,
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


class Mission(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    """A persistent objective.  The core object of the platform."""

    __tablename__ = "missions"

    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    mission_type: Mapped[str] = mapped_column(String(64), default="generic", nullable=False)
    target_metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    baseline_provenance: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    automation_policy: Mapped[str] = mapped_column(
        String(32), default=AutomationPolicy.APPROVAL_REQUIRED, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default=MissionStatus.CREATED, nullable=False)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    plan_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Task(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "tasks"

    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING, nullable=False, index=True
    )
    priority: Mapped[str] = mapped_column(String(16), default=TaskPriority.NORMAL, nullable=False)
    risk: Mapped[str] = mapped_column(String(32), default="low", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    required_capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    allowed_tools: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    approval_policy: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskDependency(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_edge"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    condition: Mapped[str] = mapped_column(String(64), default="completed", nullable=False)


class MissionTask(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """The mission's planned task graph node (stage, ordering, necessity)."""

    __tablename__ = "mission_tasks"
    __table_args__ = (UniqueConstraint("mission_id", "task_id", name="uq_mission_tasks_link"),)

    mission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    selection_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MissionMetric(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "mission_metrics"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MissionProgress(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "mission_progress"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    percent_complete: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = [
    "Mission",
    "MissionMetric",
    "MissionProgress",
    "MissionTask",
    "Task",
    "TaskDependency",
]
