"""Input and output contracts for CNT-005 (Content Optimisation)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentOptimisationInput(BaseModel):
    brand_id: UUID
    asset_ids: list[UUID] = Field(default_factory=list)
    max_assets: int = Field(default=10, ge=1, le=100)


class ContentOptimisationOutput(BaseModel):
    brand_id: str
    assets_reviewed: int = 0
    edits_proposed: int = 0
    edits: list[dict[str, Any]] = Field(default_factory=list)
