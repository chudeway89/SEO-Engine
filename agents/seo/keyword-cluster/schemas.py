"""Input and output contracts for SEO-005 (Keyword Cluster)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class KeywordClusterInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_findings: int = Field(default=15, ge=1, le=100)


class KeywordClusterOutput(BaseModel):
    brand_id: str
    clusters_analysed: int = 0
    clusters_with_pages: int = 0
    healthy_clusters: int = 0
    cannibalisation: list[dict[str, Any]] = Field(default_factory=list)
    structures: list[dict[str, Any]] = Field(default_factory=list)
