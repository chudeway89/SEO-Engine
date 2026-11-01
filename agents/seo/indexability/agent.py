"""SEO-012 — Indexability Agent.

Reconciles three accounts of what should be indexed — the sitemap's, the
crawl's and the business's — and, when Search Console is connected, a fourth:
which URLs are actually earning impressions. Disagreement between declared
intent and observed state is the finding, and a priority landing page that
cannot be indexed is critical however few other issues there are.

Sitemap URLs the bounded crawl never reached are reported as *unverified*. A
crawl budget running out says nothing about those URLs, so the agent claims
nothing about them either way.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, load_page_facts, website_domain
from seo_engine.engines.opportunities.detection import seed
from seo_engine.engines.seo.indexability import reconcile
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import (
    DataProvenance,
    EvidenceType,
    OpportunityType,
    RiskLevel,
    SynthesisMode,
)

_schemas = load_agent_module(__file__)
IndexabilityInput = _schemas.IndexabilityInput
IndexabilityOutput = _schemas.IndexabilityOutput

IMPACT_BY_SEVERITY = {"critical": 9.5, "high": 7.5, "medium": 5.0, "low": 3.0}


class IndexabilityAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = IndexabilityInput.model_validate(context.inputs)
        if payload.website_id is None:
            workspace.limitation("No website was supplied, so index coverage cannot be judged.")
            return "No indexability assessment was possible: no website is connected."

        websites = context.service("websites")
        crawl = await websites.latest_completed_crawl(payload.website_id)
        pages = await load_page_facts(context, payload.website_id, limit=5000)
        if crawl is None or not pages:
            workspace.limitation(
                "The website has not been crawled yet, so there is no observed state to "
                "reconcile. Run the technical audit first."
            )
            return "No crawl exists for this website, so index coverage was not assessed."

        sitemap_urls = [
            entry.get("loc")
            for entry in (crawl.sitemap_report or {}).get("entries", [])
            if isinstance(entry, dict) and entry.get("loc")
        ]
        if not sitemap_urls:
            workspace.limitation(
                "No sitemap entries were found, so declared index intent could not be "
                "compared with the crawl."
            )

        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)

        # Search Console's impressions, when it is connected and has synced.
        gsc_urls: list[str] | None = None
        gsc_provenance = DataProvenance.UNKNOWN
        handle = context.tools.get("gsc")
        if handle is not None and handle.available:
            workspace.tools_used.add("gsc")
            demand = await context.service("integrations").query_demand(payload.brand_id)
            gsc_urls = sorted({page for row in demand for page in row["pages"]})
            if any(row["provenance"] == DataProvenance.SYNTHETIC_DEMO.value for row in demand):
                gsc_provenance = DataProvenance.SYNTHETIC_DEMO
                workspace.limitation(
                    "Search Console is running its development adapter, so the comparison "
                    "with earning URLs uses synthetic data."
                )
            elif demand:
                gsc_provenance = DataProvenance.OBSERVED
        else:
            workspace.note_unavailable_tool("gsc")

        report = reconcile(
            pages,
            sitemap_urls=sitemap_urls,
            priority_urls=facts.priority_urls,
            gsc_urls=gsc_urls,
        )
        if report.sitemap_unverified:
            workspace.limitation(
                f"{len(report.sitemap_unverified)} sitemap URL(s) were beyond the crawl's "
                "reach. Their state is unverified and no issue is claimed for them."
            )

        overview = workspace.observe(
            evidence_type=EvidenceType.CRAWL_RESULT,
            source="index_coverage_engine",
            reference=str(crawl.id),
            observation=(
                f"Reconciled {report.pages_observed} crawled URL(s) with {report.sitemap_urls} "
                f"sitemap entr(y/ies) and {len(facts.priority_urls)} priority landing page(s): "
                f"{len(report.issues)} disagreement(s)."
            ),
            data={"states": report.states, "issues": report.by_issue()},
        )

        seeds = []
        for issue in report.issues[: payload.max_findings]:
            earning = issue.issue == "earning_url_not_indexable"
            evidence = workspace.observe(
                evidence_type=EvidenceType.GSC if earning else EvidenceType.CRAWL_RESULT,
                source="index_coverage_engine",
                reference=issue.url,
                observation=issue.detail,
                data=issue.as_dict(),
                provenance=gsc_provenance if earning else DataProvenance.OBSERVED,
            )
            workspace.find(
                key=f"indexability.{issue.issue}",
                title=f"{issue.issue.replace('_', ' ').capitalize()}: {issue.url}",
                detail=issue.detail,
                severity=issue.severity,
                data=issue.as_dict(),
                evidence=[evidence],
            )
            if issue.severity in {"critical", "high", "medium"}:
                seeds.append(
                    seed(
                        opportunity_type=OpportunityType.INDEXABILITY,
                        title=f"Resolve {issue.issue.replace('_', ' ')} on {issue.url}",
                        description=issue.detail,
                        business_impact=IMPACT_BY_SEVERITY[issue.severity]
                        + (0.5 if issue.priority_label else 0.0),
                        seo_impact=IMPACT_BY_SEVERITY[issue.severity],
                        effort=2.0,
                        confidence=0.85 if not earning else 0.7,
                        evidence_refs=[evidence.id, overview.id],
                        target_url=issue.url,
                        risk=RiskLevel.MEDIUM,
                        source_agent=self.manifest.id,
                        data={"state": issue.state, "priority_label": issue.priority_label},
                    )
                )

        output = IndexabilityOutput(
            brand_id=str(payload.brand_id),
            pages_observed=report.pages_observed,
            sitemap_urls=report.sitemap_urls,
            sitemap_unverified=len(report.sitemap_unverified),
            states=report.states,
            issues_by_type=report.by_issue(),
            gsc_compared=report.gsc_compared,
            issues=[i.as_dict() for i in report.issues[:200]],
        )
        workspace.outputs["indexability"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["index_coverage_issues"] = float(len(report.issues))
        critical = sum(1 for i in report.issues if i.severity == "critical")

        return (
            f"Reconciled index coverage across {report.pages_observed} crawled URL(s) and "
            f"{report.sitemap_urls} sitemap entr(y/ies): {len(report.issues)} disagreement(s)"
            + (f", {critical} of them on a priority landing page" if critical else "")
            + "."
        )


AGENT = IndexabilityAgent
