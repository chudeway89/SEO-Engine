"""Input and output contracts for POL-001 (Policy Guardian)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PolicyReviewInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    asset_ids: list[UUID] = Field(default_factory=list)
    max_assets: int = Field(default=20, ge=1, le=200)


class PolicyReviewOutput(BaseModel):
    brand_id: str
    drafts_checked: int = 0
    drafts_compliant: int = 0
    returned_to_draft: int = 0
    actions_checked: int = 0
    actions_needing_attention: list[dict[str, Any]] = Field(default_factory=list)
    content: list[dict[str, Any]] = Field(default_factory=list)
