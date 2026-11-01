"""Input and output contracts for CMP-001 (Competitor Discovery)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CompetitorDiscoveryInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    minimum_appearances: int = Field(default=2, ge=1, le=20)


class CompetitorDiscoveryOutput(BaseModel):
    brand_id: str
    serps_analysed: int = 0
    synthetic: bool = False
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    recorded_observed: list[dict[str, Any]] = Field(default_factory=list)
    recorded_not_observed: list[str] = Field(default_factory=list)
    brand_graph_changed: bool = False
