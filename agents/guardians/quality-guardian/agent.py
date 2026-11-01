"""QUAL-001 — Quality Guardian Agent.

The result validator checks each agent result as it is produced. This guardian
checks the accumulated output afterwards: every recommendation for the brand,
against the evidence store as it stands now (``audit_recommendations``).

It catches what a per-run check cannot see — evidence that no longer resolves,
a recommendation resting only on synthetic development data, confidence beyond
the strongest evidence cited, a high-risk change that would not ask for
approval, an unmeasurable outcome, a duplicate. Each issue names its rule. The
guardian reports and scores; correcting a recommendation is the job of the
agent and person who own it.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.engines.quality.audit import (
    EvidenceFacts,
    RecommendationFacts,
    audit_recommendations,
)
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
QualityAuditInput = _schemas.QualityAuditInput
QualityAuditOutput = _schemas.QualityAuditOutput


class QualityGuardianAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = QualityAuditInput.model_validate(context.inputs)
        rows = await context.service("decisions").list_recommendations(
            payload.brand_id, limit=payload.limit
        )
        if payload.mission_id is not None:
            rows = [r for r in rows if r.mission_id in {payload.mission_id, None}]
        if not rows:
            workspace.limitation("There are no recommendations to audit.")
            return "No recommendations exist for this brand, so there was nothing to audit."

        refs = sorted({ref for r in rows for ref in r.evidence_refs or []})
        loaded = await workspace.evidence_collector.load(refs)
        evidence = {
            e.id: EvidenceFacts(
                ref=e.id,
                provenance=e.provenance.value,
                is_observation=e.is_observation,
                confidence=e.confidence,
            )
            for e in loaded
        }
        report = audit_recommendations(
            [
                RecommendationFacts(
                    id=str(r.id),
                    title=r.title,
                    recommendation_type=r.recommendation_type,
                    status=r.status,
                    evidence_refs=list(r.evidence_refs or []),
                    confidence=r.confidence,
                    is_hypothesis=r.is_hypothesis,
                    risk=r.risk,
                    approval_required=r.approval_required,
                    expected_outcome=r.expected_outcome or "",
                )
                for r in rows
            ],
            evidence,
        )

        audit_evidence = workspace.observe(
            evidence_type=EvidenceType.SYSTEM,
            source="quality_audit",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Audited {report.audited} recommendation(s) against {len(evidence)} resolved "
                f"evidence record(s): {report.clean} clean, {len(report.issues)} issue(s); "
                f"quality score {report.quality_score:.0f}/100."
            ),
            data={
                "by_rule": report.by_rule(),
                "refs_cited": len(refs),
                "refs_resolved": len(evidence),
            },
            provenance=DataProvenance.OBSERVED,
        )
        for rule, count in sorted(report.by_rule().items()):
            sample = [i for i in report.issues if i.rule == rule]
            workspace.find(
                key=f"quality.{rule}",
                title=f"{count} recommendation(s): {rule.replace('_', ' ')}",
                detail=sample[0].detail if sample else "",
                severity=sample[0].severity if sample else "low",
                data={"recommendations": [i.as_dict() for i in sample[:10]]},
                evidence=[audit_evidence],
            )
        if report.by_rule().get("synthetic_only_basis"):
            workspace.limitation(
                f"{report.by_rule()['synthetic_only_basis']} recommendation(s) rest only on "
                "synthetic development data and must not be read as findings about the "
                "business until real integrations are connected."
            )

        output = QualityAuditOutput(
            brand_id=str(payload.brand_id),
            audited=report.audited,
            clean=report.clean,
            quality_score=report.quality_score,
            by_rule=report.by_rule(),
            issues=[i.as_dict() for i in report.issues[:200]],
        )
        workspace.outputs["quality_audit"] = output.model_dump(mode="json")
        workspace.metrics["recommendation_quality_score"] = report.quality_score

        return (
            f"Audited {report.audited} recommendation(s): {report.clean} clean and "
            f"{len(report.issues)} issue(s) across {len(report.by_rule())} rule(s). Quality "
            f"score {report.quality_score:.0f}/100."
        )


AGENT = QualityGuardianAgent
