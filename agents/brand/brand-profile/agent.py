"""BRD-002 — Brand Profile Agent.

The brand graph is the customer's account of their business; the website is a
second account, written for visitors. Where they disagree, one is out of date —
and every downstream analysis inherits whichever premise is wrong.

This agent compares the two and reports the differences as proposals. Text
extracted from the site is untrusted data: it is compared and counted, never
followed, and never written into the brand graph. Only the customer can confirm
a fact about their own business, so ``brand_graph_changed`` is always false.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, load_page_facts
from seo_engine.engines.brand.profile import DeclaredItem, compare_profile
from seo_engine.schemas.agent import AgentContext, ProposedRecommendation
from seo_engine.schemas.enums import EvidenceType, RiskLevel, SynthesisMode

_schemas = load_agent_module(__file__)
BrandProfileInput = _schemas.BrandProfileInput
BrandProfileOutput = _schemas.BrandProfileOutput


class BrandProfileAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = BrandProfileInput.model_validate(context.inputs)
        facts = await load_brand_facts(context, payload.brand_id)
        pages = await load_page_facts(context, payload.website_id)
        if not pages:
            workspace.limitation(
                "No crawled pages are available, so the profile could not be compared with "
                "the website. Run the technical audit first."
            )
            return "No crawled pages were available to compare with the brand profile."

        declared = [
            DeclaredItem("service", name, terms=terms, landing_url=url)
            for name, terms, url in facts.services
        ] + [
            DeclaredItem("location", name, terms=[city] if city else [])
            for name, city in facts.locations
        ]
        if not declared:
            workspace.limitation(
                "The brand profile declares no services or locations, so there is nothing "
                "to confirm against the site."
            )

        comparison = compare_profile(pages, declared, brand_name=facts.name)
        evidence = workspace.observe(
            evidence_type=EvidenceType.CRAWL_RESULT,
            source="brand_profile_engine",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Compared {len(declared)} declared service(s) and location(s) with "
                f"{comparison.pages_compared} crawled page(s): {len(comparison.covered)} "
                f"covered, {len(comparison.proposals)} difference(s)."
            ),
            data={
                "covered": comparison.covered,
                "proposals": [p.as_dict() for p in comparison.proposals],
            },
        )

        for proposal in comparison.proposals:
            missing = proposal.proposal == "declared_not_found"
            workspace.find(
                key=f"brand_profile.{proposal.proposal}",
                title=(
                    f"{proposal.kind.capitalize()} '{proposal.subject}' "
                    + ("is not described on the site" if missing else "is not in the profile")
                ),
                detail=proposal.detail,
                severity="medium" if missing and proposal.kind == "service" else "low",
                data=proposal.as_dict(),
                evidence=[evidence],
            )
            workspace.recommend(
                ProposedRecommendation(
                    type="brand.profile_review",
                    title=(
                        f"Confirm whether '{proposal.subject}' is still offered"
                        if missing
                        else f"Decide whether '{proposal.subject}' belongs in the brand profile"
                    ),
                    problem=proposal.detail,
                    opportunity=(
                        "Analysis built on an accurate profile targets what the business "
                        "actually sells."
                    ),
                    reason="The profile and the website disagree; one of them is out of date.",
                    business_impact=6.0 if proposal.kind == "service" else 4.0,
                    seo_impact=3.0,
                    effort=1.0,
                    risk=RiskLevel.LOW,
                    confidence=0.7,
                    expected_outcome="A brand profile that matches the live website.",
                    evidence_ids=[evidence.id],
                )
            )

        output = BrandProfileOutput(
            brand_id=str(payload.brand_id),
            pages_compared=comparison.pages_compared,
            covered=comparison.covered,
            proposals=[p.as_dict() for p in comparison.proposals],
            vocabulary=comparison.vocabulary,
            brand_graph_changed=False,
        )
        workspace.outputs["brand_profile"] = output.model_dump(mode="json")
        workspace.metrics["profile_differences"] = float(len(comparison.proposals))

        return (
            f"Compared the brand profile with {comparison.pages_compared} crawled page(s): "
            f"{len(comparison.covered)} declared item(s) are covered on the site and "
            f"{len(comparison.proposals)} difference(s) need the customer's confirmation. "
            "The brand profile was not changed."
        )


AGENT = BrandProfileAgent
