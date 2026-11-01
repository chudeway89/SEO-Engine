"""Input and output contracts for SEO-012 (Indexability)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IndexabilityInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_findings: int = Field(default=20, ge=1, le=200)


class IndexabilityOutput(BaseModel):
    brand_id: str
    pages_observed: int = 0
    sitemap_urls: int = 0
    sitemap_unverified: int = 0
    states: dict[str, int] = Field(default_factory=dict)
    issues_by_type: dict[str, int] = Field(default_factory=dict)
    gsc_compared: bool = False
    issues: list[dict[str, Any]] = Field(default_factory=list)
