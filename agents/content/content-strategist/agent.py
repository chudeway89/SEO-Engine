"""CNT-001 — Content Strategist Agent.

Turns content gap decisions into a roadmap. The strategy is the ordering rule,
and it is conservative on purpose: consolidate and update pages that already
exist before creating new ones, order each phase by commercial intent and by
whether the topic serves a service the customer actually sells, and never
schedule more than the stated capacity — the overflow is a backlog, not a
squeeze. Topics the gap stage decided need no content are counted and listed
with their reason; doing nothing is a decision the plan records.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts
from seo_engine.engines.content.strategy import build_roadmap
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import SynthesisMode

_schemas = load_agent_module(__file__)
ContentStrategyInput = _schemas.ContentStrategyInput
ContentStrategyOutput = _schemas.ContentStrategyOutput


class ContentStrategistAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentStrategyInput.model_validate(context.inputs)
        if not payload.content_gaps:
            workspace.limitation(
                "No content gap decisions were supplied, so there is nothing to sequence. "
                "The content gap stage decides what each topic needs; it must run first."
            )
            return "No roadmap was produced: no content gap decisions were available."

        facts = await load_brand_facts(context, payload.brand_id)
        roadmap = build_roadmap(
            payload.content_gaps,
            services=[(name, terms) for name, terms, _url in facts.services],
            months=payload.months,
            capacity_per_month=payload.capacity_per_month,
        )

        by_decision: dict[str, int] = {}
        for item in roadmap.items:
            by_decision[item.decision.value] = by_decision.get(item.decision.value, 0) + 1
        gap_refs = sorted({ref for item in roadmap.items for ref in item.evidence_ids})
        evidence = workspace.infer(
            source="content_strategy_engine",
            conclusion=(
                f"Sequenced {len(roadmap.items)} content item(s) over {roadmap.months} month(s) "
                f"at {roadmap.capacity_per_month} per month; {len(roadmap.backlog)} in backlog "
                f"and {len(roadmap.not_pursued)} topic(s) not pursued."
            ),
            data=roadmap.as_dict(),
            confidence=0.8,
            derived_from=gap_refs,
        )

        for month in range(1, roadmap.months + 1):
            items = [i for i in roadmap.items if i.month == month]
            if not items:
                continue
            workspace.find(
                key="content_strategy.month",
                title=f"Month {month}: " + "; ".join(i.topic for i in items),
                detail=" ".join(i.rationale for i in items),
                data={"items": [i.as_dict() for i in items]},
                evidence=[evidence],
            )
        if roadmap.backlog:
            workspace.limitation(
                f"{len(roadmap.backlog)} topic(s) exceed the stated capacity and are held in "
                "the backlog rather than scheduled."
            )

        output = ContentStrategyOutput(
            brand_id=str(payload.brand_id),
            scheduled=len(roadmap.items),
            backlog=len(roadmap.backlog),
            not_pursued=len(roadmap.not_pursued),
            by_decision=by_decision,
            roadmap=roadmap.as_dict(),
        )
        workspace.outputs["content_strategy"] = output.model_dump(mode="json")
        workspace.outputs["content_roadmap"] = [i.as_dict() for i in roadmap.items]
        workspace.metrics["roadmap_items"] = float(len(roadmap.items))

        return (
            f"Scheduled {len(roadmap.items)} content item(s) over {roadmap.months} month(s): "
            + ", ".join(f"{n} {d.replace('_', ' ')}" for d, n in sorted(by_decision.items()))
            + f". Existing pages are fixed before new ones are created; "
            f"{len(roadmap.not_pursued)} topic(s) need no content."
        )


AGENT = ContentStrategistAgent
