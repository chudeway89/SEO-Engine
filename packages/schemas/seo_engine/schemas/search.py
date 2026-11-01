"""Keyword, intent, SERP and competitor contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator
from seo_engine.schemas.enums import (
    CompetitorType,
    ContentDecision,
    DataProvenance,
    SearchIntent,
)


class IntentDistribution(BaseModel):
    """Probabilistic search intent.  Probabilities sum to 1.0."""

    informational: float = 0.0
    commercial: float = 0.0
    transactional: float = 0.0
    navigational: float = 0.0
    local: float = 0.0
    investigational: float = 0.0

    @model_validator(mode="after")
    def _normalise(self) -> IntentDistribution:
        total = sum(self.model_dump().values())
        if total <= 0:
            self.informational = 1.0
            return self
        for key, value in self.model_dump().items():
            setattr(self, key, round(value / total, 4))
        return self

    @property
    def primary(self) -> SearchIntent:
        data = self.model_dump()
        return SearchIntent(max(data, key=lambda k: data[k]))

    @property
    def primary_probability(self) -> float:
        return max(self.model_dump().values())

    def as_dict(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v > 0}


class KeywordMetric(BaseModel):
    """A metric for a keyword, always carrying its provenance.

    Rule 14: the platform never fabricates volume, difficulty or CPC.  When no
    provider is connected the value stays ``None`` and provenance is UNKNOWN.
    """

    name: str
    value: float | None = None
    unit: str | None = None
    provenance: DataProvenance = DataProvenance.UNKNOWN
    source: str | None = None
    observed_at: datetime | None = None
    note: str | None = None


class KeywordScoreBreakdown(BaseModel):
    """SEO Engine's internal opportunity model — not a Google ranking formula."""

    business_relevance: float = Field(ge=0, le=100, default=0)
    intent_value: float = Field(ge=0, le=100, default=0)
    demand: float = Field(ge=0, le=100, default=0)
    ranking_feasibility: float = Field(ge=0, le=100, default=0)
    competitive_gap: float = Field(ge=0, le=100, default=0)
    conversion_potential: float = Field(ge=0, le=100, default=0)

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "business_relevance": 0.30,
            "intent_value": 0.20,
            "demand": 0.15,
            "ranking_feasibility": 0.15,
            "competitive_gap": 0.10,
            "conversion_potential": 0.10,
        }
    )
    dimensions_with_observed_data: list[str] = Field(default_factory=list)

    @property
    def opportunity_score(self) -> float:
        values = self.model_dump()
        return round(
            sum(values[key] * weight for key, weight in self.weights.items()),
            2,
        )


class KeywordRecord(BaseModel):
    keyword: str
    normalised: str
    language: str = "en"
    country: str | None = None
    is_branded: bool = False
    is_local: bool = False
    is_question: bool = False
    source: str = "seed"
    variants: list[str] = Field(default_factory=list)
    intent: IntentDistribution = Field(default_factory=IntentDistribution)
    metrics: list[KeywordMetric] = Field(default_factory=list)
    score: KeywordScoreBreakdown = Field(default_factory=KeywordScoreBreakdown)
    mapped_url: str | None = None
    mapping_confidence: float = 0.0
    cluster_id: str | None = None

    def metric(self, name: str) -> KeywordMetric | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None


class KeywordCluster(BaseModel):
    id: str
    label: str
    head_keyword: str
    keywords: list[str] = Field(default_factory=list)
    intent: IntentDistribution = Field(default_factory=IntentDistribution)
    opportunity_score: float = 0.0
    mapped_urls: list[str] = Field(default_factory=list)
    coverage: float = Field(ge=0, le=1, default=0.0)
    recommended_decision: ContentDecision | None = None


class SERPResultItem(BaseModel):
    position: int
    url: str
    title: str | None = None
    snippet: str | None = None
    domain: str
    result_type: str = "organic"


class SERPSnapshot(BaseModel):
    query: str
    engine: str = "google"
    country: str | None = None
    device: str = "desktop"
    observed_at: datetime
    provider: str
    provenance: DataProvenance = DataProvenance.OBSERVED
    results: list[SERPResultItem] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    available: bool = True
    unavailable_reason: str | None = None


class SearchQuestion(BaseModel):
    question: str
    source: str
    intent: IntentDistribution = Field(default_factory=IntentDistribution)
    answered_by_url: str | None = None
    provenance: DataProvenance = DataProvenance.OBSERVED


class CompetitorProfile(BaseModel):
    name: str
    domain: str
    types: list[CompetitorType] = Field(default_factory=list)
    priority: int = Field(ge=1, le=5, default=3)
    discovered_via: str = "user"
    notes: str = ""
    pages_analysed: int = 0
    topics_covered: list[str] = Field(default_factory=list)
    observed_urls: list[str] = Field(default_factory=list)


class KeywordGap(BaseModel):
    keyword: str
    competitor_domains: list[str] = Field(default_factory=list)
    brand_covers: bool = False
    brand_url: str | None = None
    evidence_ref: str = ""
    opportunity_score: float = 0.0


class ContentGap(BaseModel):
    topic: str
    cluster_id: str | None = None
    brand_coverage: float = Field(ge=0, le=1, default=0.0)
    brand_urls: list[str] = Field(default_factory=list)
    competitor_coverage: float = Field(ge=0, le=1, default=0.0)
    competitor_urls: list[str] = Field(default_factory=list)
    serp_coverage: float = Field(ge=0, le=1, default=0.0)
    demand_signal: float | None = None
    demand_provenance: DataProvenance = DataProvenance.UNKNOWN
    intent: IntentDistribution = Field(default_factory=IntentDistribution)
    existing_page_quality: float | None = None
    decision: ContentDecision = ContentDecision.DO_NOTHING
    decision_reason: str = ""
    target_url: str | None = None
    consolidate_urls: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


class KeywordResearchReport(BaseModel):
    brand_id: str
    keywords: list[KeywordRecord] = Field(default_factory=list)
    clusters: list[KeywordCluster] = Field(default_factory=list)
    questions: list[SearchQuestion] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    metrics_available: bool = False
    limitations: list[str] = Field(default_factory=list)


class CompetitorAnalysisReport(BaseModel):
    brand_id: str
    competitors: list[CompetitorProfile] = Field(default_factory=list)
    keyword_gaps: list[KeywordGap] = Field(default_factory=list)
    content_gaps: list[ContentGap] = Field(default_factory=list)
    coverage_comparison: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


__all__ = [
    "CompetitorAnalysisReport",
    "CompetitorProfile",
    "ContentGap",
    "IntentDistribution",
    "KeywordCluster",
    "KeywordGap",
    "KeywordMetric",
    "KeywordRecord",
    "KeywordResearchReport",
    "KeywordScoreBreakdown",
    "SERPResultItem",
    "SERPSnapshot",
    "SearchQuestion",
]
