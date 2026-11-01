"""Input and output contracts for QUAL-001 (Quality Guardian)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QualityAuditInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    limit: int = Field(default=200, ge=1, le=2000)


class QualityAuditOutput(BaseModel):
    brand_id: str
    audited: int = 0
    clean: int = 0
    quality_score: float = 100.0
    by_rule: dict[str, int] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list)
