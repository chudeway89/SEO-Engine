"""Questions the audience asks, and whether the site answers them.

Questions are gathered from sources that each say something different:

* **Search Console** — questions people asked *and the site appeared for*;
* **SERP people-also-ask** — questions the search engine associates with a query;
* **the brand graph** — questions written into an audience's vocabulary by the
  customer.

Each question keeps every source it came from and the weakest provenance among
them, so a question seen only on a synthetic results page stays labelled
synthetic. Mapping to pages is lexical: a page "answers" a question when its
headings, or failing that its copy, carry most of the question's terms. That is
a coverage signal, not a judgement of answer quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_engine.engines.keywords.intent import classify_intent, is_question
from seo_engine.engines.keywords.pipeline import content_tokens, normalise
from seo_engine.engines.seo.pages import PageFacts
from seo_engine.schemas.enums import DataProvenance
from seo_engine.schemas.search import SearchQuestion

#: Share of a question's terms a heading must carry to count as answering it.
HEADING_COVERAGE = 0.6
#: A stricter bar for body copy, which is long enough to contain anything.
COPY_COVERAGE = 0.85

_PROVENANCE_RANK = {
    DataProvenance.SYNTHETIC_DEMO: 0,
    DataProvenance.UNKNOWN: 1,
    DataProvenance.INFERRED: 2,
    DataProvenance.ESTIMATED: 2,
    DataProvenance.USER_PROVIDED: 3,
    DataProvenance.OBSERVED: 4,
}


@dataclass(slots=True)
class QuestionCandidate:
    question: str
    sources: list[str] = field(default_factory=list)
    provenance: DataProvenance = DataProvenance.UNKNOWN
    impressions: int = 0
    answered_by_url: str | None = None
    answered_in: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "question": self.question,
            "sources": self.sources,
            "provenance": self.provenance.value,
            "impressions": self.impressions,
            "answered_by_url": self.answered_by_url,
            "answered_in": self.answered_in,
        }

    def contract(self) -> SearchQuestion:
        return SearchQuestion(
            question=self.question,
            source="+".join(self.sources),
            intent=classify_intent(self.question),
            answered_by_url=self.answered_by_url,
            provenance=self.provenance,
        )


def _weakest(left: DataProvenance, right: DataProvenance) -> DataProvenance:
    return left if _PROVENANCE_RANK[left] <= _PROVENANCE_RANK[right] else right


def gather_questions(
    *,
    gsc_queries: list[dict[str, object]] | None = None,
    serp_questions: list[tuple[str, DataProvenance]] | None = None,
    audience_questions: list[str] | None = None,
) -> list[QuestionCandidate]:
    merged: dict[str, QuestionCandidate] = {}

    def add(text: str, source: str, provenance: DataProvenance, impressions: int = 0) -> None:
        text = " ".join(text.split()).strip()
        if not text or not is_question(text):
            return
        norm = normalise(text).rstrip("?")
        candidate = merged.get(norm)
        if candidate is None:
            display = text if text.endswith("?") else f"{text}?"
            merged[norm] = QuestionCandidate(
                question=display[0].upper() + display[1:],
                sources=[source],
                provenance=provenance,
                impressions=impressions,
            )
            return
        if source not in candidate.sources:
            candidate.sources.append(source)
        candidate.provenance = _weakest(candidate.provenance, provenance)
        candidate.impressions += impressions

    for row in gsc_queries or []:
        add(
            str(row.get("query") or ""),
            "search_console",
            DataProvenance(str(row.get("provenance") or "unknown")),
            int(row.get("impressions") or 0),  # type: ignore[call-overload]
        )
    for text, provenance in serp_questions or []:
        add(text, "serp_people_also_ask", provenance)
    for text in audience_questions or []:
        add(text, "brand_audience_vocabulary", DataProvenance.USER_PROVIDED)

    return sorted(merged.values(), key=lambda q: (-len(q.sources), -q.impressions, q.question))


def map_to_pages(
    questions: list[QuestionCandidate], pages: list[PageFacts]
) -> list[QuestionCandidate]:
    """Attach the page (and where on it) that already answers each question."""
    for question in questions:
        tokens = content_tokens(question.question)
        if not tokens:
            continue
        best: tuple[float, str, str] | None = None
        for page in pages:
            if not page.is_indexable:
                continue
            for heading in [page.h1, *page.headings]:
                overlap = len(tokens & content_tokens(heading)) / len(tokens)
                if overlap >= HEADING_COVERAGE and (best is None or overlap > best[0]):
                    best = (overlap, page.url, "heading")
            copy_overlap = len(tokens & content_tokens(page.text[:8000])) / len(tokens)
            if copy_overlap >= COPY_COVERAGE and (best is None or copy_overlap > best[0] + 0.2):
                best = (copy_overlap - 0.2, page.url, "copy")
        if best is not None:
            question.answered_by_url, question.answered_in = best[1], best[2]
    return questions


__all__ = [
    "COPY_COVERAGE",
    "HEADING_COVERAGE",
    "QuestionCandidate",
    "gather_questions",
    "map_to_pages",
]
