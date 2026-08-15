"""SEO-003 — Keyword Intelligence Agent.

Runs the keyword pipeline over the brand graph and whatever measured demand is
actually available. Its most important behaviour is what it does *not* do: with
no keyword data provider connected, it produces keywords with
``search_volume = None`` and ``provenance = unknown``, and says so in its
limitations, rather than estimating a number that would then propagate through
every downstream score.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.keywords.pipeline import (
    KeywordInputs,
    build_keyword_records,
    cluster_keywords,
)
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode


class KeywordResearchInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_keywords: int = 300


class KeywordResearchOutput(BaseModel):
    brand_id: str
    keywords_total: int = 0
    clusters_total: int = 0
    measured_demand_available: bool = False
    sources_used: list[str] = Field(default_factory=list)
    top_keywords: list[dict[str, Any]] = Field(default_factory=list)
    clusters: list[dict[str, Any]] = Field(default_factory=list)
    intent_distribution: dict[str, int] = Field(default_factory=dict)


class KeywordIntelligenceAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = KeywordResearchInput.model_validate(context.inputs)
        brands = context.service("brands")
        profile = await brands.profile(payload.brand_id)

        # --- measured demand, only if Search Console is genuinely connected ---
        observed_queries: list[tuple[str, int, int, float]] = []
        sources = ["brand_graph"]
        if workspace.note_unavailable_tool("gsc"):
            integrations = context.services.get("integrations")
            if integrations is not None:
                observed_queries = await integrations.top_queries(payload.brand_id, limit=200)
                sources.append("google_search_console")

        if not observed_queries:
            workspace.limitation(
                "No measured search demand was available, so no keyword carries a "
                "volume figure. The demand dimension contributes zero to every score "
                "rather than an estimate, and relative ranking rests on business "
                "relevance, intent and competitive gap only."
            )

        # --- pages, for keyword-to-URL mapping --------------------------------
        pages: dict[str, dict] = {}
        if payload.website_id is not None:
            websites = context.service("websites")
            for page in await websites.list_pages(payload.website_id, limit=500):
                pages[page.url] = {
                    "title": page.title or "",
                    "h1": page.h1 or "",
                    "text": (page.text_content or "")[:4000],
                }

        inputs = KeywordInputs(
            brand_name=profile["brand"].name,
            services=[s.name for s in profile["services"]],
            products=[p.name for p in profile["products"]],
            locations=[loc.city or loc.region or loc.name for loc in profile["locations"]],
            audience_vocabulary=[
                term for a in profile["audiences"] for term in (a.vocabulary or [])
            ],
            audience_pains=[term for a in profile["audiences"] for term in (a.pains or [])],
            existing_keywords=[
                keyword for s in profile["services"] for keyword in (s.keywords or [])
            ],
            observed_queries=observed_queries,
        )

        records = build_keyword_records(
            inputs, pages=pages or None, max_keywords=payload.max_keywords
        )
        if not records:
            workspace.limitation(
                "The brand graph contains no services, products, audience vocabulary or "
                "observed queries, so there is nothing to derive keywords from. No "
                "keywords have been invented."
            )
            return (
                "No keywords could be derived: the brand profile contains no services, "
                "products or audience vocabulary, and no search data is connected."
            )

        clusters = cluster_keywords(records)
        search_service = context.services.get("search")
        if search_service is not None:
            await search_service.store(payload.brand_id, records, clusters)

        # --- evidence ---------------------------------------------------------
        seed_evidence = workspace.observe(
            evidence_type=EvidenceType.KEYWORD,
            source="keyword_pipeline",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Derived {len(records)} keyword(s) in {len(clusters)} cluster(s) from "
                f"{len(inputs.services)} service(s), {len(inputs.products)} product(s) and "
                f"{len(observed_queries)} observed Search Console quer(y/ies)."
            ),
            data={
                "keywords": len(records),
                "clusters": len(clusters),
                "observed_queries": len(observed_queries),
                "sources": sources,
            },
            provenance=(DataProvenance.OBSERVED if observed_queries else DataProvenance.INFERRED),
        )

        if observed_queries:
            top = sorted(observed_queries, key=lambda q: -q[1])[:5]
            workspace.observe(
                evidence_type=EvidenceType.GSC,
                source="google_search_console",
                reference=f"brand:{payload.brand_id}",
                observation=(
                    "Highest-impression observed queries: "
                    + "; ".join(
                        f"{q} ({impressions} impressions, position {position:.1f})"
                        for q, impressions, _clicks, position in top
                    )
                ),
                data={"queries": [{"query": q, "impressions": i} for q, i, _, _ in top]},
            )

        intent_counts: dict[str, int] = {}
        for record in records:
            key = record.intent.primary.value
            intent_counts[key] = intent_counts.get(key, 0) + 1

        commercial = [
            r for r in records if r.intent.primary.value in {"commercial", "transactional", "local"}
        ]
        workspace.find(
            key="keywords.commercial_share",
            title=f"{len(commercial)} of {len(records)} keywords carry commercial intent",
            detail=(
                "Commercial, transactional and local intent sit closest to a business "
                "outcome, and are weighted accordingly in the opportunity model."
            ),
            data={"intent_distribution": intent_counts},
            evidence=[seed_evidence],
        )

        unmapped = [r for r in records if not r.mapped_url]
        if pages and unmapped:
            workspace.find(
                key="keywords.unmapped",
                title=f"{len(unmapped)} keyword(s) have no page targeting them",
                detail=(
                    "These are candidates for the content gap stage, which decides "
                    "whether each one justifies a page at all."
                ),
                severity="medium",
                data={"examples": [r.keyword for r in unmapped[:20]]},
                evidence=[seed_evidence],
            )

        output = KeywordResearchOutput(
            brand_id=str(payload.brand_id),
            keywords_total=len(records),
            clusters_total=len(clusters),
            measured_demand_available=bool(observed_queries),
            sources_used=sources,
            top_keywords=[
                {
                    "keyword": r.keyword,
                    "opportunity_score": r.score.opportunity_score,
                    "primary_intent": r.intent.primary.value,
                    "mapped_url": r.mapped_url,
                    "is_branded": r.is_branded,
                    "is_local": r.is_local,
                    "measured_dimensions": r.score.dimensions_with_observed_data,
                }
                for r in records[:30]
            ],
            clusters=[
                {
                    "id": c.id,
                    "label": c.label,
                    "head_keyword": c.head_keyword,
                    "keywords": c.keywords,
                    "opportunity_score": c.opportunity_score,
                    "primary_intent": c.intent.primary.value,
                }
                for c in clusters[:30]
            ],
            intent_distribution=intent_counts,
        )
        workspace.outputs["keyword_research"] = output.model_dump(mode="json")
        workspace.metrics["keywords"] = float(len(records))
        workspace.metrics["clusters"] = float(len(clusters))

        summary = (
            f"Derived {len(records)} keyword(s) in {len(clusters)} topic cluster(s); "
            f"{len(commercial)} carry commercial, transactional or local intent."
        )
        if observed_queries:
            summary += (
                f" {len(observed_queries)} quer(y/ies) carry measured Search Console "
                "demand; the rest are scored without a demand signal."
            )
        else:
            summary += (
                " No search data provider is connected, so no keyword carries a volume "
                "figure and none has been estimated."
            )
        return summary


AGENT = KeywordIntelligenceAgent
