"""Input and output contracts for CNT-006 (Content Update)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentUpdateInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    content_gaps: list[dict[str, Any]] = Field(default_factory=list)
    max_pages: int = Field(default=5, ge=1, le=50)


class ContentUpdateOutput(BaseModel):
    brand_id: str
    pages_planned: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
