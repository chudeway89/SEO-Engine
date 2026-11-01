"""CMP-001 — Competitor Discovery Agent.

The competitors a customer names are business competitors. The domains that
keep appearing for the brand's own queries are search competitors. They
overlap, but not completely, and the difference matters: a rival nobody sees in
search is not where lost visibility goes.

This agent reads the SERP snapshots SERP research stored, finds the domains
that recur (``discover_serp_competitors``), and compares them with the recorded
list. It proposes new candidates; it never adds one to the brand graph. A
domain observed only on synthetic development pages is reported as synthetic
and is never proposed — it is not a real company.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import (
    SYNTHETIC_SERP_LIMITATION,
    load_brand_facts,
    snapshots_provenance,
    website_domain,
)
from seo_engine.engines.competitors.analysis import discover_serp_competitors
from seo_engine.schemas.agent import AgentContext, ProposedRecommendation
from seo_engine.schemas.enums import DataProvenance, EvidenceType, RiskLevel, SynthesisMode

_schemas = load_agent_module(__file__)
CompetitorDiscoveryInput = _schemas.CompetitorDiscoveryInput
CompetitorDiscoveryOutput = _schemas.CompetitorDiscoveryOutput


def _domain(value: str) -> str:
    return value.lower().removeprefix("www.")


class CompetitorDiscoveryAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = CompetitorDiscoveryInput.model_validate(context.inputs)
        snapshots = [
            s
            for s in await context.service("search").latest_snapshots(payload.brand_id)
            if s.available
        ]
        if not snapshots:
            workspace.limitation(
                "No results pages have been observed for this brand, so no search "
                "competitor can be identified. Run SERP research first; nobody is guessed."
            )
            return "No SERP observations exist, so no competitors were discovered."

        provenance = snapshots_provenance(snapshots)
        synthetic = provenance is DataProvenance.SYNTHETIC_DEMO
        if synthetic:
            workspace.limitation(SYNTHETIC_SERP_LIMITATION)

        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)
        recorded = {_domain(d) for d in facts.competitors}
        profiles = discover_serp_competitors(
            snapshots,
            brand_domain=facts.domain or "",
            minimum_appearances=payload.minimum_appearances,
        )
        candidates = [p for p in profiles if _domain(p.domain) not in recorded]
        observed_recorded = [p for p in profiles if _domain(p.domain) in recorded]
        seen_domains = {
            _domain(r.domain) for s in snapshots for r in s.results if r.result_type == "organic"
        }
        not_observed = sorted(d for d in recorded if d not in seen_domains)

        evidence = workspace.observe(
            evidence_type=EvidenceType.SERP_RESULT,
            source="competitor_discovery",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Across {len(snapshots)} results page(s), {len(profiles)} domain(s) recur at "
                f"least {payload.minimum_appearances} times; {len(candidates)} are not among "
                f"the {len(recorded)} recorded competitor(s)."
            ),
            data={
                "recurring": [{"domain": p.domain, "notes": p.notes} for p in profiles],
                "recorded_not_observed": not_observed,
            },
            provenance=provenance,
        )

        for profile in candidates:
            workspace.find(
                key="competitor.candidate",
                title=f"{profile.domain} recurs in the brand's results pages",
                detail=profile.notes
                + (" Synthetic domain: not proposed as a competitor." if synthetic else ""),
                severity="info" if synthetic else "medium",
                data={"domain": profile.domain, "priority": profile.priority},
                evidence=[evidence],
            )
            if synthetic:
                continue
            workspace.recommend(
                ProposedRecommendation(
                    type="competitor.review",
                    title=f"Review {profile.domain} as a search competitor",
                    problem=(
                        f"{profile.domain} competes for the brand's queries but is not in the "
                        "recorded competitor list."
                    ),
                    opportunity="Competitive analysis would include who actually wins the results.",
                    reason=profile.notes,
                    business_impact=5.0,
                    seo_impact=6.0,
                    effort=1.0,
                    risk=RiskLevel.LOW,
                    confidence=0.7,
                    expected_outcome="The competitor list reflects observed search competition.",
                    evidence_ids=[evidence.id],
                )
            )
        if not_observed:
            workspace.find(
                key="competitor.recorded_not_observed",
                title=f"{len(not_observed)} recorded competitor(s) never appear in the results",
                detail=(
                    "They may be business competitors, but for these queries they are not "
                    "search competitors: " + ", ".join(not_observed) + "."
                ),
                data={"domains": not_observed},
                evidence=[evidence],
            )

        output = CompetitorDiscoveryOutput(
            brand_id=str(payload.brand_id),
            serps_analysed=len(snapshots),
            synthetic=synthetic,
            candidates=[
                {
                    "domain": p.domain,
                    "priority": p.priority,
                    "notes": p.notes,
                    "synthetic": synthetic,
                }
                for p in candidates
            ],
            recorded_observed=[{"domain": p.domain, "notes": p.notes} for p in observed_recorded],
            recorded_not_observed=not_observed,
            brand_graph_changed=False,
        )
        workspace.outputs["competitor_discovery"] = output.model_dump(mode="json")
        workspace.metrics["competitor_candidates"] = float(0 if synthetic else len(candidates))

        return (
            f"Analysed {len(snapshots)} results page(s): {len(candidates)} recurring domain(s) "
            f"are not recorded competitors and {len(not_observed)} recorded competitor(s) never "
            "appear. "
            + (
                "The SERP data is synthetic, so no candidate is proposed."
                if synthetic
                else "Candidates are proposals; the brand graph was not changed."
            )
        )


AGENT = CompetitorDiscoveryAgent
