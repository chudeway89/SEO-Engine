"""Input and output contracts for CNT-004 (Content Writer)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ContentWriterInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    brief_ids: list[UUID] = Field(default_factory=list)
    max_drafts: int = Field(default=3, ge=1, le=20)


class ContentWriterOutput(BaseModel):
    brand_id: str
    drafts_written: int = 0
    outlines: int = 0
    drafts: list[dict[str, Any]] = Field(default_factory=list)
    #: Briefs whose asset the writer must not overwrite, with the reason.
    skipped: list[dict[str, Any]] = Field(default_factory=list)
