"""AI Search and agentic-web readiness.

The governing constraint (Architecture Pack P13, Build Specification §60) is
that AI Search is **not** a separate ranking system to be hacked. Google's own
guidance states there are no special optimisation requirements for AI surfaces
beyond foundational SEO. So this module does not invent an "AI ranking score".

It reports three strictly separated classes of signal:

* **OBSERVED** — measured from the crawl or a connected provider;
* **INFERRED** — concluded from observations, and labelled as a conclusion;
* **UNKNOWN** — depends on proprietary internals we cannot see, and is never
  guessed at.

The readiness score is computed from observed and inferred signals only.
Unknowns are listed separately so a user can see exactly what the system
*cannot* tell them.
"""

from __future__ import annotations

from statistics import mean

from seo_engine.schemas.crawl import CrawlResult
from seo_engine.schemas.enums import (
    IssueSeverity,
    ObservationConfidenceClass,
    SEODimension,
)
from seo_engine.schemas.seo import (
    AgenticWebReadinessReport,
    AISearchReadinessReport,
    AISearchSignal,
    SEOIssue,
)

#: Things no third party can measure, whatever they claim.  Listed explicitly so
#: the UI can show the user what is genuinely unknowable rather than implying
#: the absence of data is a low score.
UNKNOWNS: tuple[str, ...] = (
    "Google's internal AI Overview and AI Mode ranking signals",
    "Whether a specific page is currently used as a source in an AI answer, "
    "unless a citation is directly observed",
    "How a generative surface weights any individual page attribute",
)


def assess_ai_search_readiness(
    result: CrawlResult,
    *,
    website_id: str,
    observed_citations: list[dict] | None = None,
    gsc_connected: bool = False,
) -> AISearchReadinessReport:
    """Assess the conditions that make content usable as a source.

    These are the same foundations that matter for Search: the content is
    reachable without executing JavaScript, it is structured, it states what it
    is about, and it is attributable.
    """
    pages = [p for p in result.pages if not p.error and p.is_indexable]
    signals: list[AISearchSignal] = []

    if not pages:
        return AISearchReadinessReport(
            website_id=website_id,
            signals=[],
            readiness_score=None,
            unknowns=list(UNKNOWNS),
            notes=["No indexable pages were crawled, so readiness could not be assessed."],
        )

    total = len(pages)

    # --- OBSERVED -------------------------------------------------------
    server_rendered = sum(1 for p in pages if not p.accessibility.rendered_by_javascript)
    signals.append(
        AISearchSignal(
            key="server_rendered_content",
            label="Pages whose primary content is in the initial HTML",
            classification=ObservationConfidenceClass.OBSERVED,
            value=_ratio(server_rendered, total),
            detail=(
                f"{server_rendered} of {total} indexable pages carry their content in "
                "the HTML response. Systems that do not execute JavaScript can only "
                "read those."
            ),
            source="crawler",
        )
    )

    with_schema = sum(1 for p in pages if p.schema_blocks)
    signals.append(
        AISearchSignal(
            key="structured_data_coverage",
            label="Pages carrying structured data",
            classification=ObservationConfidenceClass.OBSERVED,
            value=_ratio(with_schema, total),
            detail=f"{with_schema} of {total} indexable pages include JSON-LD or microdata.",
            source="crawler",
        )
    )

    with_headings = sum(1 for p in pages if p.h1s and p.accessibility.heading_order_valid)
    signals.append(
        AISearchSignal(
            key="document_structure",
            label="Pages with a valid heading outline",
            classification=ObservationConfidenceClass.OBSERVED,
            value=_ratio(with_headings, total),
            detail=(
                f"{with_headings} of {total} pages have a single clear H1 and a "
                "sequential heading structure that can be segmented reliably."
            ),
            source="crawler",
        )
    )

    with_language = sum(1 for p in pages if p.lang)
    signals.append(
        AISearchSignal(
            key="language_declared",
            label="Pages declaring their language",
            classification=ObservationConfidenceClass.OBSERVED,
            value=_ratio(with_language, total),
            detail=f"{with_language} of {total} pages set an html lang attribute.",
            source="crawler",
        )
    )

    substantive = sum(1 for p in pages if p.word_count >= 300)
    signals.append(
        AISearchSignal(
            key="substantive_content",
            label="Pages with substantive body content",
            classification=ObservationConfidenceClass.OBSERVED,
            value=_ratio(substantive, total),
            detail=f"{substantive} of {total} pages have 300+ words of extractable text.",
            source="crawler",
        )
    )

    citations = observed_citations or []
    signals.append(
        AISearchSignal(
            key="observed_citations",
            label="Directly observed AI-surface citations",
            classification=ObservationConfidenceClass.OBSERVED,
            value=len(citations),
            detail=(
                f"{len(citations)} citation(s) have been directly observed."
                if citations
                else (
                    "No citations have been observed. This means none were measured — "
                    "it is not evidence that none exist."
                )
            ),
            source="ai_search_monitor",
        )
    )

    # --- INFERRED -------------------------------------------------------
    extractable = mean(
        [
            _ratio(server_rendered, total),
            _ratio(with_headings, total),
            _ratio(substantive, total),
        ]
    )
    signals.append(
        AISearchSignal(
            key="extraction_suitability",
            label="Suitability of the content for extraction and citation",
            classification=ObservationConfidenceClass.INFERRED,
            value=round(extractable, 3),
            detail=(
                "Concluded from server-rendering, heading structure and content depth. "
                "It describes how readable the site is to an automated reader, not "
                "whether any system will actually cite it."
            ),
            source="inference",
        )
    )

    signals.append(
        AISearchSignal(
            key="entity_clarity",
            label="Clarity of the site's entity signals",
            classification=ObservationConfidenceClass.INFERRED,
            value=round(_ratio(with_schema, total), 3),
            detail=(
                "Inferred from structured-data coverage. Organisation, product and "
                "article markup make the entities on a page explicit rather than "
                "something a reader has to deduce from prose."
            ),
            source="inference",
        )
    )

    # --- UNKNOWN --------------------------------------------------------
    for unknown in UNKNOWNS:
        signals.append(
            AISearchSignal(
                key="proprietary_ranking_signals",
                label=unknown,
                classification=ObservationConfidenceClass.UNKNOWN,
                value=None,
                detail=(
                    "Not observable. SEO Engine will not estimate this, and any tool "
                    "claiming to measure it is inferring, not observing."
                ),
                source="none",
            )
        )

    scoreable = [
        s
        for s in signals
        if s.classification != ObservationConfidenceClass.UNKNOWN
        and isinstance(s.value, int | float)
        and s.key != "observed_citations"
    ]
    readiness = round(100 * mean([float(s.value) for s in scoreable]), 1) if scoreable else None

    notes = [
        "AI Search readiness is assessed through the same foundations as Search. "
        "There is no separate optimisation discipline, and this module deliberately "
        "does not produce an 'AI ranking score'.",
    ]
    if not gsc_connected:
        notes.append(
            "Search Console is not connected, so no query-coverage or search-presence "
            "signals could be observed."
        )

    return AISearchReadinessReport(
        website_id=website_id,
        signals=signals,
        readiness_score=readiness,
        unknowns=list(UNKNOWNS),
        notes=notes,
    )


def assess_agentic_web_readiness(
    result: CrawlResult, *, website_id: str
) -> AgenticWebReadinessReport:
    """Audit how usable the site is to a browser agent.

    Google's material describes agents interacting through rendered pages, DOM
    structure and the accessibility tree — so this measures accessible names,
    labelled controls, landmarks, keyboard order and JavaScript dependence.
    """
    pages = [p for p in result.pages if not p.error and p.is_indexable]
    if not pages:
        return AgenticWebReadinessReport(website_id=website_id, score=0.0, pages_evaluated=0)

    def ratio(numerator: int, denominator: int) -> float:
        return 1.0 if denominator == 0 else numerator / denominator

    button_named = mean(
        ratio(p.accessibility.buttons_with_accessible_name, p.accessibility.buttons_total)
        for p in pages
    )
    link_named = mean(
        ratio(p.accessibility.links_with_accessible_name, p.accessibility.links_total)
        for p in pages
    )
    control_labelled = mean(
        ratio(p.accessibility.form_controls_labelled, p.accessibility.form_controls_total)
        for p in pages
    )
    landmarks = mean(1.0 if p.accessibility.has_main_landmark else 0.0 for p in pages)
    heading_order = mean(1.0 if p.accessibility.heading_order_valid else 0.0 for p in pages)
    no_js_dependency = mean(0.0 if p.accessibility.rendered_by_javascript else 1.0 for p in pages)
    natural_tab_order = mean(
        1.0 if p.accessibility.tabindex_positive_count == 0 else 0.0 for p in pages
    )

    components = {
        "buttons_with_accessible_names": button_named,
        "links_with_accessible_names": link_named,
        "form_controls_labelled": control_labelled,
        "main_landmark_present": landmarks,
        "valid_heading_order": heading_order,
        "content_without_javascript": no_js_dependency,
        "natural_keyboard_order": natural_tab_order,
    }
    score = round(100 * mean(components.values()), 1)

    issues: list[SEOIssue] = []
    if natural_tab_order < 1.0:
        offenders = [p.url for p in pages if p.accessibility.tabindex_positive_count > 0]
        issues.append(
            SEOIssue(
                check_id="positive_tabindex",
                title="Positive tabindex values override the natural keyboard order",
                severity=IssueSeverity.LOW,
                dimension=SEODimension.AI_SEARCH_READINESS,
                url=offenders[0],
                detail=(
                    "Positive tabindex makes focus order diverge from document order, "
                    "which confuses both keyboard users and agents that traverse the page."
                ),
                recommendation='Use tabindex="0" or rely on document order.',
                affected_urls=offenders[:50],
            )
        )

    return AgenticWebReadinessReport(
        website_id=website_id,
        score=score,
        signals={k: round(v, 3) for k, v in components.items()},
        issues=issues,
        pages_evaluated=len(pages),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 3) if denominator else 0.0


__all__ = [
    "UNKNOWNS",
    "assess_agentic_web_readiness",
    "assess_ai_search_readiness",
]
