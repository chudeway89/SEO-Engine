"""Input and output contracts for CNT-009 (Content Quality Guardian)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QualityGateInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    asset_ids: list[UUID] = Field(default_factory=list)
    max_assets: int = Field(default=10, ge=1, le=100)


class QualityGateOutput(BaseModel):
    brand_id: str
    gated: int = 0
    passed: int = 0
    moved_to_review: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
