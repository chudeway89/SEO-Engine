"""Input and output contracts for SEO-002 (On-Page SEO)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class OnPageInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_pages: int = Field(default=500, ge=1, le=5000)
    max_findings: int = Field(default=15, ge=1, le=100)


class OnPageOutput(BaseModel):
    brand_id: str
    pages_assessed: int = 0
    misaligned: int = 0
    average_alignment: float | None = None
    pages: list[dict[str, Any]] = Field(default_factory=list)
