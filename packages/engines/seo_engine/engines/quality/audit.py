"""Audit of persisted recommendations against the evidence they cite.

The result validator checks each agent result *as it is produced*. This audit
runs afterwards, across everything the platform has recommended for a brand,
against the evidence store as it now stands. It catches what a per-run check
cannot see:

* a recommendation citing evidence that no longer resolves (dangling refs);
* a recommendation resting entirely on synthetic development data, which must
  never be presented to a customer as a finding about their business;
* confidence that exceeds what its evidence supports — an inference-only basis
  claiming more than a hypothesis may, or a recommendation more confident than
  any evidence behind it;
* a high-risk recommendation that does not require approval;
* a missing expected outcome, which makes the recommendation unmeasurable;
* duplicate open recommendations for the same change.

Every issue names its rule, so a fix can be traced to the invariant it restores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.pipeline import normalise

HYPOTHESIS_CONFIDENCE_CAP = 0.6
CONFIDENCE_HEADROOM = 0.1
OPEN_STATUSES = frozenset({"proposed", "pending_approval", "approved"})

SEVERITY = {
    "dangling_evidence": "high",
    "unevidenced_not_hypothesis": "critical",
    "synthetic_only_basis": "high",
    "inference_only_overconfident": "medium",
    "confidence_exceeds_evidence": "medium",
    "high_risk_without_approval": "critical",
    "no_expected_outcome": "low",
    "duplicate_recommendation": "low",
}


@dataclass(slots=True)
class EvidenceFacts:
    ref: str
    provenance: str
    is_observation: bool
    confidence: float


@dataclass(slots=True)
class RecommendationFacts:
    id: str
    title: str
    recommendation_type: str
    status: str
    evidence_refs: list[str]
    confidence: float
    is_hypothesis: bool
    risk: str
    approval_required: bool
    expected_outcome: str


@dataclass(slots=True)
class QualityIssue:
    rule: str
    recommendation_id: str
    title: str
    detail: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.rule]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(slots=True)
class AuditReport:
    audited: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
    clean: int = 0

    @property
    def quality_score(self) -> float:
        """Share of audited recommendations with no high or critical issue."""
        if not self.audited:
            return 100.0
        serious = {i.recommendation_id for i in self.issues if i.severity in {"high", "critical"}}
        return round(100.0 * (self.audited - len(serious)) / self.audited, 1)

    def by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.rule] = counts.get(issue.rule, 0) + 1
        return counts


def audit_recommendations(
    recommendations: list[RecommendationFacts], evidence: dict[str, EvidenceFacts]
) -> AuditReport:
    report = AuditReport(audited=len(recommendations))
    seen: dict[tuple[str, str], str] = {}

    for rec in recommendations:
        before = len(report.issues)

        def flag(rule: str, detail: str, rec: RecommendationFacts = rec) -> None:
            report.issues.append(QualityIssue(rule, rec.id, rec.title, detail))

        resolved = [evidence[r] for r in rec.evidence_refs if r in evidence]
        dangling = [r for r in rec.evidence_refs if r not in evidence]

        if dangling:
            flag(
                "dangling_evidence",
                f"{len(dangling)} cited evidence reference(s) do not resolve: {', '.join(dangling[:5])}.",
            )
        if not rec.evidence_refs and not rec.is_hypothesis:
            flag(
                "unevidenced_not_hypothesis",
                "No evidence is cited and it is not labelled a hypothesis.",
            )
        if resolved and all(e.provenance == "synthetic_demo" for e in resolved):
            flag(
                "synthetic_only_basis",
                "Every piece of evidence behind this recommendation is synthetic development "
                "data. It must not be presented as a finding about the business.",
            )
        # Synthetic observations are still observations; their synthetic basis is
        # the separate synthetic_only_basis rule, not this one.
        observed = [e for e in resolved if e.is_observation]
        if resolved and not observed and rec.confidence > HYPOTHESIS_CONFIDENCE_CAP:
            flag(
                "inference_only_overconfident",
                f"Confidence {rec.confidence:.2f} rests on no direct observation; an "
                f"inference-only basis is capped at {HYPOTHESIS_CONFIDENCE_CAP}.",
            )
        if resolved:
            ceiling = max(e.confidence for e in resolved) + CONFIDENCE_HEADROOM
            if rec.confidence > ceiling:
                flag(
                    "confidence_exceeds_evidence",
                    f"Confidence {rec.confidence:.2f} exceeds the strongest cited evidence "
                    f"({ceiling - CONFIDENCE_HEADROOM:.2f}).",
                )
        if rec.risk in {"high", "critical"} and not rec.approval_required:
            flag(
                "high_risk_without_approval", f"A {rec.risk}-risk change does not require approval."
            )
        if not rec.expected_outcome.strip():
            flag(
                "no_expected_outcome",
                "No expected outcome is stated, so the result cannot be measured.",
            )

        if rec.status in OPEN_STATUSES:
            signature = (rec.recommendation_type, normalise(rec.title))
            original = seen.get(signature)
            if original is not None:
                flag(
                    "duplicate_recommendation",
                    f"Duplicates open recommendation {original} for the same change.",
                )
            else:
                seen[signature] = rec.id

        if len(report.issues) == before:
            report.clean += 1

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    report.issues.sort(key=lambda i: (order[i.severity], i.rule, i.title))
    return report


__all__ = [
    "HYPOTHESIS_CONFIDENCE_CAP",
    "SEVERITY",
    "AuditReport",
    "EvidenceFacts",
    "QualityIssue",
    "RecommendationFacts",
    "audit_recommendations",
]
