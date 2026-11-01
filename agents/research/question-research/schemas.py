"""Input and output contracts for RES-005 (Question Research)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QuestionResearchInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_questions: int = Field(default=100, ge=1, le=1000)


class QuestionResearchOutput(BaseModel):
    brand_id: str
    questions_total: int = 0
    answered: int = 0
    unanswered: int = 0
    sources_used: list[str] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
