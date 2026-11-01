"""Input and output contracts for CNT-008 (Content Repurposing)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentRepurposingInput(BaseModel):
    brand_id: UUID
    asset_ids: list[UUID] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=lambda: ["linkedin", "email", "faq"])
    max_assets: int = Field(default=5, ge=1, le=50)


class ContentRepurposingOutput(BaseModel):
    brand_id: str
    sources_used: int = 0
    derivatives: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
