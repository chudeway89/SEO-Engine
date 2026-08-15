"""SEO-006 — Content Gap Agent.

For each topic cluster it decides exactly one of CREATE, UPDATE, CONSOLIDATE,
REDIRECT or DO_NOTHING, and records why.

The decision order is deliberately biased against publishing: competing pages
are consolidated, a good page is left alone, a weak page is updated, and a new
page requires a stated reason. A cluster with no demand, no competitor coverage
and no SERP evidence returns DO_NOTHING — a keyword on its own is never a reason
to publish (Rule 13).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.competitors.analysis import CompetitorPages, analyse_content_gap
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.crawl import CrawlPage
from seo_engine.schemas.enums import (
    ContentDecision,
    DataProvenance,
    EvidenceType,
    SynthesisMode,
)
from seo_engine.schemas.search import IntentDistribution, KeywordCluster
from seo_engine.shared.ids import utcnow


class ContentGapInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    max_clusters: int = 25


class ContentGapOutput(BaseModel):
    brand_id: str
    clusters_evaluated: int = 0
    decisions: dict[str, int] = Field(default_factory=dict)
    gaps: list[dict[str, Any]] = Field(default_factory=list)


class ContentGapAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentGapInput.model_validate(context.inputs)
        search = context.service("search")
        clusters = await search.list_clusters(payload.brand_id, limit=payload.max_clusters)

        if not clusters:
            workspace.limitation(
                "No keyword clusters exist for this brand, so no content gap could be "
                "evaluated. Run keyword research first."
            )
            return "No content gaps could be evaluated: there are no keyword clusters."

        # --- the brand's existing pages ---------------------------------------
        brand_pages: dict[str, CrawlPage] = {}
        if payload.website_id is not None:
            websites = context.service("websites")
            for page in await websites.list_pages(payload.website_id, limit=500):
                brand_pages[page.url] = _to_crawl_page(page)

        if not brand_pages:
            workspace.limitation(
                "No crawled pages are available for this brand, so every topic looks "
                "uncovered. Decisions here should be treated as provisional until the "
                "website has been crawled."
            )

        # --- competitor pages observed upstream --------------------------------
        competitor_pages: dict[str, CompetitorPages] = {}
        upstream = context.inputs.get("competitor_pages") or {}
        for domain, urls in upstream.items():
            competitor_pages[domain] = CompetitorPages(
                domain=domain,
                pages=[
                    CrawlPage(url=url, status_code=200, title=url, fetched_at=utcnow())
                    for url in urls
                ],
            )

        decisions: dict[str, int] = {}
        gaps: list[Any] = []

        for row in clusters:
            cluster = KeywordCluster(
                id=str(row.id),
                label=row.label,
                head_keyword=row.head_keyword,
                keywords=[row.head_keyword],
                intent=IntentDistribution(**(row.intent or {})),
                opportunity_score=row.opportunity_score,
            )
            gap = analyse_content_gap(
                cluster,
                brand_pages=brand_pages,
                competitors=competitor_pages,
                demand_signal=row.opportunity_score if row.opportunity_score else None,
                demand_provenance=DataProvenance.INFERRED,
            )

            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_gap_engine",
                reference=gap.target_url or f"cluster:{row.id}",
                observation=(
                    f"Topic '{gap.topic}': decision {gap.decision.value.upper()}. "
                    f"{gap.decision_reason}"
                ),
                data={
                    "decision": gap.decision.value,
                    "brand_coverage": gap.brand_coverage,
                    "competitor_coverage": gap.competitor_coverage,
                    "existing_page_quality": gap.existing_page_quality,
                    "target_url": gap.target_url,
                },
                confidence=gap.confidence,
            )
            gap.evidence_ids = [evidence.id]
            gaps.append(gap)
            decisions[gap.decision.value] = decisions.get(gap.decision.value, 0) + 1

        actionable = [g for g in gaps if g.decision is not ContentDecision.DO_NOTHING]
        for gap in actionable[:10]:
            workspace.find(
                key=f"content_gap.{gap.decision.value}",
                title=f"{gap.decision.value.replace('_', ' ').title()}: {gap.topic}",
                detail=gap.decision_reason,
                severity="medium",
                data=gap.model_dump(mode="json"),
                evidence=[e for e in workspace.evidence if e.id in gap.evidence_ids],
            )

        do_nothing = decisions.get(ContentDecision.DO_NOTHING.value, 0)
        workspace.outputs["content_gaps"] = [g.model_dump(mode="json") for g in gaps]
        output = ContentGapOutput(
            brand_id=str(payload.brand_id),
            clusters_evaluated=len(gaps),
            decisions=decisions,
            gaps=[g.model_dump(mode="json") for g in gaps[:50]],
        )
        workspace.outputs["content_gap"] = output.model_dump(mode="json")
        workspace.metrics["clusters_evaluated"] = float(len(gaps))
        workspace.metrics["actionable_gaps"] = float(len(actionable))

        return (
            f"Evaluated {len(gaps)} topic cluster(s): "
            + ", ".join(
                f"{count} {decision.replace('_', ' ')}"
                for decision, count in sorted(decisions.items())
            )
            + f". {do_nothing} topic(s) do not justify any content action, which is a "
            "result in itself rather than a gap."
        )


def _to_crawl_page(page: Any) -> CrawlPage:
    from seo_engine.schemas.crawl import Heading

    return CrawlPage(
        url=page.url,
        status_code=page.status_code,
        title=page.title,
        meta_description=page.meta_description,
        canonical_url=page.canonical_url,
        meta_robots=page.meta_robots or [],
        headings=[Heading(level=1, text=page.h1)] if page.h1 else [],
        word_count=page.word_count,
        content_hash=page.content_hash,
        text_content=(page.text_content or "")[:8000],
        fetched_at=page.last_crawled_at or utcnow(),
    )


AGENT = ContentGapAgent
