"""Evidence contracts.

Rule 7: *every recommendation must have evidence or be explicitly labelled a
hypothesis.*  Evidence is the audit trail that lets the UI answer "why did SEO
Engine recommend this?".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from seo_engine.schemas.enums import (
    OBSERVED_EVIDENCE_TYPES,
    DataProvenance,
    EvidenceType,
    SourceTier,
)


class EvidenceRecord(BaseModel):
    """A single observation or inference supporting a conclusion."""

    model_config = ConfigDict(use_enum_values=False)

    id: str
    type: EvidenceType
    source: str = Field(description="System or provider that produced this evidence")
    reference: str = Field(default="", description="URL, query, page id or API path")
    observation: str = Field(description="Plain-language statement of what was seen")
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    observed_at: datetime
    provenance: DataProvenance = DataProvenance.OBSERVED
    source_tier: SourceTier | None = None

    @field_validator("observation")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence.observation must not be empty")
        return value.strip()

    @property
    def is_observation(self) -> bool:
        """True when this evidence records something measured, not concluded."""
        return self.type in OBSERVED_EVIDENCE_TYPES

    @property
    def is_inference(self) -> bool:
        return not self.is_observation


class SourceReference(BaseModel):
    """An external source cited by content research.  Never model-invented."""

    url: str
    title: str
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    tier: SourceTier
    supports_claim: str | None = None
    reliability: float = Field(ge=0.0, le=1.0, default=0.5)
    verified: bool = Field(
        default=False,
        description="True only when the URL was actually fetched by the platform.",
    )


__all__ = ["EvidenceRecord", "SourceReference"]
