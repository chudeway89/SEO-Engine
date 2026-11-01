"""Opportunity detection and prioritisation.

Opportunities are derived from things the platform *observed* — technical
issues, content gaps, keyword positions, analytics — and each carries the
evidence that produced it. An opportunity with no evidence is not created.

Prioritisation uses the documented internal formula:

    priority = impact x confidence x strategic_fit / effort

normalised to 0-100. It is SEO Engine's model for ordering work, and is
explicitly not a claim about how Google ranks anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_engine.schemas.enums import (
    ContentDecision,
    IssueSeverity,
    OpportunityType,
    RiskLevel,
)
from seo_engine.schemas.search import ContentGap, KeywordGap, KeywordRecord
from seo_engine.schemas.seo import SEOIssue

#: Effort in the 1-10 band the recommendation schema uses.
EFFORT_BY_CHECK: dict[str, float] = {
    "missing_title": 1.0,
    "title_length": 1.0,
    "missing_meta_description": 1.0,
    "duplicate_meta_description": 2.0,
    "missing_h1": 1.0,
    "multiple_h1": 1.0,
    "missing_canonical": 2.0,
    "canonical_mismatch": 3.0,
    "noindex": 2.0,
    "http_4xx": 4.0,
    "http_5xx": 5.0,
    "broken_internal_link": 2.0,
    "redirect_chain": 3.0,
    "orphan_page": 2.0,
    "thin_content": 6.0,
    "duplicate_content": 6.0,
    "empty_page": 7.0,
    "missing_image_alt": 2.0,
    "invalid_structured_data": 3.0,
    "missing_structured_data": 4.0,
    "hreflang_no_return_tag": 3.0,
    "mixed_protocol": 6.0,
    "sitemap_missing": 2.0,
    "javascript_dependent_content": 9.0,
    "unlabelled_form_controls": 3.0,
    "unnamed_interactive_elements": 3.0,
    "no_conversion_path": 4.0,
    "no_semantic_landmarks": 3.0,
}

#: Which issues map to which opportunity type.
TYPE_BY_CHECK: dict[str, OpportunityType] = {
    "missing_title": OpportunityType.ON_PAGE,
    "duplicate_title": OpportunityType.ON_PAGE,
    "title_length": OpportunityType.CTR_IMPROVEMENT,
    "missing_meta_description": OpportunityType.CTR_IMPROVEMENT,
    "duplicate_meta_description": OpportunityType.CTR_IMPROVEMENT,
    "meta_description_length": OpportunityType.CTR_IMPROVEMENT,
    "missing_h1": OpportunityType.ON_PAGE,
    "multiple_h1": OpportunityType.ON_PAGE,
    "heading_order": OpportunityType.AI_SEARCH_READINESS,
    "missing_canonical": OpportunityType.INDEXABILITY,
    "canonical_mismatch": OpportunityType.INDEXABILITY,
    "noindex": OpportunityType.INDEXABILITY,
    "sitemap_missing": OpportunityType.INDEXABILITY,
    "sitemap_url_not_indexable": OpportunityType.INDEXABILITY,
    "page_not_in_sitemap": OpportunityType.INDEXABILITY,
    "http_4xx": OpportunityType.TECHNICAL_FIX,
    "http_5xx": OpportunityType.TECHNICAL_FIX,
    "fetch_error": OpportunityType.TECHNICAL_FIX,
    "redirect_chain": OpportunityType.TECHNICAL_FIX,
    "mixed_protocol": OpportunityType.TECHNICAL_FIX,
    "hreflang_no_return_tag": OpportunityType.TECHNICAL_FIX,
    "broken_internal_link": OpportunityType.INTERNAL_LINKING,
    "orphan_page": OpportunityType.INTERNAL_LINKING,
    "nofollow_internal_links": OpportunityType.INTERNAL_LINKING,
    "thin_content": OpportunityType.CONTENT_UPDATE,
    "duplicate_content": OpportunityType.CONTENT_CONSOLIDATE,
    "empty_page": OpportunityType.CONTENT_UPDATE,
    "missing_structured_data": OpportunityType.STRUCTURED_DATA,
    "invalid_structured_data": OpportunityType.STRUCTURED_DATA,
    "missing_image_alt": OpportunityType.AI_SEARCH_READINESS,
    "javascript_dependent_content": OpportunityType.AI_SEARCH_READINESS,
    "no_semantic_landmarks": OpportunityType.AGENTIC_WEB_READINESS,
    "unnamed_interactive_elements": OpportunityType.AGENTIC_WEB_READINESS,
    "unlabelled_form_controls": OpportunityType.CONVERSION,
    "no_conversion_path": OpportunityType.CONVERSION,
    "missing_lang_attribute": OpportunityType.AI_SEARCH_READINESS,
    "positive_tabindex": OpportunityType.AGENTIC_WEB_READINESS,
}

SEVERITY_IMPACT: dict[IssueSeverity, float] = {
    IssueSeverity.CRITICAL: 9.0,
    IssueSeverity.HIGH: 7.0,
    IssueSeverity.MEDIUM: 5.0,
    IssueSeverity.LOW: 3.0,
    IssueSeverity.INFO: 1.0,
}

SEVERITY_RISK: dict[IssueSeverity, RiskLevel] = {
    IssueSeverity.CRITICAL: RiskLevel.MEDIUM,
    IssueSeverity.HIGH: RiskLevel.LOW,
    IssueSeverity.MEDIUM: RiskLevel.LOW,
    IssueSeverity.LOW: RiskLevel.LOW,
    IssueSeverity.INFO: RiskLevel.LOW,
}

PRIORITY_FORMULA = (
    "priority = impact x confidence x strategic_fit / effort, normalised to 0-100. "
    "This is SEO Engine's internal model for ordering work. It is not a Google "
    "ranking formula and makes no claim about ranking outcomes."
)


@dataclass(slots=True)
class DetectedOpportunity:
    """An opportunity before it is persisted."""

    opportunity_type: OpportunityType
    title: str
    description: str
    business_impact: float
    seo_impact: float
    effort: float
    confidence: float
    strategic_fit: float = 0.7
    risk: RiskLevel = RiskLevel.LOW
    target_entity_type: str | None = None
    target_entity_id: str | None = None
    target_url: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    priority_score: float = 0.0
    priority_breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def impact(self) -> float:
        """Combined impact, business-weighted (Rule 12: business relevance leads)."""
        return round(0.6 * self.business_impact + 0.4 * self.seo_impact, 3)


def prioritise(opportunity: DetectedOpportunity) -> DetectedOpportunity:
    """Apply the documented priority formula and record the working."""
    effort = max(opportunity.effort, 0.5)
    raw = (opportunity.impact * opportunity.confidence * opportunity.strategic_fit) / effort

    # The theoretical maximum is impact 10 x confidence 1 x fit 1 / effort 0.5.
    normalised = min(100.0, (raw / 20.0) * 100.0)

    opportunity.priority_score = round(normalised, 2)
    opportunity.priority_breakdown = {
        "impact": opportunity.impact,
        "business_impact": opportunity.business_impact,
        "seo_impact": opportunity.seo_impact,
        "confidence": opportunity.confidence,
        "strategic_fit": opportunity.strategic_fit,
        "effort": effort,
        "raw": round(raw, 4),
        "formula": PRIORITY_FORMULA,
    }
    return opportunity


def prioritise_all(opportunities: list[DetectedOpportunity]) -> list[DetectedOpportunity]:
    scored = [prioritise(o) for o in opportunities]
    scored.sort(key=lambda o: (-o.priority_score, o.title))
    return scored


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
def from_technical_issues(
    issues: list[SEOIssue],
    *,
    evidence_by_check: dict[str, str] | None = None,
    pages_total: int = 1,
    commercial_urls: set[str] | None = None,
) -> list[DetectedOpportunity]:
    """Group issues by check into one opportunity per check type.

    Grouping matters: fifty missing meta descriptions are one piece of work, not
    fifty competing recommendations.
    """
    grouped: dict[str, list[SEOIssue]] = {}
    for issue in issues:
        grouped.setdefault(issue.check_id, []).append(issue)

    commercial_urls = commercial_urls or set()
    opportunities: list[DetectedOpportunity] = []

    for check_id, group in grouped.items():
        worst = min(group, key=lambda i: list(SEVERITY_IMPACT).index(i.severity))
        affected = {i.url for i in group if i.url} | {url for i in group for url in i.affected_urls}
        share = min(len(affected) / max(pages_total, 1), 1.0)

        seo_impact = SEVERITY_IMPACT[worst.severity]
        # An issue on a commercially important page matters more.
        touches_commercial = bool(affected & commercial_urls)
        business_impact = seo_impact * (1.0 if touches_commercial else 0.75)
        business_impact = min(10.0, business_impact + 2.0 * share)

        effort = EFFORT_BY_CHECK.get(check_id, 4.0)
        # Fixing the same thing on many pages costs more, but sub-linearly.
        effort = min(10.0, effort * (1.0 + 0.5 * share))

        evidence = []
        if evidence_by_check and check_id in evidence_by_check:
            evidence = [evidence_by_check[check_id]]

        opportunities.append(
            DetectedOpportunity(
                opportunity_type=TYPE_BY_CHECK.get(check_id, OpportunityType.TECHNICAL_FIX),
                title=f"{worst.title} ({len(affected) or len(group)} page(s))",
                description=(
                    f"{worst.detail} {worst.recommendation}".strip()
                    or f"{len(group)} instance(s) of {check_id}."
                ),
                business_impact=round(business_impact, 2),
                seo_impact=seo_impact,
                effort=round(effort, 2),
                # Deterministic checks are observations, so confidence is high;
                # the residual uncertainty is about business value, not detection.
                confidence=0.9,
                strategic_fit=0.9 if touches_commercial else 0.7,
                risk=SEVERITY_RISK[worst.severity],
                target_entity_type="page" if len(affected) == 1 else "website",
                target_url=next(iter(affected), None) if len(affected) == 1 else None,
                evidence_refs=evidence,
                data={
                    "check_id": check_id,
                    "severity": worst.severity.value,
                    "dimension": worst.dimension.value,
                    "affected_count": len(affected) or len(group),
                    "affected_urls": sorted(affected)[:50],
                },
            )
        )
    return opportunities


def from_content_gaps(
    gaps: list[ContentGap], *, evidence_by_topic: dict[str, str] | None = None
) -> list[DetectedOpportunity]:
    """Turn gap decisions into opportunities, skipping DO_NOTHING entirely."""
    type_by_decision = {
        ContentDecision.CREATE: OpportunityType.CONTENT_CREATE,
        ContentDecision.UPDATE: OpportunityType.CONTENT_UPDATE,
        ContentDecision.CONSOLIDATE: OpportunityType.CONTENT_CONSOLIDATE,
        ContentDecision.REDIRECT: OpportunityType.TECHNICAL_FIX,
    }
    effort_by_decision = {
        ContentDecision.CREATE: 8.0,
        ContentDecision.UPDATE: 5.0,
        ContentDecision.CONSOLIDATE: 6.0,
        ContentDecision.REDIRECT: 3.0,
    }

    opportunities: list[DetectedOpportunity] = []
    for gap in gaps:
        if gap.decision is ContentDecision.DO_NOTHING:
            # Deliberately produces nothing: the correct action is no action.
            continue

        intent_value = gap.intent.transactional + gap.intent.commercial + gap.intent.local
        business_impact = round(4.0 + 5.0 * intent_value, 2)
        seo_impact = round(4.0 + 4.0 * max(gap.competitor_coverage, gap.serp_coverage), 2)

        evidence = []
        if evidence_by_topic and gap.topic in evidence_by_topic:
            evidence = [evidence_by_topic[gap.topic]]

        opportunities.append(
            DetectedOpportunity(
                opportunity_type=type_by_decision[gap.decision],
                title=f"{gap.decision.value.replace('_', ' ').title()}: {gap.topic}",
                description=gap.decision_reason,
                business_impact=min(business_impact, 10.0),
                seo_impact=min(seo_impact, 10.0),
                effort=effort_by_decision[gap.decision],
                confidence=gap.confidence,
                strategic_fit=round(0.5 + 0.5 * intent_value, 2),
                risk=RiskLevel.LOW,
                target_entity_type="content",
                target_entity_id=gap.cluster_id,
                target_url=gap.target_url,
                evidence_refs=evidence + gap.evidence_ids,
                data={
                    "decision": gap.decision.value,
                    "brand_coverage": gap.brand_coverage,
                    "competitor_coverage": gap.competitor_coverage,
                    "serp_coverage": gap.serp_coverage,
                    "existing_page_quality": gap.existing_page_quality,
                    "consolidate_urls": gap.consolidate_urls,
                    "primary_intent": gap.intent.primary.value,
                },
            )
        )
    return opportunities


def from_keyword_positions(
    keywords: list[KeywordRecord], *, evidence_ref: str | None = None
) -> list[DetectedOpportunity]:
    """Find pages ranking just below where clicks begin.

    This only fires on *observed* Search Console positions. Without GSC there is
    no position data and therefore no opportunity — not a guessed one.
    """
    opportunities: list[DetectedOpportunity] = []
    for record in keywords:
        position = record.metric("position")
        impressions = record.metric("impressions")
        if position is None or position.value is None:
            continue
        if impressions is None or impressions.value is None:
            continue
        if not (4 <= position.value <= 20) or impressions.value < 50:
            continue

        intent_value = record.intent.transactional + record.intent.commercial + record.intent.local
        opportunities.append(
            DetectedOpportunity(
                opportunity_type=OpportunityType.CTR_IMPROVEMENT
                if position.value <= 10
                else OpportunityType.CONTENT_UPDATE,
                title=f"Improve position {position.value:.1f} for '{record.keyword}'",
                description=(
                    f"The query '{record.keyword}' returned {impressions.value:.0f} "
                    f"impressions at an average position of {position.value:.1f}. It is "
                    "close enough to the visible results that improvement is realistic."
                ),
                business_impact=round(4.0 + 5.0 * intent_value, 2),
                seo_impact=round(9.0 - position.value * 0.25, 2),
                effort=4.0 if position.value <= 10 else 6.0,
                confidence=0.75,
                strategic_fit=round(0.5 + 0.5 * intent_value, 2),
                target_entity_type="keyword",
                target_entity_id=record.normalised,
                target_url=record.mapped_url,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                data={
                    "keyword": record.keyword,
                    "position": position.value,
                    "impressions": impressions.value,
                    "provenance": position.provenance.value,
                },
            )
        )
    return opportunities


def from_keyword_gaps(
    gaps: list[KeywordGap], *, evidence_ref: str | None = None, limit: int = 20
) -> list[DetectedOpportunity]:
    opportunities: list[DetectedOpportunity] = []
    for gap in gaps[:limit]:
        opportunities.append(
            DetectedOpportunity(
                opportunity_type=OpportunityType.KEYWORD_GAP,
                title=f"Competitors cover '{gap.keyword}' and this brand does not",
                description=(
                    f"{len(gap.competitor_domains)} competitor domain(s) have a page "
                    f"addressing '{gap.keyword}': {', '.join(gap.competitor_domains)}. "
                    "No brand page was observed covering it."
                ),
                business_impact=5.0,
                seo_impact=round(min(9.0, 4.0 + len(gap.competitor_domains)), 2),
                effort=7.0,
                confidence=0.6,
                strategic_fit=0.7,
                target_entity_type="keyword",
                target_entity_id=gap.keyword,
                evidence_refs=[evidence_ref] if evidence_ref else [],
                data={"competitors": gap.competitor_domains},
            )
        )
    return opportunities


__all__ = [
    "EFFORT_BY_CHECK",
    "PRIORITY_FORMULA",
    "SEVERITY_IMPACT",
    "TYPE_BY_CHECK",
    "DetectedOpportunity",
    "from_content_gaps",
    "from_keyword_gaps",
    "from_keyword_positions",
    "from_technical_issues",
    "prioritise",
    "prioritise_all",
]
