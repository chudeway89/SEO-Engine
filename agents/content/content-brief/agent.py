"""CNT-003 — Content Brief Agent.

The brief is the contract the writer is held to and the evaluator scores
against. This agent assembles it with ``build_brief`` from the topic's research
pack, its keyword cluster, the brand profile, the brand's approved and
prohibited claims, the crawled pages it should link to, and the registered
sources — of which only verified ones are offered for citation; unverified ones
become "claims requiring verification".

A topic whose keyword cluster cannot be found is skipped with the reason: a
brief without its cluster would have no keywords to target, and inventing them
is exactly what the platform does not do.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import cluster_for_topic, load_brand_facts
from seo_engine.engines.content.brief import build_brief
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import ContentDecision, DataProvenance, SynthesisMode
from seo_engine.schemas.search import ContentGap

_schemas = load_agent_module(__file__)
ContentBriefInput = _schemas.ContentBriefInput
ContentBriefOutput = _schemas.ContentBriefOutput

BRIEFABLE = frozenset({ContentDecision.CREATE, ContentDecision.UPDATE})


class ContentBriefAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentBriefInput.model_validate(context.inputs)
        packs = payload.research[: payload.max_briefs]
        if not packs:
            workspace.limitation(
                "No research packs were supplied. Content research builds them from the "
                "scheduled topics; it must run first."
            )
            return "No research packs were supplied, so no brief was written."

        content = context.service("content")
        facts = await load_brand_facts(context, payload.brand_id)
        sources = [content.source_contract(r) for r in await content.list_sources(payload.brand_id)]
        existing_pages: dict[str, dict[str, Any]] = {}
        if payload.website_id is not None:
            for page in await context.service("websites").list_pages(payload.website_id, limit=500):
                if page.indexability == "indexable":
                    existing_pages[page.url] = {"title": page.title or "", "h1": page.h1 or ""}

        briefs: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for pack in packs:
            topic = str(pack.get("topic") or "")
            decision = ContentDecision(pack.get("decision") or ContentDecision.CREATE)
            if decision not in BRIEFABLE:
                skipped.append(
                    {"topic": topic, "reason": f"a {decision.value} decision needs no new brief"}
                )
                continue
            cluster, keywords = await cluster_for_topic(
                context, payload.brand_id, topic=topic, cluster_id=pack.get("cluster_id")
            )
            if cluster is None:
                skipped.append({"topic": topic, "reason": "no keyword cluster matches the topic"})
                workspace.limitation(
                    f"No keyword cluster matches '{topic}', so no brief was written for it."
                )
                continue

            pack_sources = set(pack.get("source_urls") or [])
            gap = ContentGap(
                topic=topic,
                cluster_id=cluster.id,
                intent=cluster.intent,
                decision=decision,
                target_url=pack.get("target_url"),
                decision_reason=f"Scheduled by the content roadmap as {decision.value}.",
                evidence_ids=list(pack.get("evidence_ids") or []),
                demand_provenance=DataProvenance.INFERRED,
            )
            brief = build_brief(
                gap=gap,
                cluster=cluster,
                keywords=keywords,
                brand_profile=facts.brief_profile(),
                approved_claims=[claim for claim, _ in facts.approved_claims],
                prohibited_claims=list(facts.prohibited_claims),
                existing_pages=existing_pages,
                sources=[s for s in sources if s.url in pack_sources],
                questions=list(pack.get("questions") or []),
            )
            record = await content.save_brief(
                payload.brand_id, brief, created_by_agent=self.manifest.id
            )
            evidence = workspace.infer(
                source="content_brief_engine",
                conclusion=(
                    f"Brief '{brief.title}' targets '{brief.primary_keyword}' with "
                    f"{len(brief.secondary_keywords)} secondary keyword(s), "
                    f"{len(brief.required_sections)} section(s), "
                    f"{len(brief.questions_to_answer)} question(s), "
                    f"{len(brief.authoritative_sources)} verified source(s) and "
                    f"{len(brief.prohibited_claims)} prohibition(s)."
                ),
                data={"brief_id": str(record.id), "risk_category": brief.risk_category.value},
                confidence=0.85,
                derived_from=list(pack.get("evidence_ids") or []),
            )
            if not brief.authoritative_sources:
                workspace.find(
                    key="content_brief.no_verified_sources",
                    title=f"'{brief.title}' has no verified source to cite",
                    detail=(
                        "The writer has no fetched source to rely on; any factual claim "
                        "beyond the approved claims must be verified before review."
                    ),
                    severity="medium",
                    evidence=[evidence],
                )
            briefs.append(
                {
                    "brief_id": str(record.id),
                    "title": brief.title,
                    "topic": topic,
                    "primary_keyword": brief.primary_keyword,
                    "risk_category": brief.risk_category.value,
                    "evidence_ids": [*gap.evidence_ids, evidence.id],
                }
            )

        output = ContentBriefOutput(
            brand_id=str(payload.brand_id),
            briefs_written=len(briefs),
            skipped=skipped,
            briefs=briefs,
        )
        workspace.outputs["content_briefs"] = output.model_dump(mode="json")
        workspace.metrics["briefs_written"] = float(len(briefs))

        return (
            f"Wrote {len(briefs)} brief(s)"
            + (f"; skipped {len(skipped)} with stated reasons" if skipped else "")
            + ". Each carries the brand's approved and prohibited claims."
        )


AGENT = ContentBriefAgent
