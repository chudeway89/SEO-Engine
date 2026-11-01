"""Dimension scoring.

There is deliberately no single opaque "SEO score".  Nine dimensions are scored
independently from the deterministic issues, and the overall figure is a
weighted mean that never replaces them.

A dimension the crawl could not assess is reported as **not evaluated** rather
than scored 100 — an unassessed dimension is not a healthy one.
"""

from __future__ import annotations

from collections import defaultdict

from seo_engine.schemas.crawl import CrawlResult
from seo_engine.schemas.enums import IssueSeverity, SEODimension
from seo_engine.schemas.seo import DimensionScore, SEOIssue, SEOScorecard, TechnicalAuditReport

#: How much each dimension contributes to the overall indicator.
DIMENSION_WEIGHTS: dict[SEODimension, float] = {
    SEODimension.TECHNICAL_HEALTH: 0.18,
    SEODimension.INDEXABILITY: 0.18,
    SEODimension.CONTENT_QUALITY: 0.15,
    SEODimension.SEARCH_ALIGNMENT: 0.14,
    SEODimension.INTERNAL_LINKING: 0.10,
    SEODimension.STRUCTURED_DATA: 0.07,
    SEODimension.AI_SEARCH_READINESS: 0.08,
    SEODimension.CONVERSION_READINESS: 0.06,
    SEODimension.LOCAL_READINESS: 0.04,
}

#: Penalty per issue, scaled by how much of the site it affects.
SEVERITY_PENALTY: dict[IssueSeverity, float] = {
    IssueSeverity.CRITICAL: 25.0,
    IssueSeverity.HIGH: 12.0,
    IssueSeverity.MEDIUM: 5.0,
    IssueSeverity.LOW: 1.5,
    IssueSeverity.INFO: 0.0,
}

SCORING_METHOD = (
    "Deterministic rule engine. Each dimension starts at 100 and is penalised by "
    "the severity of the issues found in it, scaled by the share of crawled pages "
    "affected. The overall figure is a weighted mean of the evaluated dimensions "
    "and does not replace them. This is SEO Engine's internal health model, not a "
    "Google ranking score."
)

#: Dimensions that need a data source the crawler alone cannot provide.
_REQUIRES_EXTERNAL_DATA: dict[SEODimension, str] = {
    SEODimension.LOCAL_READINESS: (
        "Local readiness needs Google Business Profile data and brand location "
        "records; neither was available for this audit."
    ),
}


def score_dimensions(
    result: CrawlResult,
    issues: list[SEOIssue],
    *,
    has_local_data: bool = False,
) -> SEOScorecard:
    pages_evaluated = sum(1 for p in result.pages if not p.error)
    denominator = max(pages_evaluated, 1)

    by_dimension: dict[SEODimension, list[SEOIssue]] = defaultdict(list)
    for issue in issues:
        by_dimension[issue.dimension].append(issue)

    scores: list[DimensionScore] = []
    for dimension in SEODimension:
        dimension_issues = by_dimension.get(dimension, [])

        reason = _REQUIRES_EXTERNAL_DATA.get(dimension)
        if reason and not has_local_data and not dimension_issues:
            scores.append(
                DimensionScore(
                    dimension=dimension,
                    score=0.0,
                    evaluated=False,
                    not_evaluated_reason=reason,
                    pages_evaluated=pages_evaluated,
                    detail="Not evaluated.",
                )
            )
            continue

        penalty = 0.0
        for issue in dimension_issues:
            # One issue on one page of a thousand should not sink a dimension;
            # the same issue on every page should.
            affected = max(len(issue.affected_urls), 1)
            share = min(affected / denominator, 1.0)
            penalty += SEVERITY_PENALTY[issue.severity] * (0.35 + 0.65 * share)

        score = max(0.0, 100.0 - penalty)
        critical = sum(1 for i in dimension_issues if i.severity == IssueSeverity.CRITICAL)
        scores.append(
            DimensionScore(
                dimension=dimension,
                score=round(score, 1),
                issues_count=len(dimension_issues),
                critical_count=critical,
                pages_evaluated=pages_evaluated,
                detail=_describe(dimension, dimension_issues),
            )
        )

    evaluated = [s for s in scores if s.evaluated]
    total_weight = sum(DIMENSION_WEIGHTS[s.dimension] for s in evaluated) or 1.0
    overall = sum(s.score * DIMENSION_WEIGHTS[s.dimension] for s in evaluated) / total_weight

    return SEOScorecard(
        dimensions=scores,
        overall=round(overall, 1),
        pages_evaluated=pages_evaluated,
        issues_total=len(issues),
        method=SCORING_METHOD,
    )


def _describe(dimension: SEODimension, issues: list[SEOIssue]) -> str:
    if not issues:
        return "No issues detected by the deterministic checks."
    counts: dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue.severity.value] += 1
    parts = [f"{count} {severity}" for severity, count in sorted(counts.items())]
    worst = min(issues, key=lambda i: list(SEVERITY_PENALTY).index(i.severity))
    return f"{', '.join(parts)}. Most severe: {worst.title}."


def build_audit_report(
    result: CrawlResult,
    issues: list[SEOIssue],
    *,
    website_id: str,
    crawl_job_id: str,
    has_local_data: bool = False,
) -> TechnicalAuditReport:
    scorecard = score_dimensions(result, issues, has_local_data=has_local_data)
    counts: dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue.severity.value] += 1
    return TechnicalAuditReport(
        website_id=website_id,
        crawl_job_id=crawl_job_id,
        issues=issues,
        scorecard=scorecard,
        pages_analysed=scorecard.pages_evaluated,
        summary_counts=dict(counts),
    )


__all__ = [
    "DIMENSION_WEIGHTS",
    "SCORING_METHOD",
    "SEVERITY_PENALTY",
    "build_audit_report",
    "score_dimensions",
]
