"""Input and output contracts for CNT-007 (Content Evaluator)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentEvaluatorInput(BaseModel):
    brand_id: UUID
    asset_ids: list[UUID] = Field(default_factory=list)
    max_assets: int = Field(default=10, ge=1, le=100)


class ContentEvaluatorOutput(BaseModel):
    brand_id: str
    evaluated: int = 0
    passed: int = 0
    skipped: list[dict[str, str]] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)
