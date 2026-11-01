"""Input and output contracts for BRD-002 (Brand Profile)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BrandProfileInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None


class BrandProfileOutput(BaseModel):
    brand_id: str
    pages_compared: int = 0
    covered: list[dict[str, Any]] = Field(default_factory=list)
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    vocabulary: list[dict[str, Any]] = Field(default_factory=list)
    brand_graph_changed: bool = False
