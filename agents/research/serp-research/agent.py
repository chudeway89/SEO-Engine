"""RES-002 — SERP Research Agent.

Fetches the results page for each priority query through the SERP integration,
which stores the raw response and the normalised snapshot. The agent then
summarises what the pages show: the features present, the domains that recur,
the brand's own position, and where observed features shift a query's intent
away from its lexical reading.

With no SERP API key the integration runs its development adapter. The agent
runs identically, but every snapshot, every figure and every piece of evidence
is labelled synthetic, and the result says so as its first limitation.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import (
    SYNTHETIC_SERP_LIMITATION,
    load_brand_facts,
    website_domain,
)
from seo_engine.engines.keywords.intent import classify_intent
from seo_engine.engines.research.serp import summarise_serps
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode
from seo_engine.schemas.search import SearchQuestion
from seo_engine.shared.errors import IntegrationError

_schemas = load_agent_module(__file__)
SERPResearchInput = _schemas.SERPResearchInput
SERPResearchOutput = _schemas.SERPResearchOutput


class SERPResearchAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = SERPResearchInput.model_validate(context.inputs)
        if not workspace.note_unavailable_tool("serp"):
            return (
                "No results pages were observed: the SERP integration is not available, "
                "and no SERP data has been estimated in its place."
            )

        search = context.service("search")
        queries = [q.strip() for q in payload.queries if q and q.strip()]
        if not queries:
            queries = [
                k.keyword
                for k in await search.list_keywords(payload.brand_id, limit=200)
                if not k.is_branded
            ]
        queries = list(dict.fromkeys(queries))[: payload.max_queries]
        if not queries:
            workspace.limitation(
                "No queries were supplied and no keyword research exists, so there was "
                "nothing to look up."
            )
            return "No queries were available to research."

        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)
        integrations = context.service("integrations")

        snapshots = []
        failed: list[dict[str, str]] = []
        question_records: list[SearchQuestion] = []
        for query in queries:
            try:
                normalised = await integrations.serp_lookup(
                    payload.brand_id,
                    query,
                    country=payload.country,
                    device=payload.device,
                    brand_domain=facts.domain,
                )
            except IntegrationError as exc:
                failed.append({"query": query, "reason": exc.message})
                continue
            snapshot = normalised.snapshot
            snapshots.append(snapshot)
            brand_rank = next(
                (
                    r.position
                    for r in snapshot.results
                    if facts.domain and r.domain.removeprefix("www.") == facts.domain
                ),
                None,
            )
            workspace.observe(
                evidence_type=EvidenceType.SERP_RESULT,
                source=snapshot.provider,
                reference=query,
                observation=(
                    f"Results page for '{query}': {len(snapshot.results)} result(s), features "
                    f"{', '.join(snapshot.features) or 'none'}; the brand "
                    + (f"ranks at {brand_rank}." if brand_rank else "was not observed.")
                    if snapshot.available
                    else f"No results page was available for '{query}': {snapshot.unavailable_reason}"
                ),
                data={
                    "query": query,
                    "features": snapshot.features,
                    "domains": [r.domain for r in snapshot.results][:10],
                    "brand_position": brand_rank,
                },
                provenance=snapshot.provenance,
            )
            question_records += [
                SearchQuestion(
                    question=text,
                    source="serp_people_also_ask",
                    intent=classify_intent(text),
                    provenance=snapshot.provenance,
                )
                for text in normalised.questions
            ]

        for failure in failed:
            workspace.limitation(
                f"The results page for '{failure['query']}' could not be fetched "
                f"({failure['reason']}); nothing is assumed about it."
            )
        if not snapshots:
            return f"None of the {len(queries)} results page(s) could be fetched."

        landscape = summarise_serps(snapshots, brand_domain=facts.domain)
        if landscape.synthetic:
            workspace.limitation(SYNTHETIC_SERP_LIMITATION)
        provenance = (
            DataProvenance.SYNTHETIC_DEMO if landscape.synthetic else DataProvenance.OBSERVED
        )
        recorded = await search.store_questions(payload.brand_id, question_records)

        summary_evidence = workspace.observe(
            evidence_type=EvidenceType.SERP_RESULT,
            source="serp_landscape",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Across {landscape.queries_observed} results page(s) the brand appears on "
                f"{landscape.brand_visible_share:.0%}; the most frequent features are "
                + (", ".join(list(landscape.feature_frequency)[:4]) or "none")
                + "."
            ),
            data=landscape.as_dict(),
            provenance=provenance,
        )
        if landscape.recurring_domains:
            workspace.find(
                key="serp.recurring_domains",
                title=f"{len(landscape.recurring_domains)} domain(s) recur across the results",
                detail=(
                    "Recurring domains are candidates for search competitors. Competitor "
                    "discovery decides; nothing is added to the brand graph here."
                    + (" These domains are synthetic." if landscape.synthetic else "")
                ),
                data={"domains": landscape.recurring_domains},
                evidence=[summary_evidence],
            )
        if landscape.intent_shifts:
            workspace.find(
                key="serp.intent_shifts",
                title=f"Observed features shift the intent of {len(landscape.intent_shifts)} quer(y/ies)",
                detail="The results page reads the query differently from its wording.",
                data={"shifts": landscape.intent_shifts},
                evidence=[summary_evidence],
            )

        output = SERPResearchOutput(
            brand_id=str(payload.brand_id),
            queries_requested=queries,
            queries_failed=failed,
            questions_recorded=recorded,
            synthetic=landscape.synthetic,
            landscape=landscape.as_dict(),
        )
        workspace.outputs["serp_research"] = output.model_dump(mode="json")
        workspace.metrics["serp_pages_observed"] = float(landscape.queries_observed)

        return (
            f"Observed {landscape.queries_observed} results page(s); the brand appears on "
            f"{landscape.brand_visible_share:.0%} of them and {len(landscape.recurring_domains)} "
            f"domain(s) recur. {recorded} new question(s) recorded."
            + (" All SERP data is synthetic development data." if landscape.synthetic else "")
        )


AGENT = SERPResearchAgent
