"""OPP-001 — Opportunity Detection Agent.

Reads the findings of every upstream stage and turns them into opportunities,
each carrying the evidence that produced it. An opportunity with no supporting
observation is not created — which means a mission where nothing could be
observed produces no opportunities, and says so.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.engines.opportunities.detection import (
    from_content_gaps,
    from_keyword_positions,
    from_technical_issues,
)
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, IssueSeverity, SynthesisMode
from seo_engine.schemas.search import ContentGap, KeywordMetric, KeywordRecord
from seo_engine.schemas.seo import SEOIssue


class OpportunityDetectionInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    mission_id: UUID | None = None


class OpportunityDetectionOutput(BaseModel):
    brand_id: str
    opportunities_detected: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)


class OpportunityDetectionAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = OpportunityDetectionInput.model_validate(context.inputs)
        upstream = context.inputs.get("upstream") or {}
        detected: list[Any] = []
        by_source: dict[str, int] = {}

        # --- from the technical audit -----------------------------------------
        websites = context.services.get("websites")
        commercial_urls: set[str] = set()
        issues: list[SEOIssue] = []
        pages_total = 1
        if websites is not None and payload.website_id is not None:
            rows = await websites.list_issues(payload.website_id, limit=500)
            pages_total = max(await websites.count_pages(payload.website_id), 1)
            issues = [
                SEOIssue(
                    check_id=row.check_id,
                    title=row.title,
                    severity=IssueSeverity(row.severity),
                    dimension=row.dimension,
                    url=row.url,
                    detail=row.detail,
                    recommendation=row.recommendation,
                    evidence_data=row.evidence_data,
                    affected_urls=row.affected_urls,
                )
                for row in rows
            ]
            for page in await websites.list_pages(payload.website_id, limit=300):
                if any(
                    token in (page.path or "").lower()
                    for token in ("service", "product", "pricing", "contact", "book")
                ):
                    commercial_urls.add(page.url)

        if issues:
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="technical_audit",
                reference=str(payload.website_id),
                observation=(
                    f"{len(issues)} open technical finding(s) across {pages_total} "
                    "crawled page(s) were carried into opportunity detection."
                ),
                data={"issues": len(issues), "pages": pages_total},
            )
            technical = from_technical_issues(
                issues,
                pages_total=pages_total,
                commercial_urls=commercial_urls,
                evidence_by_check={i.check_id: evidence.id for i in issues},
            )
            detected.extend(technical)
            by_source["technical_audit"] = len(technical)

        # --- from content gaps -------------------------------------------------
        gaps_raw = upstream.get("content_gaps") or []
        if gaps_raw:
            gaps = [ContentGap.model_validate(g) for g in gaps_raw]
            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_gap_engine",
                reference=f"brand:{payload.brand_id}",
                observation=(
                    f"{len(gaps)} topic decision(s) were carried into opportunity "
                    "detection; only actionable ones become opportunities."
                ),
                data={"decisions": [g.decision.value for g in gaps]},
            )
            content = from_content_gaps(
                gaps, evidence_by_topic={g.topic: evidence.id for g in gaps}
            )
            detected.extend(content)
            by_source["content_gaps"] = len(content)

        # --- from observed positions -------------------------------------------
        observed = upstream.get("observed_queries") or []
        if observed:
            evidence = workspace.observe(
                evidence_type=EvidenceType.GSC,
                source="google_search_console",
                reference=f"brand:{payload.brand_id}",
                observation=(
                    f"{len(observed)} quer(y/ies) with measured impressions and "
                    "positions were carried into opportunity detection."
                ),
                data={"queries": len(observed)},
                provenance=DataProvenance.OBSERVED,
            )
            records = [
                KeywordRecord(
                    keyword=item["query"],
                    normalised=item["query"],
                    metrics=[
                        KeywordMetric(
                            name="position",
                            value=float(item["position"]),
                            provenance=DataProvenance.OBSERVED,
                        ),
                        KeywordMetric(
                            name="impressions",
                            value=float(item["impressions"]),
                            provenance=DataProvenance.OBSERVED,
                        ),
                    ],
                )
                for item in observed
            ]
            positional = from_keyword_positions(records, evidence_ref=evidence.id)
            detected.extend(positional)
            by_source["search_console"] = len(positional)

        if not detected:
            workspace.limitation(
                "No opportunity could be detected because no upstream stage produced an "
                "observation. This is a result, not an error: nothing observable "
                "justifies work right now."
            )
            return (
                "No opportunities were detected. No upstream stage produced an "
                "observation that would justify one, and none has been invented."
            )

        # --- persist -----------------------------------------------------------
        decisions = context.service("decisions")
        stored = await decisions.record_opportunities(
            payload.brand_id,
            detected,
            website_id=payload.website_id,
            mission_id=payload.mission_id,
            agent_id=self.manifest.id,
        )

        by_type: dict[str, int] = {}
        for item in detected:
            key = item.opportunity_type.value
            by_type[key] = by_type.get(key, 0) + 1

        for opportunity in sorted(detected, key=lambda o: -o.priority_score)[:8]:
            workspace.find(
                key=f"opportunity.{opportunity.opportunity_type.value}",
                title=opportunity.title,
                detail=opportunity.description,
                severity="medium",
                data={
                    "priority_score": opportunity.priority_score,
                    "business_impact": opportunity.business_impact,
                    "effort": opportunity.effort,
                },
                evidence=[e for e in workspace.evidence if e.id in opportunity.evidence_refs],
            )

        output = OpportunityDetectionOutput(
            brand_id=str(payload.brand_id),
            opportunities_detected=len(stored),
            by_type=by_type,
            by_source=by_source,
            opportunities=[
                {
                    "id": str(row.id),
                    "type": row.opportunity_type,
                    "title": row.title,
                    "priority_score": row.priority_score,
                    "evidence_refs": row.evidence_refs,
                }
                for row in stored
            ],
        )
        workspace.outputs["opportunity_detection"] = output.model_dump(mode="json")
        workspace.metrics["opportunities"] = float(len(stored))

        return (
            f"Detected {len(stored)} opportunit(y/ies) from "
            + ", ".join(
                f"{count} via {source.replace('_', ' ')}" for source, count in by_source.items()
            )
            + ". Each one cites the observation that produced it."
        )


AGENT = OpportunityDetectionAgent
