"""Input and output contracts for BRD-001."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BrandUnderstandingInput(BaseModel):
    brand_id: UUID


class CompletenessDimension(BaseModel):
    """How much of one part of the brand graph the customer has supplied."""

    dimension: str
    present: int
    expected_minimum: int
    complete: bool
    detail: str = ""

    @property
    def ratio(self) -> float:
        if self.expected_minimum <= 0:
            return 1.0
        return min(1.0, self.present / self.expected_minimum)


class BrandUnderstandingOutput(BaseModel):
    brand_id: str
    brand_name: str
    industry: str | None = None
    risk_category: str = "general"
    completeness: list[CompletenessDimension] = Field(default_factory=list)
    completeness_score: float = Field(ge=0, le=100, default=0)
    commercial_priorities: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    audience_vocabulary: list[str] = Field(default_factory=list)
    seed_topics: list[str] = Field(default_factory=list)
    approved_claims: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BrandUnderstandingInput",
    "BrandUnderstandingOutput",
    "CompletenessDimension",
]
