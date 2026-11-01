"""Input and output contracts for SEO-004 (Search Intent)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchIntentInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_findings: int = Field(default=15, ge=1, le=100)


class SearchIntentOutput(BaseModel):
    brand_id: str
    pairs_assessed: int = 0
    mismatches: int = 0
    serp_refined: int = 0
    serp_synthetic: bool = False
    page_types: dict[str, int] = Field(default_factory=dict)
    assessments: list[dict[str, Any]] = Field(default_factory=list)
