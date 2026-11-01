"""Input and output contracts for RES-002 (SERP Research)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SERPResearchInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    queries: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=10, ge=1, le=100)
    country: str | None = None
    device: str = "desktop"


class SERPResearchOutput(BaseModel):
    brand_id: str
    queries_requested: list[str] = Field(default_factory=list)
    queries_failed: list[dict[str, str]] = Field(default_factory=list)
    questions_recorded: int = 0
    synthetic: bool = False
    landscape: dict[str, Any] = Field(default_factory=dict)
