"""Input and output contracts for ORCH-001 (Brand and Strategy Orchestrator)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class StrategyInput(BaseModel):
    brand_id: UUID
    objective: str | None = None
    website_id: UUID | None = None


class StrategyOutput(BaseModel):
    brand_id: str
    objective: str
    mission_type: str
    target_metric: str | None = None
    stages: list[dict[str, Any]] = Field(default_factory=list)
    excluded: list[dict[str, Any]] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
