"""PRI-001 — Opportunity Prioritisation Agent.

Ranks detected opportunities with the documented internal model and makes the
working visible: what the impact, confidence, strategic fit and effort were, and
what the resulting score means.

It states plainly that this is SEO Engine's ordering model and not a claim about
how Google ranks anything.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.opportunities.detection import PRIORITY_FORMULA
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import EvidenceType, SynthesisMode


class PrioritisationInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    limit: int = 50


class PrioritisationOutput(BaseModel):
    brand_id: str
    opportunities_ranked: int = 0
    formula: str = PRIORITY_FORMULA
    ranked: list[dict[str, Any]] = Field(default_factory=list)
    quick_wins: list[dict[str, Any]] = Field(default_factory=list)


class PrioritisationAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = PrioritisationInput.model_validate(context.inputs)
        decisions = context.service("decisions")
        opportunities = await decisions.list_opportunities(payload.brand_id, limit=payload.limit)

        if not opportunities:
            workspace.limitation(
                "There are no detected opportunities to rank, so no prioritisation was performed."
            )
            return "No opportunities were available to prioritise."

        ranked = sorted(opportunities, key=lambda o: -o.priority_score)

        evidence = workspace.observe(
            evidence_type=EvidenceType.SYSTEM,
            source="prioritisation_engine",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Ranked {len(ranked)} opportunit(y/ies) using the internal model "
                f"({PRIORITY_FORMULA.split('.')[0]}). The highest scores "
                f"{ranked[0].priority_score:.1f}; the lowest scores "
                f"{ranked[-1].priority_score:.1f}."
            ),
            data={
                "count": len(ranked),
                "top": [{"title": o.title, "score": o.priority_score} for o in ranked[:5]],
            },
            confidence=0.9,
        )

        # Quick wins: real impact, low effort. Worth naming separately because
        # they are what a team can actually start on this week.
        quick_wins = [o for o in ranked if o.effort <= 3.0 and o.business_impact >= 5.0][:10]

        workspace.find(
            key="prioritisation.ranking",
            title=f"{len(ranked)} opportunit(y/ies) ranked",
            detail=(
                f"{PRIORITY_FORMULA} The score orders work; it does not predict a ranking position."
            ),
            data={
                "top": [
                    {
                        "title": o.title,
                        "score": o.priority_score,
                        "breakdown": o.priority_breakdown,
                    }
                    for o in ranked[:10]
                ]
            },
            evidence=[evidence],
        )
        if quick_wins:
            workspace.find(
                key="prioritisation.quick_wins",
                title=f"{len(quick_wins)} low-effort, high-impact item(s)",
                detail="These carry real business impact at an effort of 3/10 or less.",
                data={"items": [o.title for o in quick_wins]},
                evidence=[evidence],
            )

        for opportunity in ranked:
            from seo_engine.schemas.enums import OpportunityStatus

            opportunity.status = OpportunityStatus.PRIORITISED

        output = PrioritisationOutput(
            brand_id=str(payload.brand_id),
            opportunities_ranked=len(ranked),
            ranked=[
                {
                    "id": str(o.id),
                    "title": o.title,
                    "type": o.opportunity_type,
                    "priority_score": o.priority_score,
                    "business_impact": o.business_impact,
                    "seo_impact": o.seo_impact,
                    "effort": o.effort,
                    "confidence": o.confidence,
                    "breakdown": o.priority_breakdown,
                }
                for o in ranked
            ],
            quick_wins=[{"id": str(o.id), "title": o.title} for o in quick_wins],
        )
        workspace.outputs["prioritisation"] = output.model_dump(mode="json")
        workspace.metrics["ranked"] = float(len(ranked))

        return (
            f"Ranked {len(ranked)} opportunit(y/ies). The highest-priority item is "
            f"'{ranked[0].title}' at {ranked[0].priority_score:.1f}/100. "
            f"{len(quick_wins)} item(s) are low-effort and high-impact. This ordering "
            "is SEO Engine's internal model, not a prediction of ranking outcomes."
        )


AGENT = PrioritisationAgent
