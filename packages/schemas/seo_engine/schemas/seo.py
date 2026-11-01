"""SEO analysis contracts: issues, dimension scores, readiness reports."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from seo_engine.schemas.enums import (
    IssueSeverity,
    ObservationConfidenceClass,
    SEODimension,
)


class SEOIssue(BaseModel):
    """A deterministic finding produced by a rule, never by a model."""

    check_id: str
    title: str
    severity: IssueSeverity
    dimension: SEODimension
    url: str | None = None
    page_id: str | None = None
    detail: str = ""
    evidence_data: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""
    affected_urls: list[str] = Field(default_factory=list)

    @property
    def weight(self) -> float:
        return {
            IssueSeverity.CRITICAL: 10.0,
            IssueSeverity.HIGH: 6.0,
            IssueSeverity.MEDIUM: 3.0,
            IssueSeverity.LOW: 1.0,
            IssueSeverity.INFO: 0.0,
        }[self.severity]


class DimensionScore(BaseModel):
    dimension: SEODimension
    score: float = Field(ge=0, le=100)
    issues_count: int = 0
    critical_count: int = 0
    pages_evaluated: int = 0
    detail: str = ""
    evaluated: bool = True
    not_evaluated_reason: str | None = None


class SEOScorecard(BaseModel):
    """Multiple dimensions.  ``overall`` never replaces them."""

    dimensions: list[DimensionScore]
    overall: float = Field(ge=0, le=100)
    pages_evaluated: int = 0
    issues_total: int = 0
    method: str = (
        "Weighted deterministic rule engine. This is SEO Engine's internal health "
        "model, not a Google ranking score."
    )

    def dimension(self, dimension: SEODimension) -> DimensionScore | None:
        for item in self.dimensions:
            if item.dimension == dimension:
                return item
        return None


class TechnicalAuditReport(BaseModel):
    website_id: str
    crawl_job_id: str
    issues: list[SEOIssue] = Field(default_factory=list)
    scorecard: SEOScorecard
    pages_analysed: int = 0
    summary_counts: dict[str, int] = Field(default_factory=dict)


class AISearchSignal(BaseModel):
    """AI Search readiness signal.

    ``classification`` must be honest: OBSERVED for things measured, INFERRED for
    conclusions, UNKNOWN for anything that depends on proprietary internals.
    """

    key: str
    label: str
    classification: ObservationConfidenceClass
    value: Any = None
    detail: str = ""
    source: str = "system"


class AISearchReadinessReport(BaseModel):
    website_id: str
    signals: list[AISearchSignal] = Field(default_factory=list)
    readiness_score: float | None = Field(
        default=None,
        description="Derived only from OBSERVED and INFERRED signals; never from UNKNOWN ones.",
    )
    unknowns: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AgenticWebReadinessReport(BaseModel):
    website_id: str
    score: float = Field(ge=0, le=100)
    signals: dict[str, Any] = Field(default_factory=dict)
    issues: list[SEOIssue] = Field(default_factory=list)
    pages_evaluated: int = 0


__all__ = [
    "AISearchReadinessReport",
    "AISearchSignal",
    "AgenticWebReadinessReport",
    "DimensionScore",
    "SEOIssue",
    "SEOScorecard",
    "TechnicalAuditReport",
]
