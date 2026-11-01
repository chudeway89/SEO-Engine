"""CMP-002 — Competitor Analysis Agent.

Crawls the competitors the customer actually recorded, within the same
safeguards as the brand's own crawl, and compares topical coverage.

Everything it asserts is grounded in pages it fetched. A competitor it could not
reach produces no gaps — the failure is reported as a limitation rather than
becoming an absence of coverage on the competitor's side.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.competitors.analysis import (
    CompetitorPages,
    coverage_comparison,
    keyword_gaps,
)
from seo_engine.engines.crawler.crawler import WebsiteCrawler, config_from_settings
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import CompetitorType, EvidenceType, SynthesisMode

#: Competitor crawls are deliberately shallow: enough to see what a competitor
#: covers, never enough to mirror their site.
COMPETITOR_MAX_PAGES = 25
COMPETITOR_MAX_DEPTH = 2


class CompetitorAnalysisInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    keywords: list[str] = Field(default_factory=list)
    max_competitors: int = 5


class CompetitorAnalysisOutput(BaseModel):
    brand_id: str
    competitors_analysed: int = 0
    competitors_unreachable: list[str] = Field(default_factory=list)
    pages_observed: int = 0
    keyword_gaps: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    competitor_pages: dict[str, list[str]] = Field(default_factory=dict)


class CompetitorAnalysisAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = CompetitorAnalysisInput.model_validate(context.inputs)
        brands = context.service("brands")
        competitors = await brands.list_competitors(payload.brand_id)

        if not competitors:
            workspace.limitation(
                "No competitors are recorded for this brand, so no competitive gap can "
                "be asserted. Add competitors to enable this analysis."
            )
            return (
                "No competitor analysis was possible: the brand has no competitors "
                "recorded. Nothing has been inferred about the competitive landscape."
            )

        if not workspace.note_unavailable_tool("crawler"):
            return (
                "No competitor pages could be fetched because the crawler tool was not "
                "granted to this run."
            )

        # --- the brand's own pages, for comparison ---------------------------
        brand_pages: dict[str, dict] = {}
        if payload.website_id is not None:
            websites = context.service("websites")
            for page in await websites.list_pages(payload.website_id, limit=300):
                brand_pages[page.url] = {"title": page.title or "", "h1": page.h1 or ""}

        # --- crawl each competitor -------------------------------------------
        crawler_factory = context.services.get("crawler_factory")
        observed: dict[str, CompetitorPages] = {}
        unreachable: list[str] = []
        total_pages = 0

        for competitor in competitors[: payload.max_competitors]:
            config = config_from_settings(
                max_pages=COMPETITOR_MAX_PAGES,
                max_depth=COMPETITOR_MAX_DEPTH,
                allowed_domains=[competitor.domain],
            )
            crawler = crawler_factory(config) if crawler_factory else WebsiteCrawler(config)
            try:
                result = await crawler.crawl(f"https://{competitor.domain}/")
            except Exception as exc:
                unreachable.append(competitor.domain)
                workspace.limitation(
                    f"{competitor.domain} could not be crawled ({type(exc).__name__}), "
                    "so no coverage is claimed for it either way."
                )
                continue

            pages = [p for p in result.pages if not p.error and p.is_indexable]
            if not pages:
                unreachable.append(competitor.domain)
                workspace.limitation(
                    f"{competitor.domain} returned no indexable pages "
                    + (f"({result.stopped_reason})" if result.stopped_reason else "")
                    + ", so no coverage is claimed for it."
                )
                continue

            observed[competitor.domain] = CompetitorPages(domain=competitor.domain, pages=pages)
            total_pages += len(pages)

            evidence = workspace.observe(
                evidence_type=EvidenceType.COMPETITOR,
                source="crawler",
                reference=f"https://{competitor.domain}/",
                observation=(
                    f"Crawled {len(pages)} indexable page(s) on {competitor.domain}. "
                    f"Observed topics include: "
                    + ", ".join(sorted({p.title for p in pages if p.title})[:6])
                    + "."
                ),
                data={
                    "domain": competitor.domain,
                    "pages_observed": len(pages),
                    "urls": [p.url for p in pages][:25],
                },
            )

            # A recorded business competitor is only a *content* competitor once
            # we have actually seen its content.
            types = set(competitor.competitor_types)
            types.add(CompetitorType.CONTENT.value)
            competitor.competitor_types = sorted(types)
            competitor.observations = {
                **(competitor.observations or {}),
                "pages_observed": len(pages),
                "evidence_ref": evidence.id,
            }

        if not observed:
            return (
                f"None of the {len(competitors)} recorded competitor(s) could be "
                "crawled, so no competitive gaps are asserted."
            )

        # --- gaps --------------------------------------------------------------
        gaps = keyword_gaps(
            brand_pages=brand_pages,
            competitors=observed,
            keywords=payload.keywords,
        )
        comparison = coverage_comparison(
            brand_pages={url: _as_page(page) for url, page in brand_pages.items()},
            competitors=observed,
        )

        if gaps:
            gap_evidence = workspace.observe(
                evidence_type=EvidenceType.COMPETITOR,
                source="competitor_analysis",
                reference=f"brand:{payload.brand_id}",
                observation=(
                    f"{len(gaps)} keyword(s) are addressed by at least one competitor "
                    "page and by no observed brand page."
                ),
                data={"gaps": [g.keyword for g in gaps][:30]},
            )
            workspace.find(
                key="competitor.keyword_gaps",
                title=f"{len(gaps)} keyword gap(s) against observed competitors",
                detail=(
                    "Each gap names the competitor domains whose pages address the "
                    "term. Whether any of them justifies a page is decided by the "
                    "content gap stage, not here."
                ),
                severity="medium",
                data={"top": [g.model_dump(mode="json") for g in gaps[:10]]},
                evidence=[gap_evidence],
            )

        output = CompetitorAnalysisOutput(
            brand_id=str(payload.brand_id),
            competitors_analysed=len(observed),
            competitors_unreachable=unreachable,
            pages_observed=total_pages,
            keyword_gaps=[g.model_dump(mode="json") for g in gaps[:50]],
            coverage=comparison,
            competitor_pages={
                domain: [p.url for p in pages.pages][:25] for domain, pages in observed.items()
            },
        )
        workspace.outputs["competitor_analysis"] = output.model_dump(mode="json")
        workspace.metrics["competitors_analysed"] = float(len(observed))
        workspace.metrics["keyword_gaps"] = float(len(gaps))

        summary = (
            f"Analysed {len(observed)} competitor(s) across {total_pages} observed "
            f"page(s) and found {len(gaps)} keyword gap(s)."
        )
        if unreachable:
            summary += (
                f" {len(unreachable)} competitor(s) could not be crawled "
                f"({', '.join(unreachable)}); no coverage is claimed for them."
            )
        return summary


def _as_page(page_dict: dict) -> Any:
    """Adapt the stored page shape to what the coverage comparison expects."""
    from seo_engine.schemas.crawl import CrawlPage
    from seo_engine.shared.ids import utcnow

    return CrawlPage(
        url="stored",
        status_code=200,
        title=page_dict.get("title"),
        fetched_at=utcnow(),
    )


AGENT = CompetitorAnalysisAgent
