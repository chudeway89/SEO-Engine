"""Input and output contracts for CNT-003 (Content Brief)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentBriefInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    research: list[dict[str, Any]] = Field(default_factory=list)
    max_briefs: int = Field(default=3, ge=1, le=20)


class ContentBriefOutput(BaseModel):
    brand_id: str
    briefs_written: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    briefs: list[dict[str, Any]] = Field(default_factory=list)
