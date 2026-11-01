"""RES-001 — Search Research Agent.

Describes the demand landscape the brand is measured against: branded versus
non-branded, the intent and topic mix, the share asked as questions, and the
queries sitting in striking distance just off page one.

The only input is what Search Console reported. Search Console shows queries the
site already appeared for, so demand the site is invisible to is absent by
construction — the agent says so every time instead of estimating the rest of
the market (Rule 14).
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts
from seo_engine.engines.research.demand import VISIBILITY_LIMITATION, demand_landscape
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
SearchResearchInput = _schemas.SearchResearchInput
SearchResearchOutput = _schemas.SearchResearchOutput


class SearchResearchAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = SearchResearchInput.model_validate(context.inputs)
        if not workspace.note_unavailable_tool("gsc"):
            workspace.outputs["search_research"] = SearchResearchOutput(
                brand_id=str(payload.brand_id)
            ).model_dump(mode="json")
            return (
                "No demand landscape was produced: Search Console is not available, and "
                "no demand figure has been estimated in its place."
            )

        rows = await context.service("integrations").query_demand(
            payload.brand_id, limit=payload.max_queries
        )
        if not rows:
            workspace.limitation(
                "Search Console is connected but no query rows have been synced yet, so "
                "there is no measured demand to describe."
            )
            workspace.outputs["search_research"] = SearchResearchOutput(
                brand_id=str(payload.brand_id)
            ).model_dump(mode="json")
            return "Search Console returned no query rows, so no demand landscape was produced."

        facts = await load_brand_facts(context, payload.brand_id)
        landscape = demand_landscape(
            rows, brand_terms=facts.terms, location_terms=facts.location_terms
        )
        provenance = DataProvenance(landscape.provenance)
        workspace.limitation(VISIBILITY_LIMITATION)
        if provenance is DataProvenance.SYNTHETIC_DEMO:
            workspace.limitation(
                "Search Console is running its development adapter: every figure in this "
                "landscape is synthetic demonstration data, not a measurement of the site."
            )

        evidence = workspace.observe(
            evidence_type=EvidenceType.GSC,
            source="google_search_console",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"{landscape.queries} quer(y/ies) with {landscape.impressions} impressions and "
                f"{landscape.clicks} clicks: {landscape.branded_share:.0%} of impressions are "
                f"branded and {landscape.question_share:.0%} are questions."
            ),
            data=landscape.as_dict(),
            provenance=provenance,
        )

        top_intent = max(landscape.by_intent, key=lambda k: landscape.by_intent[k], default=None)
        workspace.find(
            key="demand.mix",
            title=(
                f"{landscape.branded_share:.0%} of measured demand is branded"
                + (f"; {top_intent} intent leads" if top_intent else "")
            ),
            detail=(
                "Branded demand is people already looking for the brand. Non-branded "
                "demand is where new visitors come from."
            ),
            data={"by_intent": landscape.by_intent, "branded_share": landscape.branded_share},
            evidence=[evidence],
        )
        striking = landscape.by_band.get("striking_distance", {})
        if striking.get("queries"):
            workspace.find(
                key="demand.striking_distance",
                title=(
                    f"{striking['queries']} quer(y/ies) with {striking['impressions']} "
                    "impressions sit at positions 11-20"
                ),
                detail=(
                    "These are measured, already-earned impressions one page away from "
                    "being seen; they are the cheapest demand to capture."
                ),
                severity="medium",
                data={"queries": landscape.striking_distance[:10]},
                evidence=[evidence],
            )

        output = SearchResearchOutput(
            brand_id=str(payload.brand_id),
            measured=True,
            provenance=provenance.value,
            landscape=landscape.as_dict(),
        )
        workspace.outputs["search_research"] = output.model_dump(mode="json")
        workspace.metrics["measured_impressions"] = float(landscape.impressions)

        return (
            f"Described measured demand across {landscape.queries} quer(y/ies) and "
            f"{landscape.impressions} impressions: {landscape.branded_share:.0%} branded, "
            f"{landscape.question_share:.0%} questions, "
            f"{striking.get('queries', 0)} in striking distance."
            + (" The data is synthetic." if provenance is DataProvenance.SYNTHETIC_DEMO else "")
        )


AGENT = SearchResearchAgent
