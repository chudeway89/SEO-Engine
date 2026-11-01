"""Input and output contracts for RES-001 (Search Research)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchResearchInput(BaseModel):
    brand_id: UUID
    max_queries: int = Field(default=500, ge=1, le=5000)


class SearchResearchOutput(BaseModel):
    brand_id: str
    measured: bool = False
    provenance: str = "unknown"
    landscape: dict[str, Any] = Field(default_factory=dict)
