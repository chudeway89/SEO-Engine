"""SEO-005 — Keyword Cluster Agent.

Keyword research clusters keywords and maps each to its best page. This agent
reads that mapping as architecture:

* **cannibalisation** — a cluster whose keywords map to several URLs, or two
  pages whose titles target the same terms, splits relevance instead of
  building it; the agent names the page best placed to own the topic;
* **hub and spoke** — each cluster's supporting pages should link to its hub;
  the observed internal link graph says whether they do.

It proposes consolidation and internal links as evidenced opportunity seeds.
It does not decide to merge or redirect anything: consolidation is a
medium-risk change the decision gate and a human approve.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_page_facts
from seo_engine.engines.keywords.architecture import (
    MappedKeyword,
    cluster_structures,
    find_cannibalisation,
)
from seo_engine.engines.opportunities.detection import seed
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import EvidenceType, OpportunityType, RiskLevel, SynthesisMode

_schemas = load_agent_module(__file__)
KeywordClusterInput = _schemas.KeywordClusterInput
KeywordClusterOutput = _schemas.KeywordClusterOutput


class KeywordClusterAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = KeywordClusterInput.model_validate(context.inputs)
        search = context.service("search")
        clusters = {str(c.id): c for c in await search.list_clusters(payload.brand_id, limit=500)}
        keywords = await search.list_keywords(payload.brand_id, limit=2000)

        if not clusters:
            workspace.limitation(
                "No keyword clusters exist for this brand, so no architecture can be "
                "assessed. Run keyword research first."
            )
            return "No keyword clusters exist, so no topical architecture was assessed."

        mapped = [
            MappedKeyword(
                keyword=k.keyword,
                cluster_id=str(k.cluster_id) if k.cluster_id else None,
                cluster_label=clusters[str(k.cluster_id)].label
                if k.cluster_id and str(k.cluster_id) in clusters
                else None,
                mapped_url=k.mapped_url,
                opportunity_score=k.opportunity_score,
                is_head=bool(
                    k.cluster_id
                    and str(k.cluster_id) in clusters
                    and clusters[str(k.cluster_id)].head_keyword == k.keyword
                ),
            )
            for k in keywords
            if not k.is_branded
        ]
        pages = await load_page_facts(context, payload.website_id)
        links = []
        if payload.website_id is not None:
            links = [
                (link.source_url, link.target_url)
                for link in await context.service("websites").list_links(payload.website_id)
            ]
        else:
            workspace.limitation(
                "No website was supplied, so the internal link graph is unavailable and "
                "hub-and-spoke linking was not assessed."
            )

        cannibalisation = find_cannibalisation(mapped, pages)
        structures = cluster_structures(mapped, links) if links else []
        unlinked = [s for s in structures if s.spokes_missing_hub_link]

        overview = workspace.observe(
            evidence_type=EvidenceType.KEYWORD,
            source="architecture_engine",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Read {len(clusters)} cluster(s) and {len(links)} internal link(s): "
                f"{len(cannibalisation)} cannibalisation case(s) and {len(unlinked)} "
                "cluster(s) with spokes that do not link to their hub."
            ),
            data={
                "clusters": len(clusters),
                "links": len(links),
                "cannibalisation": len(cannibalisation),
                "unlinked_clusters": len(unlinked),
            },
            # Derived from the pipeline's mapping, so recorded as an inference.
            confidence=0.8,
        )

        seeds = []
        for case in cannibalisation[: payload.max_findings]:
            evidence = workspace.observe(
                evidence_type=EvidenceType.KEYWORD,
                source="architecture_engine",
                reference=case.recommended_primary,
                observation=(
                    f"Topic '{case.topic}': {case.basis}. Competing URLs: {', '.join(case.urls)}."
                ),
                data=case.as_dict(),
                confidence=0.75 if case.cluster_id else 0.6,
            )
            workspace.find(
                key="architecture.cannibalisation",
                title=f"{len(case.urls)} pages compete for '{case.topic}'",
                detail=(
                    f"{case.basis.capitalize()}. {case.recommended_primary} is best placed "
                    "to own the topic; the others should support or merge into it."
                ),
                severity="medium",
                data=case.as_dict(),
                evidence=[evidence],
            )
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.CONTENT_CONSOLIDATE,
                    title=f"Consolidate '{case.topic}' into {case.recommended_primary}",
                    description=(
                        f"{case.basis.capitalize()}; consolidating concentrates relevance "
                        "on one page."
                    ),
                    business_impact=5.5,
                    seo_impact=7.0,
                    effort=6.0,
                    confidence=0.7 if case.cluster_id else 0.55,
                    evidence_refs=[evidence.id, overview.id],
                    target_url=case.recommended_primary,
                    risk=RiskLevel.MEDIUM,
                    source_agent=self.manifest.id,
                    data={"urls": case.urls},
                )
            )

        for structure in unlinked[: payload.max_findings]:
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="architecture_engine",
                reference=structure.hub_url or structure.label,
                observation=(
                    f"Cluster '{structure.label}': {len(structure.spokes_missing_hub_link)} of "
                    f"{len(structure.spokes)} supporting page(s) do not link to the hub "
                    f"{structure.hub_url}."
                ),
                data=structure.as_dict(),
            )
            workspace.find(
                key="architecture.missing_hub_links",
                title=f"Spokes of '{structure.label}' do not link to their hub",
                detail=f"Add links from {', '.join(structure.spokes_missing_hub_link[:5])}.",
                severity="low",
                data=structure.as_dict(),
                evidence=[evidence],
            )
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.INTERNAL_LINKING,
                    title=f"Link the '{structure.label}' spokes to {structure.hub_url}",
                    description=(
                        f"{len(structure.spokes_missing_hub_link)} supporting page(s) do not "
                        "link to the cluster's hub, so it lacks the internal signal that it "
                        "is the authoritative page."
                    ),
                    business_impact=4.0,
                    seo_impact=5.5,
                    effort=2.0,
                    confidence=0.7,
                    evidence_refs=[evidence.id],
                    target_url=structure.hub_url,
                    source_agent=self.manifest.id,
                    data={"from_urls": structure.spokes_missing_hub_link},
                )
            )

        output = KeywordClusterOutput(
            brand_id=str(payload.brand_id),
            clusters_analysed=len(clusters),
            clusters_with_pages=len(structures),
            healthy_clusters=sum(1 for s in structures if s.healthy),
            cannibalisation=[c.as_dict() for c in cannibalisation[:50]],
            structures=[s.as_dict() for s in structures[:100]],
        )
        workspace.outputs["keyword_architecture"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["cannibalisation_cases"] = float(len(cannibalisation))

        return (
            f"Assessed the architecture of {len(clusters)} keyword cluster(s): "
            f"{len(cannibalisation)} cannibalisation case(s), and {len(unlinked)} cluster(s) "
            "whose supporting pages do not link to their hub."
        )


AGENT = KeywordClusterAgent
