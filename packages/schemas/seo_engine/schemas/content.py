"""Content engine contracts: briefs, drafts, evaluations, repurposing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from seo_engine.schemas.enums import (
    ContentAssetType,
    ContentDecision,
    RiskCategory,
    SearchIntent,
)
from seo_engine.schemas.evidence import SourceReference


class InternalLinkTarget(BaseModel):
    url: str
    anchor_text: str
    reason: str = ""


class ContentBrief(BaseModel):
    """The definitive instruction set for the writer agent."""

    title: str
    primary_topic: str
    primary_keyword: str | None = None
    secondary_keywords: list[str] = Field(default_factory=list)
    search_intent: list[SearchIntent] = Field(default_factory=list)
    audience: str
    business_goal: str
    unique_value_proposition: str
    required_sections: list[str] = Field(default_factory=list)
    questions_to_answer: list[str] = Field(default_factory=list)
    authoritative_sources: list[SourceReference] = Field(default_factory=list)
    internal_links: list[InternalLinkTarget] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    claims_requiring_verification: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    approved_claims: list[str] = Field(default_factory=list)
    cta: str | None = None

    content_type: ContentAssetType = ContentAssetType.ARTICLE
    risk_category: RiskCategory = RiskCategory.GENERAL
    target_word_count: int = 1200
    tone: str = "professional, plain-language, evidence-led"
    decision: ContentDecision = ContentDecision.CREATE
    target_url: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ContentSection(BaseModel):
    heading: str
    level: int = 2
    body: str
    supports_question: str | None = None
    source_urls: list[str] = Field(default_factory=list)


class ContentDraft(BaseModel):
    title: str
    meta_description: str
    slug: str
    sections: list[ContentSection] = Field(default_factory=list)
    body_markdown: str = ""
    word_count: int = 0
    internal_links: list[InternalLinkTarget] = Field(default_factory=list)
    cited_sources: list[SourceReference] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    schema_recommendation: dict[str, Any] | None = None
    cta: str | None = None
    unverified_claims: list[str] = Field(default_factory=list)
    synthesis_mode: str = "deterministic"


class EvaluationCriterionResult(BaseModel):
    criterion: str
    score: float = Field(ge=0, le=100)
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


CONTENT_EVALUATION_CRITERIA: tuple[str, ...] = (
    "search_intent",
    "accuracy",
    "source_quality",
    "originality",
    "usefulness",
    "completeness",
    "brand_alignment",
    "readability",
    "internal_linking",
    "structured_data_suitability",
    "conversion_relevance",
    "risk",
)


class ContentEvaluation(BaseModel):
    criteria: list[EvaluationCriterionResult] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100, default=0)
    passed: bool = False
    blocking_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    keyword_stuffing_detected: bool = False
    requires_human_review: bool = False

    def criterion(self, name: str) -> EvaluationCriterionResult | None:
        for item in self.criteria:
            if item.criterion == name:
                return item
        return None


class ContentUpdatePlan(BaseModel):
    target_url: str
    outdated_information: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    weak_sections: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    sections_to_add: list[str] = Field(default_factory=list)
    sections_to_rewrite: list[str] = Field(default_factory=list)
    internal_links_to_add: list[InternalLinkTarget] = Field(default_factory=list)
    metadata_changes: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


REPURPOSE_PLATFORMS: tuple[str, ...] = (
    "linkedin",
    "instagram",
    "facebook",
    "x",
    "youtube_script",
    "short_form_video_script",
    "email",
    "newsletter",
    "carousel",
    "faq",
    "press_angle",
    "sales_enablement",
)


class RepurposedAsset(BaseModel):
    platform: str
    audience: str
    objective: str
    format: str
    tone: str
    cta: str
    body: str
    canonical_source_url: str | None = None
    canonical_content_asset_id: str | None = None


__all__ = [
    "CONTENT_EVALUATION_CRITERIA",
    "REPURPOSE_PLATFORMS",
    "ContentBrief",
    "ContentDraft",
    "ContentEvaluation",
    "ContentSection",
    "ContentUpdatePlan",
    "EvaluationCriterionResult",
    "InternalLinkTarget",
    "RepurposedAsset",
]
