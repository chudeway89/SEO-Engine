"""RES-005 — Question Research Agent.

Collects the questions an audience asks from three sources that each mean
something different — what people asked *and the site appeared for* (Search
Console), what the search engine associates with a query (people-also-ask, from
SERP research), and what the customer wrote into an audience's vocabulary — and
maps each to the page that already answers it.

A question merged from several sources keeps all of them and the weakest
provenance among them, so a question seen only on a synthetic results page is
never presented as an observed one. An unanswered question is a coverage
signal, not a decision to publish: the content gap stage decides that.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, load_page_facts
from seo_engine.engines.keywords.intent import is_question
from seo_engine.engines.opportunities.detection import seed
from seo_engine.engines.research.questions import gather_questions, map_to_pages
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, OpportunityType, SynthesisMode

_schemas = load_agent_module(__file__)
QuestionResearchInput = _schemas.QuestionResearchInput
QuestionResearchOutput = _schemas.QuestionResearchOutput

#: An unanswered question becomes an opportunity seed only when the demand
#: behind it was measured or it came from more than one independent source.
SEED_MIN_SOURCES = 2


class QuestionResearchAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = QuestionResearchInput.model_validate(context.inputs)
        search = context.service("search")
        facts = await load_brand_facts(context, payload.brand_id)
        sources_used: list[str] = []

        gsc_rows: list[dict[str, object]] = []
        handle = context.tools.get("gsc")
        if handle is not None and handle.available:
            workspace.tools_used.add("gsc")
            demand = await context.service("integrations").query_demand(payload.brand_id)
            gsc_rows = [row for row in demand if is_question(str(row["query"]))]
            if gsc_rows:
                sources_used.append("search_console")
        else:
            workspace.note_unavailable_tool("gsc")

        stored = await search.list_questions(payload.brand_id, limit=500)
        serp_questions = [
            (row.question, DataProvenance(row.provenance))
            for row in stored
            if "people_also_ask" in (row.source or "")
        ]
        if serp_questions:
            sources_used.append("serp_people_also_ask")
        else:
            workspace.limitation(
                "No people-also-ask questions are recorded; SERP research has not run or "
                "observed none."
            )
        if facts.audience_questions:
            sources_used.append("brand_audience_vocabulary")

        questions = gather_questions(
            gsc_queries=gsc_rows,
            serp_questions=serp_questions,
            audience_questions=facts.audience_questions,
        )[: payload.max_questions]
        if not questions:
            workspace.limitation("No question was found in any available source.")
            return "No audience questions were found in any available source."

        pages = await load_page_facts(context, payload.website_id)
        if not pages:
            workspace.limitation(
                "No crawled pages are available, so no question could be matched to an "
                "answering page; every question is reported unanswered provisionally."
            )
        map_to_pages(questions, pages)
        stored_count = await search.store_questions(
            payload.brand_id, [q.contract() for q in questions]
        )

        answered = [q for q in questions if q.answered_by_url]
        unanswered = [q for q in questions if not q.answered_by_url]
        if all(q.provenance is DataProvenance.SYNTHETIC_DEMO for q in questions):
            provenance = DataProvenance.SYNTHETIC_DEMO
        elif any(q.provenance is DataProvenance.OBSERVED for q in questions):
            provenance = DataProvenance.OBSERVED
        else:
            provenance = DataProvenance.USER_PROVIDED
        evidence = workspace.observe(
            evidence_type=EvidenceType.OBSERVATION,
            source="question_research",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"{len(questions)} audience question(s) from {', '.join(sources_used)}: "
                f"{len(answered)} answered by an existing page, {len(unanswered)} not."
            ),
            data={"questions": [q.as_dict() for q in questions[:50]]},
            provenance=provenance,
        )
        if unanswered:
            workspace.find(
                key="questions.unanswered",
                title=f"{len(unanswered)} audience question(s) have no answering page",
                detail="; ".join(q.question for q in unanswered[:6]),
                severity="medium",
                data={"unanswered": [q.as_dict() for q in unanswered[:25]]},
                evidence=[evidence],
            )

        seeds = []
        for question in unanswered:
            measured = "search_console" in question.sources and question.impressions > 0
            if not measured and len(question.sources) < SEED_MIN_SOURCES:
                continue
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.CONTENT_CREATE,
                    title=f"Answer: {question.question}",
                    description=(
                        f"Asked via {', '.join(question.sources)} and answered by no crawled page."
                    ),
                    business_impact=5.0,
                    seo_impact=6.0 if measured else 4.5,
                    effort=4.0,
                    confidence=0.65 if measured else 0.5,
                    evidence_refs=[evidence.id],
                    source_agent=self.manifest.id,
                    data={"question": question.question, "provenance": question.provenance.value},
                )
            )

        output = QuestionResearchOutput(
            brand_id=str(payload.brand_id),
            questions_total=len(questions),
            answered=len(answered),
            unanswered=len(unanswered),
            sources_used=sources_used,
            questions=[q.as_dict() for q in questions],
        )
        workspace.outputs["question_research"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["questions_unanswered"] = float(len(unanswered))

        return (
            f"Gathered {len(questions)} audience question(s) from {len(sources_used)} source(s); "
            f"{len(answered)} are answered by an existing page and {len(unanswered)} are not. "
            f"{stored_count} new question(s) stored."
        )


AGENT = QuestionResearchAgent
