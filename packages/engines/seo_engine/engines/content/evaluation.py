"""Content quality evaluation.

Twelve criteria from the Build Specification, evaluated deterministically
against the draft and its brief. The evaluator is intentionally hard to please
in the ways that matter and indifferent to the ways that do not:

* it **fails** a draft that makes an unsupported claim, contradicts a prohibited
  claim, or stuffs keywords;
* it **does not reward** keyword frequency, length for its own sake, or any
  proxy that a writer could game without helping a reader.

Criteria that genuinely need judgement (originality against the live web, factual
accuracy against a source) are scored on what is checkable — citation presence
and source tier — and the residue is escalated to a human rather than guessed.
"""

from __future__ import annotations

import re
from collections import Counter

from seo_engine.engines.keywords.pipeline import STOPWORDS, content_tokens, normalise
from seo_engine.schemas.content import (
    CONTENT_EVALUATION_CRITERIA,
    ContentBrief,
    ContentDraft,
    ContentEvaluation,
    EvaluationCriterionResult,
)
from seo_engine.schemas.enums import HIGH_RISK_CATEGORIES, SOURCE_TIER_WEIGHT, SearchIntent

#: Above this share of body words, a term is being repeated for machines.
KEYWORD_STUFFING_THRESHOLD = 0.035

#: Criteria that block publication when failed.
BLOCKING_CRITERIA = frozenset({"accuracy", "risk", "brand_alignment", "search_intent"})

PASS_MARK = 60.0

#: Patterns that assert a fact needing a source.
# A trailing \b after "%" never matches (both sides are non-word characters),
# so the percentage form is anchored on its own.
_STATISTIC = re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*(?:%|\bpercent\b|\bper cent\b)", re.I)
_ABSOLUTE_CLAIM = re.compile(
    r"\b(guarantee[sd]?|always|never fails?|100% accurate|the best|cheapest|"
    r"proven to|clinically proven|cures?)\b",
    re.I,
)
_HEDGE = re.compile(r"\b(may|might|can|typically|usually|in most cases|generally)\b", re.I)

_SENTENCE = re.compile(r"[.!?]+\s")


def evaluate_content(
    draft: ContentDraft,
    brief: ContentBrief,
    *,
    brand_voice: dict | None = None,
    existing_hashes: set[str] | None = None,
) -> ContentEvaluation:
    body = draft.body_markdown or "\n".join(s.body for s in draft.sections)
    words = re.findall(r"[a-z0-9']+", body.lower())
    word_count = len(words)

    results: list[EvaluationCriterionResult] = [
        _search_intent(draft, brief, body),
        _accuracy(draft, brief, body),
        _source_quality(draft, brief),
        _originality(draft, body, existing_hashes or set()),
        _usefulness(draft, brief, body, word_count),
        _completeness(draft, brief),
        _brand_alignment(draft, brief, body, brand_voice or {}),
        _readability(body, words),
        _internal_linking(draft, brief),
        _structured_data(draft, brief),
        _conversion_relevance(draft, brief, body),
        _risk(draft, brief, body),
    ]

    stuffing = _keyword_stuffing(words, brief)
    if stuffing:
        for result in results:
            if result.criterion == "usefulness":
                result.score = min(result.score, 35.0)
                result.passed = False
                result.detail += (
                    f" Keyword stuffing detected: {stuffing[0]} accounts for "
                    f"{stuffing[1]:.1%} of the body text."
                )

    blocking = [r.criterion for r in results if r.criterion in BLOCKING_CRITERIA and not r.passed]
    warnings = [
        f"{r.criterion}: {r.detail}"
        for r in results
        if not r.passed and r.criterion not in BLOCKING_CRITERIA
    ]

    overall = round(sum(r.score for r in results) / len(results), 1)
    requires_review = (
        brief.risk_category in HIGH_RISK_CATEGORIES
        or bool(draft.unverified_claims)
        or bool(blocking)
    )

    return ContentEvaluation(
        criteria=results,
        overall_score=overall,
        passed=not blocking and overall >= PASS_MARK,
        blocking_failures=blocking,
        warnings=warnings,
        keyword_stuffing_detected=bool(stuffing),
        requires_human_review=requires_review,
    )


# ---------------------------------------------------------------------------
def _result(
    criterion: str, score: float, passed: bool, detail: str, **evidence
) -> EvaluationCriterionResult:
    return EvaluationCriterionResult(
        criterion=criterion,
        score=round(max(0.0, min(score, 100.0)), 1),
        passed=passed,
        detail=detail,
        evidence=evidence,
    )


def _search_intent(
    draft: ContentDraft, brief: ContentBrief, body: str
) -> EvaluationCriterionResult:
    """Does the draft actually serve the intent the brief specified?"""
    intent = brief.search_intent[0] if brief.search_intent else SearchIntent.INFORMATIONAL
    text = body.lower()
    expectations = {
        SearchIntent.TRANSACTIONAL: ["price", "cost", "book", "order", "contact", "how to"],
        SearchIntent.COMMERCIAL: ["compare", "option", "difference", "choose", "cost"],
        SearchIntent.LOCAL: ["location", "address", "hours", "near", "visit", "contact"],
        SearchIntent.INFORMATIONAL: ["how", "what", "why", "means", "works"],
        SearchIntent.INVESTIGATIONAL: ["evidence", "accuracy", "risk", "limitation", "consider"],
        SearchIntent.NAVIGATIONAL: [],
    }.get(intent, [])

    if not expectations:
        return _result("search_intent", 80.0, True, "No intent-specific markers required.")

    hits = [term for term in expectations if term in text]
    score = 100.0 * len(hits) / len(expectations)
    passed = score >= 40.0
    return _result(
        "search_intent",
        score,
        passed,
        (
            f"The brief specifies {intent.value} intent. The draft addresses "
            f"{len(hits)} of {len(expectations)} expected aspects."
        ),
        intent=intent.value,
        matched=hits,
    )


def _accuracy(draft: ContentDraft, brief: ContentBrief, body: str) -> EvaluationCriterionResult:
    """Statistics and absolute claims must be attributable."""
    statistics = _STATISTIC.findall(body)
    absolutes = _ABSOLUTE_CLAIM.findall(body)
    cited = len(draft.cited_sources)

    problems: list[str] = []
    if statistics and cited == 0:
        problems.append(f"{len(statistics)} statistic(s) appear with no cited source")
    if absolutes:
        problems.append(
            f"absolute claim(s) present: {', '.join(sorted({a.lower() for a in absolutes}))}"
        )
    if draft.unverified_claims:
        problems.append(f"{len(draft.unverified_claims)} claim(s) flagged unverified by the writer")

    prohibited_hit = [
        claim for claim in brief.prohibited_claims if claim and claim.lower()[:40] in body.lower()
    ]
    if prohibited_hit:
        problems.append(f"{len(prohibited_hit)} prohibited claim(s) appear in the draft")

    score = 100.0 - 30.0 * len(problems)
    return _result(
        "accuracy",
        score,
        not problems,
        "; ".join(problems) if problems else "No unsupported or prohibited claims detected.",
        statistics=len(statistics),
        cited_sources=cited,
    )


def _source_quality(draft: ContentDraft, brief: ContentBrief) -> EvaluationCriterionResult:
    if not draft.cited_sources:
        needs_sources = brief.risk_category in HIGH_RISK_CATEGORIES
        return _result(
            "source_quality",
            20.0 if needs_sources else 55.0,
            not needs_sources,
            (
                "No sources are cited, and this is a regulated content category."
                if needs_sources
                else "No sources are cited. Acceptable here, but weaker than it could be."
            ),
        )

    verified = [s for s in draft.cited_sources if s.verified]
    if not verified:
        return _result(
            "source_quality",
            25.0,
            False,
            (
                f"{len(draft.cited_sources)} source(s) are cited but none were fetched "
                "and verified by the platform."
            ),
        )
    weight = sum(SOURCE_TIER_WEIGHT[s.tier] for s in verified) / len(verified)
    return _result(
        "source_quality",
        100.0 * weight,
        weight >= 0.5,
        (f"{len(verified)} verified source(s) with an average trust weight of {weight:.2f}."),
        verified=len(verified),
        total=len(draft.cited_sources),
    )


def _originality(
    draft: ContentDraft, body: str, existing_hashes: set[str]
) -> EvaluationCriterionResult:
    import hashlib

    digest = hashlib.sha256(normalise(body).encode()).hexdigest()
    if digest in existing_hashes:
        return _result(
            "originality",
            0.0,
            False,
            "The draft is byte-identical to content that already exists.",
        )

    sentences = [s.strip() for s in _SENTENCE.split(body) if len(s.strip()) > 30]
    if not sentences:
        return _result("originality", 40.0, False, "Too little prose to assess originality.")

    unique_ratio = len({normalise(s) for s in sentences}) / len(sentences)
    return _result(
        "originality",
        100.0 * unique_ratio,
        unique_ratio >= 0.9,
        (
            f"{unique_ratio:.0%} of sentences are distinct within the draft. This checks "
            "internal repetition only; originality against the live web is not "
            "measurable from here and is left to human review."
        ),
        sentences=len(sentences),
    )


def _usefulness(
    draft: ContentDraft, brief: ContentBrief, body: str, word_count: int
) -> EvaluationCriterionResult:
    """Does it answer the questions the brief said readers ask?"""
    if not brief.questions_to_answer:
        answered_ratio = 1.0 if word_count >= 200 else 0.4
        detail = "The brief listed no questions; judged on substance alone."
    else:
        text = body.lower()
        answered = [
            q
            for q in brief.questions_to_answer
            if len(content_tokens(q) & content_tokens(text)) >= max(1, len(content_tokens(q)) // 2)
        ]
        answered_ratio = len(answered) / len(brief.questions_to_answer)
        detail = (
            f"{len(answered)} of {len(brief.questions_to_answer)} briefed questions are addressed."
        )

    # Length is a floor, never a target: past the brief's count it adds nothing.
    length_factor = min(word_count / max(brief.target_word_count * 0.6, 1), 1.0)
    score = 100.0 * (0.7 * answered_ratio + 0.3 * length_factor)
    return _result(
        "usefulness",
        score,
        score >= 50.0,
        detail,
        word_count=word_count,
        target=brief.target_word_count,
    )


def _completeness(draft: ContentDraft, brief: ContentBrief) -> EvaluationCriterionResult:
    if not brief.required_sections:
        return _result("completeness", 70.0, True, "The brief required no specific sections.")
    headings = " ".join(s.heading.lower() for s in draft.sections)
    covered = [
        section
        for section in brief.required_sections
        if len(content_tokens(section) & content_tokens(headings)) >= 1
    ]
    ratio = len(covered) / len(brief.required_sections)
    return _result(
        "completeness",
        100.0 * ratio,
        ratio >= 0.6,
        f"{len(covered)} of {len(brief.required_sections)} required sections are present.",
        missing=[s for s in brief.required_sections if s not in covered],
    )


def _brand_alignment(
    draft: ContentDraft, brief: ContentBrief, body: str, voice: dict
) -> EvaluationCriterionResult:
    text = body.lower()
    forbidden = [t for t in (voice.get("forbidden_terminology") or []) if t.lower() in text]
    prohibited = [c for c in brief.prohibited_claims if c and c.lower()[:40] in text]

    problems: list[str] = []
    if forbidden:
        problems.append(f"forbidden terminology used: {', '.join(forbidden)}")
    if prohibited:
        problems.append(f"{len(prohibited)} prohibited claim(s) present")

    score = 100.0 - 40.0 * len(problems)
    return _result(
        "brand_alignment",
        score,
        not problems,
        "; ".join(problems) if problems else "No forbidden terminology or prohibited claims.",
    )


def _readability(body: str, words: list[str]) -> EvaluationCriterionResult:
    sentences = [s for s in _SENTENCE.split(body) if s.strip()]
    if not sentences or not words:
        return _result("readability", 30.0, False, "Not enough prose to assess.")
    average = len(words) / len(sentences)
    # 12-22 words per sentence reads comfortably for most business audiences.
    if 12 <= average <= 22:
        score = 100.0
    elif average < 12:
        score = 70.0
    else:
        score = max(30.0, 100.0 - (average - 22) * 4)
    return _result(
        "readability",
        score,
        score >= 60.0,
        f"Average sentence length is {average:.1f} words.",
        sentences=len(sentences),
    )


def _internal_linking(draft: ContentDraft, brief: ContentBrief) -> EvaluationCriterionResult:
    if not brief.internal_links:
        return _result("internal_linking", 70.0, True, "The brief suggested no internal links.")
    included = {link.url for link in draft.internal_links}
    briefed = {link.url for link in brief.internal_links}
    ratio = len(included & briefed) / len(briefed)
    return _result(
        "internal_linking",
        100.0 * ratio,
        ratio >= 0.5,
        f"{len(included & briefed)} of {len(briefed)} briefed internal links are present.",
    )


def _structured_data(draft: ContentDraft, brief: ContentBrief) -> EvaluationCriterionResult:
    if draft.schema_recommendation:
        return _result(
            "structured_data",
            90.0,
            True,
            f"Structured data proposed: {draft.schema_recommendation.get('@type', 'unknown')}.",
        )
    return _result(
        "structured_data",
        50.0,
        True,
        (
            "No structured data proposed. Only mark up what a reader can actually see "
            "on the page, so this is not automatically a failure."
        ),
    )


def _conversion_relevance(
    draft: ContentDraft, brief: ContentBrief, body: str
) -> EvaluationCriterionResult:
    if not brief.cta:
        return _result("conversion_relevance", 60.0, True, "The brief specified no CTA.")
    if draft.cta and draft.cta.strip():
        return _result("conversion_relevance", 95.0, True, "A clear next step is present.")
    return _result(
        "conversion_relevance",
        35.0,
        False,
        "The brief specified a call to action but the draft has none.",
    )


def _risk(draft: ContentDraft, brief: ContentBrief, body: str) -> EvaluationCriterionResult:
    if brief.risk_category not in HIGH_RISK_CATEGORIES:
        absolutes = _ABSOLUTE_CLAIM.findall(body)
        return _result(
            "risk",
            100.0 if not absolutes else 55.0,
            not absolutes,
            "No elevated risk category and no absolute claims."
            if not absolutes
            else f"Absolute claims present: {', '.join(sorted({a.lower() for a in absolutes}))}.",
        )

    problems: list[str] = []
    if not draft.cited_sources:
        problems.append("regulated content with no cited sources")
    if _ABSOLUTE_CLAIM.search(body):
        problems.append("absolute claim in regulated content")
    if not _HEDGE.search(body):
        problems.append("no qualifying language in regulated content")

    score = 100.0 - 35.0 * len(problems)
    return _result(
        "risk",
        score,
        not problems,
        "; ".join(problems)
        if problems
        else f"{brief.risk_category.value} content is appropriately qualified and sourced.",
        category=brief.risk_category.value,
    )


def _keyword_stuffing(words: list[str], brief: ContentBrief) -> tuple[str, float] | None:
    if len(words) < 100:
        return None
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) > 3)
    if not counts:
        return None
    term, count = counts.most_common(1)[0]
    share = count / len(words)
    if share > KEYWORD_STUFFING_THRESHOLD:
        return term, share
    return None


def evaluation_criteria() -> tuple[str, ...]:
    return CONTENT_EVALUATION_CRITERIA


__all__ = [
    "BLOCKING_CRITERIA",
    "KEYWORD_STUFFING_THRESHOLD",
    "PASS_MARK",
    "evaluate_content",
    "evaluation_criteria",
]
