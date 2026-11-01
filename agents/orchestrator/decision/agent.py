"""DEC-001 — Decision Agent.

The final strategic reviewer before anything becomes a recommendation. For each
prioritised opportunity it asks the questions from the Build Specification §39:

* Is the opportunity real?
* Is the evidence sufficient?
* Does it align with the brand?
* Does an existing asset already solve it?
* Is there a safer action?
* What is the likely impact, and what could go wrong?
* Does it require approval?

An opportunity that fails those questions is *rejected here*, with the reason
recorded, rather than passed to a human as noise.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.schemas.agent import AgentContext, ProposedRecommendation
from seo_engine.schemas.enums import (
    ActionType,
    EvidenceType,
    OpportunityType,
    RiskLevel,
    SynthesisMode,
)

#: Evidence below this count is too thin to recommend acting on.
MIN_EVIDENCE = 1

#: Opportunity type → the action that would implement it.
ACTION_BY_TYPE: dict[str, str] = {
    OpportunityType.CONTENT_CREATE.value: ActionType.CMS_CREATE_DRAFT.value,
    OpportunityType.CONTENT_UPDATE.value: ActionType.CONTENT_UPDATE.value,
    OpportunityType.CONTENT_CONSOLIDATE.value: ActionType.CONTENT_UPDATE.value,
    OpportunityType.ON_PAGE.value: ActionType.METADATA_UPDATE.value,
    OpportunityType.CTR_IMPROVEMENT.value: ActionType.METADATA_UPDATE.value,
    OpportunityType.INTERNAL_LINKING.value: ActionType.INTERNAL_LINK_ADD.value,
    OpportunityType.STRUCTURED_DATA.value: ActionType.SCHEMA_UPDATE.value,
}

RISK_BY_TYPE: dict[str, RiskLevel] = {
    OpportunityType.CONTENT_CONSOLIDATE.value: RiskLevel.MEDIUM,
    OpportunityType.INDEXABILITY.value: RiskLevel.MEDIUM,
    OpportunityType.TECHNICAL_FIX.value: RiskLevel.MEDIUM,
}


class DecisionInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    max_recommendations: int = 10


class DecisionOutput(BaseModel):
    brand_id: str
    reviewed: int = 0
    recommended: int = 0
    rejected: list[dict[str, str]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


class DecisionAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = DecisionInput.model_validate(context.inputs)
        decisions = context.service("decisions")
        opportunities = await decisions.list_opportunities(payload.brand_id, limit=50)

        if not opportunities:
            workspace.limitation("There are no prioritised opportunities to review.")
            return "No opportunities were available to turn into recommendations."

        brands = context.services.get("brands")
        risk_category = "general"
        if brands is not None:
            brand = await brands.get(payload.brand_id)
            risk_category = brand.risk_category

        reviewed = 0
        rejected: list[dict[str, str]] = []
        recommendations: list[Any] = []

        for opportunity in opportunities:
            reviewed += 1
            verdict = self._review(opportunity)
            if verdict is not None:
                rejected.append({"title": opportunity.title, "reason": verdict})
                continue

            evidence = workspace.observe(
                evidence_type=EvidenceType.SYSTEM,
                source="decision_agent",
                reference=f"opportunity:{opportunity.id}",
                observation=(
                    f"Reviewed '{opportunity.title}': the opportunity cites "
                    f"{len(opportunity.evidence_refs)} piece(s) of evidence, scores "
                    f"{opportunity.priority_score:.1f}/100 on the internal model, and "
                    f"carries {opportunity.risk} risk at effort {opportunity.effort:.0f}/10."
                ),
                data={
                    "opportunity_id": str(opportunity.id),
                    "priority_score": opportunity.priority_score,
                    "evidence_count": len(opportunity.evidence_refs),
                },
                confidence=opportunity.confidence,
            )

            action_type = ACTION_BY_TYPE.get(opportunity.opportunity_type)
            risk = RISK_BY_TYPE.get(opportunity.opportunity_type, RiskLevel(opportunity.risk))

            proposed = ProposedRecommendation(
                type=opportunity.opportunity_type,
                title=opportunity.title,
                problem=opportunity.description,
                opportunity=(
                    f"Addressing this is worth {opportunity.business_impact:.0f}/10 to the "
                    f"business and {opportunity.seo_impact:.0f}/10 to search performance."
                ),
                reason=self._reason(opportunity),
                business_impact=opportunity.business_impact,
                seo_impact=opportunity.seo_impact,
                effort=opportunity.effort,
                risk=risk,
                confidence=opportunity.confidence,
                strategic_fit=opportunity.strategic_fit,
                expected_outcome=self._expected_outcome(opportunity),
                evidence_ids=[*opportunity.evidence_refs, evidence.id],
                proposed_action=(
                    {
                        "action_type": action_type,
                        "target": {"url": opportunity.target_url},
                        "attributes": {"category": risk_category},
                    }
                    if action_type
                    else None
                ),
                target_entity_type=opportunity.target_entity_type,
                target_entity_id=opportunity.target_entity_id,
            )

            record = await decisions.create_recommendation(
                payload.brand_id,
                proposed,
                opportunity_id=opportunity.id,
                mission_id=payload.mission_id,
                agent_id=self.manifest.id,
                risk_category=risk_category,
                automation_policy=context.policy.automation_policy,
            )
            recommendations.append(record)
            workspace.recommend(proposed)

            if len(recommendations) >= payload.max_recommendations:
                break

        for entry in rejected[:5]:
            workspace.find(
                key="decision.rejected",
                title=f"Not recommended: {entry['title']}",
                detail=entry["reason"],
                severity="info",
            )

        if not recommendations:
            workspace.limitation(
                "Every opportunity was reviewed and none met the bar for a "
                "recommendation. The reasons are recorded above."
            )

        output = DecisionOutput(
            brand_id=str(payload.brand_id),
            reviewed=reviewed,
            recommended=len(recommendations),
            rejected=rejected,
            recommendations=[
                {
                    "id": str(r.id),
                    "title": r.title,
                    "type": r.recommendation_type,
                    "priority_score": r.priority_score,
                    "approval_required": r.approval_required,
                    "approval_reason": r.approval_reason,
                    "evidence_refs": r.evidence_refs,
                }
                for r in recommendations
            ],
        )
        workspace.outputs["decisions"] = output.model_dump(mode="json")
        workspace.metrics["recommendations"] = float(len(recommendations))

        needing_approval = sum(1 for r in recommendations if r.approval_required)
        return (
            f"Reviewed {reviewed} opportunit(y/ies) and produced {len(recommendations)} "
            f"recommendation(s); {len(rejected)} were rejected as not worth acting on. "
            f"{needing_approval} recommendation(s) require human approval before "
            "anything is executed."
        )

    # ------------------------------------------------------------------
    def _review(self, opportunity: Any) -> str | None:
        """Return a rejection reason, or None to proceed."""
        if len(opportunity.evidence_refs) < MIN_EVIDENCE:
            return (
                "No supporting evidence was recorded, so this cannot be recommended. "
                "It would have to be raised explicitly as a hypothesis instead."
            )
        if opportunity.priority_score < 5.0:
            return (
                f"Its priority score of {opportunity.priority_score:.1f}/100 does not "
                "justify the effort against everything else available."
            )
        if opportunity.confidence < 0.35:
            return (
                f"Confidence in the underlying observation is only "
                f"{opportunity.confidence:.0%}, which is too low to act on."
            )
        if (
            opportunity.opportunity_type == OpportunityType.CONTENT_CREATE.value
            and opportunity.data.get("existing_page_quality") is not None
            and float(opportunity.data["existing_page_quality"]) >= 75
        ):
            return (
                "An existing page already covers this topic well. Creating another "
                "would compete with it rather than add anything."
            )
        return None

    def _reason(self, opportunity: Any) -> str:
        parts = [opportunity.description]
        breakdown = opportunity.priority_breakdown or {}
        if breakdown:
            parts.append(
                f"It ranks {opportunity.priority_score:.1f}/100 on the internal model "
                f"(impact {breakdown.get('impact', 0):.1f}, confidence "
                f"{breakdown.get('confidence', 0):.0%}, effort "
                f"{breakdown.get('effort', 0):.0f}/10)."
            )
        parts.append(f"It rests on {len(opportunity.evidence_refs)} recorded observation(s).")
        return " ".join(parts)

    def _expected_outcome(self, opportunity: Any) -> str:
        """Describe the direction of the expected change without predicting a number."""
        return (
            f"Improved {opportunity.opportunity_type.replace('_', ' ')} for the affected "
            "pages. The size of the change is not predicted; it will be measured "
            "against the recorded baseline after the action is executed."
        )


AGENT = DecisionAgent
