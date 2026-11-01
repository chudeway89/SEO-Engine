"""Input and output contracts for PUB-001 (Publishing)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PublishingInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    asset_ids: list[UUID] = Field(default_factory=list)
    publish: bool = True
    max_assets: int = Field(default=10, ge=1, le=100)


class PublishingOutput(BaseModel):
    brand_id: str
    considered: int = 0
    awaiting_editorial_approval: int = 0
    blocked: list[dict[str, Any]] = Field(default_factory=list)
    awaiting_action_approval: list[dict[str, Any]] = Field(default_factory=list)
    published: list[dict[str, Any]] = Field(default_factory=list)
    failed: list[dict[str, Any]] = Field(default_factory=list)
