"""Input and output contracts for CNT-002 (Content Research)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentResearchInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    topics: list[dict[str, Any]] = Field(default_factory=list)
    max_topics: int = Field(default=3, ge=1, le=20)


class ContentResearchOutput(BaseModel):
    brand_id: str
    researched: int = 0
    packs: list[dict[str, Any]] = Field(default_factory=list)
