"""Input and output contracts for RES-006 (Source and Evidence)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SourceEvidenceInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_fetch: int = Field(default=8, ge=0, le=50)


class SourceEvidenceOutput(BaseModel):
    brand_id: str
    candidates: int = 0
    fetched: int = 0
    verified: int = 0
    new_sources: int = 0
    tiers: dict[str, int] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
