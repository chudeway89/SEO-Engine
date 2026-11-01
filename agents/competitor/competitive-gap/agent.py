"""CMP-003 — Competitive Gap Agent.

Competitor analysis says which topics competitors *cover*; SERP research says
who is *visible*. Neither alone is a gap worth acting on. This agent joins the
two and scores each topic by a transparent sum (``SCORING``): coverage the brand
lacks, plus a competitor on page one where the brand is not.

Coverage comes from crawled competitor pages and is an observation. Visibility
comes from SERP snapshots and inherits their provenance: a gap that rests only
on synthetic SERP data is reported, labelled, and kept out of the opportunity
pipeline, because no decision should rest on a results page nobody observed.
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
from seo_engine.engines.competitors.gap import SCORING, competitive_gaps
from seo_engine.engines.opportunities.detection import seed
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, OpportunityType, SynthesisMode

_schemas = load_agent_module(__file__)
CompetitiveGapInput = _schemas.CompetitiveGapInput
CompetitiveGapOutput = _schemas.CompetitiveGapOutput


class CompetitiveGapAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = CompetitiveGapInput.model_validate(context.inputs)
        snapshots = [
            s
            for s in await context.service("search").latest_snapshots(payload.brand_id)
            if s.available
        ]
        if not payload.keyword_gaps:
            workspace.limitation(
                "No coverage gaps were supplied by competitor analysis, so only "
                "visibility can be compared."
            )
        if not snapshots:
            workspace.limitation(
                "No results pages have been observed, so visibility cannot be compared; "
                "only coverage gaps are reported."
            )
        if not payload.keyword_gaps and not snapshots:
            return (
                "No competitive gap could be assessed: neither coverage nor visibility "
                "data is available."
            )

        provenance = snapshots_provenance(snapshots)
        synthetic = provenance is DataProvenance.SYNTHETIC_DEMO
        if synthetic:
            workspace.limitation(SYNTHETIC_SERP_LIMITATION)

        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)
        competitors = set(facts.competitors) | set(payload.discovered_competitors)
        gaps = competitive_gaps(
            keyword_gaps=payload.keyword_gaps,
            snapshots=snapshots,
            brand_domain=facts.domain,
            competitor_domains=competitors,
        )

        by_type: dict[str, int] = {}
        for gap in gaps:
            label = "+".join(gap.gap_types)
            by_type[label] = by_type.get(label, 0) + 1

        seeds = []
        for gap in gaps[: payload.max_findings]:
            coverage_backed = "coverage" in gap.gap_types
            evidence = workspace.observe(
                evidence_type=EvidenceType.COMPETITOR,
                source="competitive_gap_engine",
                reference=gap.topic,
                observation=f"'{gap.topic}': {gap.detail}",
                data=gap.as_dict(),
                # Coverage is crawled and observed; a visibility-only gap is only as
                # real as the SERP behind it.
                provenance=(
                    DataProvenance.OBSERVED
                    if coverage_backed or not gap.synthetic
                    else DataProvenance.SYNTHETIC_DEMO
                ),
            )
            workspace.find(
                key=f"competitive_gap.{'_'.join(gap.gap_types)}",
                title=f"Competitive gap on '{gap.topic}' (score {gap.score:.0f})",
                detail=gap.detail,
                severity="medium" if gap.score >= 60 else "low",
                data=gap.as_dict(),
                evidence=[evidence],
            )
            if gap.synthetic and not coverage_backed:
                continue
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.COMPETITOR_GAP,
                    title=f"Close the competitive gap on '{gap.topic}'",
                    description=gap.detail,
                    business_impact=4.0 + gap.score / 20,
                    seo_impact=4.0 + gap.score / 25,
                    effort=6.0,
                    confidence=0.6 if gap.synthetic else 0.7,
                    evidence_refs=[evidence.id],
                    target_url=gap.brand_url,
                    source_agent=self.manifest.id,
                    data={"gap_types": gap.gap_types, "competitors": gap.competitors},
                )
            )

        output = CompetitiveGapOutput(
            brand_id=str(payload.brand_id),
            gaps_total=len(gaps),
            by_type=by_type,
            synthetic_serp=synthetic,
            scoring=SCORING,
            gaps=[g.as_dict() for g in gaps[:50]],
        )
        workspace.outputs["competitive_gap"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["competitive_gaps"] = float(len(gaps))

        return (
            f"Found {len(gaps)} competitive gap(s): "
            + (", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) or "none")
            + f". {len(seeds)} were handed to opportunity detection."
            + (" Visibility data is synthetic." if synthetic else "")
        )


AGENT = CompetitiveGapAgent
