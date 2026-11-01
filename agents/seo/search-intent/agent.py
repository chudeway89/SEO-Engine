"""SEO-004 — Search Intent Agent.

Ranking needs the right *kind* of page. This agent reads the intent the keyword
pipeline assigned to each mapped query, refines it with observed SERP features
where SERP data exists, classifies the mapped page's type from its structure,
and reports where the two do not fit.

The page-type classification names the signal that decided it (URL, title,
structured data), so a reviewer can disagree with a reason rather than a score.
A page whose type cannot be identified is not reported as a mismatch — absence
of a signal is not evidence of a problem.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import SYNTHETIC_SERP_LIMITATION, load_page_facts
from seo_engine.engines.keywords.intent import refine_with_serp
from seo_engine.engines.keywords.intent_fit import assess_fit
from seo_engine.engines.keywords.pipeline import normalise
from seo_engine.engines.opportunities.detection import seed
from seo_engine.engines.seo.pages import key
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import (
    DataProvenance,
    EvidenceType,
    OpportunityType,
    SearchIntent,
    SynthesisMode,
)
from seo_engine.schemas.search import IntentDistribution

_schemas = load_agent_module(__file__)
SearchIntentInput = _schemas.SearchIntentInput
SearchIntentOutput = _schemas.SearchIntentOutput

HIGH_VALUE_INTENTS = frozenset(
    {SearchIntent.TRANSACTIONAL, SearchIntent.COMMERCIAL, SearchIntent.LOCAL}
)


class SearchIntentAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = SearchIntentInput.model_validate(context.inputs)
        search = context.service("search")
        keywords = await search.list_keywords(payload.brand_id, limit=1000)

        # One query per mapped page: the highest-opportunity keyword mapped to it.
        chosen: dict[str, Any] = {}
        for keyword in keywords:
            if not keyword.mapped_url or keyword.is_branded:
                continue
            current = chosen.get(key(keyword.mapped_url))
            if current is None or keyword.opportunity_score > current.opportunity_score:
                chosen[key(keyword.mapped_url)] = keyword

        if not chosen:
            workspace.limitation(
                "No keyword is mapped to a page, so intent fit cannot be judged. Run "
                "keyword research first."
            )
            return "No mapped keywords were available, so no intent fit was assessed."

        pages = {
            key(p.url): p
            for p in await load_page_facts(context, payload.website_id, with_schema=True)
        }
        if not pages:
            workspace.limitation("No crawled pages are available to classify.")
            return "No crawled pages were available, so no intent fit was assessed."

        # Observed SERP features refine lexical intent — only when they exist.
        snapshots = {}
        serp_synthetic = False
        if context.tools.get("serp") is not None and context.tools["serp"].available:
            workspace.tools_used.add("serp")
            for snapshot in await search.latest_snapshots(payload.brand_id):
                snapshots[normalise(snapshot.query)] = snapshot
                serp_synthetic |= snapshot.provenance is DataProvenance.SYNTHETIC_DEMO
        else:
            workspace.limitation(
                "No SERP observations are available, so intent is the lexical "
                "classification of the query alone, unrefined by results-page features."
            )
        if serp_synthetic:
            workspace.limitation(SYNTHETIC_SERP_LIMITATION)

        assessments = []
        refined_count = 0
        page_types: dict[str, int] = {}
        for url_key, keyword in chosen.items():
            page = pages.get(url_key)
            if page is None:
                continue
            intent = IntentDistribution(**(keyword.intent or {}))
            snapshot = snapshots.get(normalise(keyword.keyword))
            if snapshot is not None:
                refined = refine_with_serp(intent, snapshot)
                if refined.as_dict() != intent.as_dict():
                    refined_count += 1
                intent = refined
            fit = assess_fit(page, keyword.keyword, intent)
            page_types[fit.page_type.value] = page_types.get(fit.page_type.value, 0) + 1
            assessments.append((fit, snapshot is not None))

        mismatches = [(fit, refined) for fit, refined in assessments if not fit.fits]
        seeds = []
        for fit, used_serp in sorted(mismatches, key=lambda pair: -pair[0].intent_confidence)[
            : payload.max_findings
        ]:
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="intent_fit_engine",
                reference=fit.url,
                observation=fit.detail,
                data=fit.as_dict() | {"serp_refined": used_serp},
                # A fit refined by synthetic SERP features inherits that label.
                provenance=(
                    DataProvenance.SYNTHETIC_DEMO
                    if used_serp and serp_synthetic
                    else DataProvenance.OBSERVED
                ),
            )
            workspace.find(
                key="search_intent.mismatch",
                title=(
                    f"'{fit.keyword}' ({fit.primary_intent.value}) is answered by a "
                    f"{fit.page_type.value} page"
                ),
                detail=fit.detail,
                severity="medium" if fit.primary_intent in HIGH_VALUE_INTENTS else "low",
                data=fit.as_dict(),
                evidence=[evidence],
            )
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.CONTENT_UPDATE,
                    title=(
                        f"Serve '{fit.keyword}' with a "
                        f"{fit.recommended_page_type.value if fit.recommended_page_type else ''} page"
                    ),
                    description=fit.detail,
                    business_impact=7.5 if fit.primary_intent in HIGH_VALUE_INTENTS else 4.5,
                    seo_impact=6.0,
                    effort=6.0,
                    confidence=round(min(0.8, 0.4 + 0.4 * fit.intent_confidence), 3),
                    evidence_refs=[evidence.id],
                    target_url=fit.url,
                    source_agent=self.manifest.id,
                    data={
                        "current_page_type": fit.page_type.value,
                        "recommended_page_type": (
                            fit.recommended_page_type.value if fit.recommended_page_type else None
                        ),
                    },
                )
            )

        if assessments:
            workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="intent_fit_engine",
                reference=str(payload.website_id),
                observation=(
                    f"Compared query intent with page type for {len(assessments)} mapped "
                    f"page(s); {len(mismatches)} do not fit."
                ),
                data={"assessed": len(assessments), "mismatches": len(mismatches)},
            )

        output = SearchIntentOutput(
            brand_id=str(payload.brand_id),
            pairs_assessed=len(assessments),
            mismatches=len(mismatches),
            serp_refined=refined_count,
            serp_synthetic=serp_synthetic,
            page_types=page_types,
            assessments=[fit.as_dict() for fit, _ in assessments][:100],
        )
        workspace.outputs["search_intent"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["intent_mismatches"] = float(len(mismatches))

        return (
            f"Compared query intent with page type on {len(assessments)} mapped page(s): "
            f"{len(mismatches)} mismatch(es)."
            + (
                f" {refined_count} intent(s) were refined by observed SERP features."
                if refined_count
                else ""
            )
            + (" SERP data was synthetic." if serp_synthetic else "")
        )


AGENT = SearchIntentAgent
