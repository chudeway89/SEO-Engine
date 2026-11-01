"""SEO-001 — Technical SEO Agent.

Crawls the website within its configured safeguards and runs the deterministic
check engine over the result. Every finding is a rule over observed data, so it
is reproducible and explainable; the agent's own contribution is to *interpret*
which findings matter, never to detect them.

Crawled page copy stays untrusted throughout: it is stored with its untrusted
marking, and any injection attempt found in it is reported as a security finding
rather than acted on.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.crawler.crawler import WebsiteCrawler, config_from_settings
from seo_engine.engines.seo.checks import run_all_checks
from seo_engine.engines.seo.readiness import (
    assess_agentic_web_readiness,
    assess_ai_search_readiness,
)
from seo_engine.engines.seo.scoring import build_audit_report
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import EvidenceType, IssueSeverity, SEODimension, SynthesisMode


class TechnicalAuditInput(BaseModel):
    website_id: UUID
    brand_id: UUID
    max_pages: int | None = None
    max_depth: int | None = None


class TechnicalAuditOutput(BaseModel):
    website_id: str
    crawl_job_id: str | None = None
    pages_crawled: int = 0
    issues_total: int = 0
    issues_by_severity: dict[str, int] = Field(default_factory=dict)
    dimensions: list[dict[str, Any]] = Field(default_factory=list)
    overall_health: float = 0.0
    ai_search_readiness: float | None = None
    agentic_web_readiness: float | None = None
    top_issues: list[dict[str, Any]] = Field(default_factory=list)
    stopped_reason: str | None = None


class TechnicalSEOAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = TechnicalAuditInput.model_validate(context.inputs)
        websites = context.service("websites")

        if not workspace.note_unavailable_tool("crawler"):
            return (
                "No crawl could be performed because the crawler tool was not granted "
                "to this run. No technical findings are available."
            )

        website = await websites.get_website(payload.website_id)
        job = await websites.create_crawl_job(website.id, correlation_id=context.correlation_id)
        await websites.mark_crawl_running(job.id)

        config = config_from_settings(
            max_pages=payload.max_pages,
            max_depth=payload.max_depth,
            allowed_domains=[website.domain],
        )
        crawler = context.services.get("crawler_factory")
        crawl = (
            await crawler(config).crawl(website.base_url, website_id=str(website.id))
            if crawler
            else await WebsiteCrawler(config).crawl(website.base_url, website_id=str(website.id))
        )
        await websites.record_crawl_result(job.id, crawl)

        crawl_evidence = workspace.observe(
            evidence_type=EvidenceType.CRAWL_RESULT,
            source="crawler",
            reference=website.base_url,
            observation=(
                f"Crawled {crawl.pages_crawled} page(s) of {website.domain} within the "
                f"configured limits ({config.max_pages} pages, depth {config.max_depth})."
                + (
                    f" The crawl stopped early: {crawl.stopped_reason}."
                    if crawl.stopped_reason
                    else ""
                )
            ),
            data={
                "pages_crawled": crawl.pages_crawled,
                "errors": crawl.error_count,
                "robots_fetched": crawl.robots.fetched,
                "sitemaps": len(crawl.sitemap.discovered),
                "stopped_reason": crawl.stopped_reason,
            },
        )

        # --- injection attempts found in page copy --------------------------
        injected = [p for p in crawl.pages if p.injection_findings]
        if injected:
            workspace.flag(
                type="prompt_injection_attempt",
                source="crawled_page_content",
                pages=[p.url for p in injected][:20],
                patterns=sorted({f["pattern"] for p in injected for f in p.injection_findings}),
                handling=(
                    "The page copy was stored as untrusted external content and was "
                    "never treated as an instruction."
                ),
            )
            workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="crawler",
                reference=injected[0].url,
                observation=(
                    f"{len(injected)} crawled page(s) contain text resembling an attempt "
                    "to issue instructions to an automated system. The content was "
                    "handled strictly as data."
                ),
                data={"pages": [p.url for p in injected][:20]},
            )

        # --- deterministic checks -------------------------------------------
        issues = run_all_checks(crawl)
        report = build_audit_report(
            crawl, issues, website_id=str(website.id), crawl_job_id=str(job.id)
        )
        await websites.replace_issues(website.id, job.id, issues)
        await websites.store_scorecard(website.id, website.brand_id, job.id, report.scorecard)

        ai_search = assess_ai_search_readiness(
            crawl,
            website_id=str(website.id),
            gsc_connected="gsc" in context.tools and context.tools["gsc"].available,
        )
        agentic = assess_agentic_web_readiness(crawl, website_id=str(website.id))

        # Readiness is reported against the crawl that produced it, so the score
        # can never be read without the coverage it was measured over.
        workspace.find(
            key="technical.readiness",
            title=(
                "AI search readiness "
                + (
                    f"{ai_search.readiness_score:.0f}/100"
                    if ai_search.readiness_score is not None
                    else "could not be scored"
                )
                + f", agentic web readiness {agentic.score:.0f}/100"
            ),
            detail=(
                "Both scores are derived only from signals observed on the "
                f"{crawl.pages_crawled} crawled page(s). "
                + (
                    "Unknown signals: " + ", ".join(ai_search.unknowns) + "."
                    if ai_search.unknowns
                    else "No signal was left unknown."
                )
            ),
            severity="info",
            data={
                "ai_search_readiness": ai_search.readiness_score,
                "ai_search_unknowns": ai_search.unknowns,
                "agentic_web_readiness": agentic.score,
                "agentic_signals": agentic.signals,
                "pages_evaluated": agentic.pages_evaluated,
            },
            evidence=[crawl_evidence],
        )
        for note in ai_search.notes:
            workspace.limitation(note)

        # --- findings --------------------------------------------------------
        by_severity: dict[str, int] = {}
        for issue in issues:
            by_severity[issue.severity.value] = by_severity.get(issue.severity.value, 0) + 1

        for issue in [
            i for i in issues if i.severity in {IssueSeverity.CRITICAL, IssueSeverity.HIGH}
        ][:10]:
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="technical_seo_checks",
                reference=issue.url or website.base_url,
                observation=f"{issue.title}. {issue.detail}".strip(),
                data={
                    "check_id": issue.check_id,
                    "severity": issue.severity.value,
                    "dimension": issue.dimension.value,
                    **issue.evidence_data,
                },
            )
            workspace.find(
                key=f"technical.{issue.check_id}",
                title=issue.title,
                detail=issue.detail,
                severity=issue.severity.value,
                data={"url": issue.url, "recommendation": issue.recommendation},
                evidence=[evidence],
            )

        for dimension in report.scorecard.dimensions:
            if not dimension.evaluated:
                workspace.limitation(
                    f"{dimension.dimension.value.replace('_', ' ').title()} was not "
                    f"evaluated: {dimension.not_evaluated_reason}"
                )

        if crawl.stopped_reason:
            workspace.limitation(
                f"The crawl did not cover the whole site: {crawl.stopped_reason}. "
                "Findings describe the pages that were crawled, not the entire website."
            )

        output = TechnicalAuditOutput(
            website_id=str(website.id),
            crawl_job_id=str(job.id),
            pages_crawled=crawl.pages_crawled,
            issues_total=len(issues),
            issues_by_severity=by_severity,
            dimensions=[d.model_dump(mode="json") for d in report.scorecard.dimensions],
            overall_health=report.scorecard.overall,
            ai_search_readiness=ai_search.readiness_score,
            agentic_web_readiness=agentic.score,
            top_issues=[
                {
                    "check_id": i.check_id,
                    "title": i.title,
                    "severity": i.severity.value,
                    "url": i.url,
                    "recommendation": i.recommendation,
                }
                for i in issues[:20]
            ],
            stopped_reason=crawl.stopped_reason,
        )
        workspace.outputs["technical_audit"] = output.model_dump(mode="json")
        workspace.outputs["crawl_job_id"] = str(job.id)
        workspace.outputs["website_id"] = str(website.id)
        workspace.metrics["pages_crawled"] = float(crawl.pages_crawled)
        workspace.metrics["issues_total"] = float(len(issues))
        workspace.metrics["overall_health"] = report.scorecard.overall

        worst = report.scorecard.dimension(
            min(
                (d.dimension for d in report.scorecard.dimensions if d.evaluated),
                key=lambda dim: next(
                    d.score for d in report.scorecard.dimensions if d.dimension == dim
                ),
                default=SEODimension.TECHNICAL_HEALTH,
            )
        )
        summary = (
            f"Crawled {crawl.pages_crawled} page(s) of {website.domain} and ran "
            f"{len(issues)} deterministic finding(s) across nine dimensions. "
            f"Overall health is {report.scorecard.overall:.0f}/100"
        )
        if worst is not None:
            summary += (
                f", weakest on {worst.dimension.value.replace('_', ' ')} at {worst.score:.0f}/100"
            )
        summary += "."
        if by_severity.get("critical"):
            summary += f" {by_severity['critical']} critical issue(s) need attention first."
        if injected:
            summary += (
                f" {len(injected)} page(s) contained text attempting to instruct an "
                "automated system; it was treated as data and reported."
            )
        return summary

    def confidence(self, workspace: AgentWorkspace) -> float:
        # Deterministic checks over observed pages are high-confidence by nature.
        base = super().confidence(workspace)
        return round(min(0.95, base + 0.1), 2)


AGENT = TechnicalSEOAgent
