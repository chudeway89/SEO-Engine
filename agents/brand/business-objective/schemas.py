"""Input and output contracts for BRD-003 (Business Objective)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BusinessObjectiveInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None


class BusinessObjectiveOutput(BaseModel):
    brand_id: str
    goals: int = 0
    measurable: int = 0
    connected_providers: list[str] = Field(default_factory=list)
    lead_events: list[str] = Field(default_factory=list)
    assessments: list[dict[str, Any]] = Field(default_factory=list)
