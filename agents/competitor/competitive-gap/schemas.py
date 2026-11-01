"""Input and output contracts for CMP-003 (Competitive Gap)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CompetitiveGapInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    keyword_gaps: list[dict[str, Any]] = Field(default_factory=list)
    discovered_competitors: list[str] = Field(default_factory=list)
    max_findings: int = Field(default=15, ge=1, le=100)


class CompetitiveGapOutput(BaseModel):
    brand_id: str
    gaps_total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    synthetic_serp: bool = False
    scoring: str = ""
    gaps: list[dict[str, Any]] = Field(default_factory=list)
