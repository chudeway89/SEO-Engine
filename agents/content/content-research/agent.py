"""CNT-002 — Content Research Agent.

Builds a research pack for each scheduled topic from evidence the platform
already holds — and only from that:

* **questions** — stored audience questions (Search Console, people-also-ask,
  the brand's own audience vocabulary) that share the topic's terms;
* **entities** — the services and cluster keywords the topic belongs to;
* **SERP treatment** — features and recurring domains on the topic's observed
  results page, carrying the page's provenance;
* **sources** — registered sources whose title or stated claim bears on the
  topic, with tier and whether the platform verified them by fetching.

The pack is stored for the brief writer. Nothing in it is generated; a topic
with thin research produces a thin pack and says so.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import cluster_for_topic, load_brand_facts
from seo_engine.engines.keywords.pipeline import content_tokens, normalise
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
ContentResearchInput = _schemas.ContentResearchInput
ContentResearchOutput = _schemas.ContentResearchOutput


def _relevant(topic_tokens: set[str], text: str, threshold: float = 0.5) -> bool:
    if not topic_tokens:
        return False
    return len(topic_tokens & content_tokens(text)) / len(topic_tokens) >= threshold


class ContentResearchAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentResearchInput.model_validate(context.inputs)
        topics = [t for t in payload.topics if t.get("topic")][: payload.max_topics]
        if not topics:
            workspace.limitation(
                "No topics were supplied to research. The content strategist schedules "
                "topics; it must run first."
            )
            return "No topics were supplied, so no research pack was built."

        search = context.service("search")
        content = context.service("content")
        facts = await load_brand_facts(context, payload.brand_id)
        stored_questions = await search.list_questions(payload.brand_id, limit=500)
        snapshots = {normalise(s.query): s for s in await search.latest_snapshots(payload.brand_id)}
        sources = [content.source_contract(r) for r in await content.list_sources(payload.brand_id)]

        packs: list[dict[str, Any]] = []
        for item in topics:
            topic = str(item["topic"])
            tokens = content_tokens(topic)
            cluster, keywords = await cluster_for_topic(
                context, payload.brand_id, topic=topic, cluster_id=item.get("cluster_id")
            )

            questions = [
                {"question": q.question, "source": q.source, "provenance": q.provenance}
                for q in stored_questions
                if _relevant(tokens, q.question, 0.34)
            ][:15]
            entities = sorted(
                {
                    name
                    for name, terms, _ in facts.services
                    if _relevant(tokens, " ".join([name, *terms]), 0.34)
                }
                | {k.keyword for k in keywords[:10]}
            )
            snapshot = snapshots.get(normalise(topic)) or (
                snapshots.get(normalise(cluster.head_keyword)) if cluster else None
            )
            serp: dict[str, Any] = {}
            if snapshot is not None and snapshot.available:
                serp = {
                    "query": snapshot.query,
                    "features": snapshot.features,
                    "domains": [r.domain for r in snapshot.results if r.result_type == "organic"][
                        :8
                    ],
                    "provenance": snapshot.provenance.value,
                }
            topic_sources = [
                s
                for s in sources
                if _relevant(tokens, s.title, 0.34)
                or (s.supports_claim and _relevant(tokens, s.supports_claim, 0.34))
            ]
            findings = [
                {"type": "question", "text": q["question"], "provenance": q["provenance"]}
                for q in questions
            ] + [
                {
                    "type": "source",
                    "url": s.url,
                    "tier": s.tier.value,
                    "verified": s.verified,
                }
                for s in topic_sources
            ]
            record = await content.save_research(
                payload.brand_id,
                topic=topic,
                questions=[q["question"] for q in questions],
                entities=entities,
                findings=findings,
                competitor_coverage=serp,
                created_by_agent=self.manifest.id,
            )

            gaps_in_pack = []
            if not questions:
                gaps_in_pack.append("no audience question bears on this topic")
            if not any(s.verified for s in topic_sources):
                gaps_in_pack.append("no verified source supports it")
            if not serp:
                gaps_in_pack.append("no results page was observed for it")
            evidence = workspace.observe(
                evidence_type=EvidenceType.OBSERVATION,
                source="content_research",
                reference=f"research:{record.id}",
                observation=(
                    f"Research pack for '{topic}': {len(questions)} question(s), "
                    f"{len(entities)} entit(y/ies), {len(topic_sources)} source(s) "
                    f"({sum(1 for s in topic_sources if s.verified)} verified)"
                    + (f"; gaps: {', '.join(gaps_in_pack)}" if gaps_in_pack else "")
                    + "."
                ),
                data={"research_id": str(record.id), "serp": serp},
                provenance=(
                    DataProvenance.SYNTHETIC_DEMO
                    if serp.get("provenance") == DataProvenance.SYNTHETIC_DEMO.value
                    and not questions
                    else DataProvenance.OBSERVED
                ),
            )
            if gaps_in_pack:
                workspace.find(
                    key="content_research.thin_pack",
                    title=f"Research for '{topic}' is thin",
                    detail="The pack has " + "; ".join(gaps_in_pack) + ".",
                    severity="medium"
                    if "no verified source supports it" in gaps_in_pack
                    else "low",
                    evidence=[evidence],
                )
            packs.append(
                {
                    "topic": topic,
                    "research_id": str(record.id),
                    "decision": item.get("decision", "create"),
                    "target_url": item.get("target_url"),
                    "cluster_id": cluster.id if cluster else item.get("cluster_id"),
                    "questions": [q["question"] for q in questions],
                    "entities": entities,
                    "source_urls": [s.url for s in topic_sources],
                    "evidence_ids": [*item.get("evidence_ids", []), evidence.id],
                    "gaps": gaps_in_pack,
                }
            )

        output = ContentResearchOutput(
            brand_id=str(payload.brand_id), researched=len(packs), packs=packs
        )
        workspace.outputs["content_research"] = output.model_dump(mode="json")
        workspace.metrics["research_packs"] = float(len(packs))

        thin = sum(1 for p in packs if p["gaps"])
        return (
            f"Built {len(packs)} research pack(s) from stored questions, cluster keywords, SERP "
            f"observations and registered sources; {thin} are thin and say what is missing."
        )


AGENT = ContentResearchAgent
