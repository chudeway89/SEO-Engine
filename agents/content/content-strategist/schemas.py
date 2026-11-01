"""Input and output contracts for CNT-001 (Content Strategist)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentStrategyInput(BaseModel):
    brand_id: UUID
    content_gaps: list[dict[str, Any]] = Field(default_factory=list)
    months: int = Field(default=6, ge=1, le=24)
    capacity_per_month: int = Field(default=4, ge=1, le=50)


class ContentStrategyOutput(BaseModel):
    brand_id: str
    scheduled: int = 0
    backlog: int = 0
    not_pursued: int = 0
    by_decision: dict[str, int] = Field(default_factory=dict)
    roadmap: dict[str, Any] = Field(default_factory=dict)
