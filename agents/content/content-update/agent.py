"""CNT-006 — Content Update Agent.

For every topic the content gap stage decided to UPDATE, this agent builds the
brief the page should meet and diffs the live page against it
(``build_update_plan``): missing and weak sections, unanswered questions,
unsupported claims, internal links and metadata changes.

Updating a live page is a consequential change, so the plan is proposed as a
``content.update`` recommendation. In a regulated category it is high risk and
the result requires approval; in any category nothing changes on the site until
a person approves the action the decision chain creates from it.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import (
    cluster_for_topic,
    crawl_page_from_row,
    load_brand_facts,
)
from seo_engine.engines.content.brief import build_brief
from seo_engine.engines.content.generation import build_update_plan
from seo_engine.engines.seo.pages import key
from seo_engine.schemas.agent import AgentContext, ProposedRecommendation
from seo_engine.schemas.enums import (
    HIGH_RISK_CATEGORIES,
    ActionType,
    ContentDecision,
    DataProvenance,
    EvidenceType,
    RiskLevel,
    SynthesisMode,
)
from seo_engine.schemas.search import ContentGap

_schemas = load_agent_module(__file__)
ContentUpdateInput = _schemas.ContentUpdateInput
ContentUpdateOutput = _schemas.ContentUpdateOutput


class ContentUpdateAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentUpdateInput.model_validate(context.inputs)
        updates = [
            ContentGap.model_validate(g)
            for g in payload.content_gaps
            if g.get("decision") == ContentDecision.UPDATE.value and g.get("target_url")
        ][: payload.max_pages]
        if not updates:
            workspace.limitation(
                "No content gap decision called for an update to an existing page, so "
                "there is nothing to plan."
            )
            return "No page was marked for update, so no update plan was produced."
        if payload.website_id is None:
            workspace.limitation("No website was supplied, so the live pages cannot be read.")
            return "No update plan was possible without the website's crawled pages."

        rows = {
            key(row.url): row
            for row in await context.service("websites").list_pages(payload.website_id, limit=1000)
        }
        facts = await load_brand_facts(context, payload.brand_id)
        regulated = facts.risk_category in HIGH_RISK_CATEGORIES
        content = context.service("content")
        inherited = {e.id for e in context.evidence}

        plans: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for gap in updates:
            row = rows.get(key(gap.target_url or ""))
            if row is None:
                skipped.append({"topic": gap.topic, "reason": "the target page was not crawled"})
                continue
            cluster, keywords = await cluster_for_topic(
                context, payload.brand_id, topic=gap.topic, cluster_id=gap.cluster_id
            )
            if cluster is None:
                skipped.append({"topic": gap.topic, "reason": "no keyword cluster matches"})
                continue
            brief = build_brief(
                gap=gap,
                cluster=cluster,
                keywords=keywords,
                brand_profile=facts.brief_profile(),
                approved_claims=[claim for claim, _ in facts.approved_claims],
                prohibited_claims=list(facts.prohibited_claims),
            )
            plan = build_update_plan(
                crawl_page_from_row(row), brief, evidence_ids=list(gap.evidence_ids)
            )
            brief_record = await content.save_brief(
                payload.brand_id, brief, created_by_agent=self.manifest.id
            )
            changes = (
                len(plan.sections_to_add)
                + len(plan.sections_to_rewrite)
                + len(plan.missing_information)
                + len(plan.unsupported_claims)
                + len(plan.internal_links_to_add)
                + len(plan.metadata_changes)
            )
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="content_update_engine",
                reference=row.url,
                observation=(
                    f"{row.url} against its brief: {len(plan.sections_to_add)} section(s) to "
                    f"add, {len(plan.missing_information)} unanswered question(s), "
                    f"{len(plan.unsupported_claims)} unsupported claim(s)."
                ),
                data=plan.model_dump(mode="json"),
                provenance=DataProvenance.OBSERVED,
            )
            if changes == 0:
                skipped.append({"topic": gap.topic, "reason": "the page already meets its brief"})
                continue

            risk = RiskLevel.HIGH if regulated else RiskLevel.MEDIUM
            workspace.recommend(
                ProposedRecommendation(
                    type="content_update",
                    title=f"Update {row.url} for '{gap.topic}'",
                    problem=plan.rationale or gap.decision_reason,
                    opportunity=(
                        "The page already exists for this topic; bringing it up to its brief "
                        "is cheaper and safer than a new page."
                    ),
                    reason=(
                        f"{changes} specific change(s) close the distance between the live "
                        "page and what its topic requires."
                    ),
                    business_impact=6.0,
                    seo_impact=6.5,
                    effort=4.0,
                    risk=risk,
                    confidence=0.7,
                    expected_outcome="The page covers its topic as fully as the brief requires.",
                    # Upstream gap evidence is cited only when this run can see it.
                    evidence_ids=[evidence.id, *[e for e in gap.evidence_ids if e in inherited]],
                    proposed_action={
                        "action_type": ActionType.CONTENT_UPDATE.value,
                        "target": {"url": row.url},
                        "attributes": {"category": facts.risk_category.value},
                    },
                    target_entity_type="page",
                    target_entity_id=str(row.id),
                )
            )
            workspace.find(
                key="content_update.plan",
                title=f"Update plan for {row.url}",
                detail=plan.rationale,
                severity="medium",
                data=plan.model_dump(mode="json"),
                evidence=[evidence],
            )
            plans.append(
                {
                    "url": row.url,
                    "topic": gap.topic,
                    "brief_id": str(brief_record.id),
                    "changes": changes,
                    "plan": plan.model_dump(mode="json"),
                }
            )

        for item in skipped:
            workspace.limitation(f"No update plan for '{item['topic']}': {item['reason']}.")

        output = ContentUpdateOutput(
            brand_id=str(payload.brand_id),
            pages_planned=len(plans),
            skipped=skipped,
            plans=plans,
        )
        workspace.outputs["content_update"] = output.model_dump(mode="json")
        workspace.metrics["update_plans"] = float(len(plans))

        return (
            f"Produced {len(plans)} update plan(s) for existing pages"
            + (f" and skipped {len(skipped)} with stated reasons" if skipped else "")
            + ". Each live-page change is a recommendation that requires approval."
        )


AGENT = ContentUpdateAgent
