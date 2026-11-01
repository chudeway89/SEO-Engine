"""On-page keyword alignment.

The technical audit already checks whether a title or meta description exists
and how long it is. This engine answers the question the audit cannot: does the
page *say what it is for*? For each page with a keyword mapped to it, it
measures whether the title, H1, meta description, opening copy and URL carry
that keyword's terms, and proposes a corrected title where they do not.

The proposal is a deterministic rearrangement of facts the platform holds — the
mapped keyword and the brand name — never invented copy. A meta description is
not proposed at all: writing one needs prose, so the engine states what it must
contain and leaves the wording to a writer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.engines.seo.checks import TITLE_MAX_LENGTH
from seo_engine.engines.seo.pages import PageFacts

#: Weight of each element in the 0-100 alignment score. The title and H1 carry
#: most of the topical signal; the URL carries the least and is the costliest
#: to change.
ELEMENT_WEIGHTS: dict[str, float] = {
    "title": 35.0,
    "h1": 25.0,
    "meta_description": 15.0,
    "opening_copy": 15.0,
    "url": 10.0,
}

#: An element "carries" the keyword when it holds this share of its terms.
COVERAGE_THRESHOLD = 0.67

#: Below this, the page is reported as misaligned with its keyword.
ALIGNMENT_PASS = 60.0

OPENING_WORDS = 120


@dataclass(slots=True)
class ElementCoverage:
    element: str
    coverage: float
    carries_keyword: bool
    current: str


@dataclass(slots=True)
class PageAlignment:
    url: str
    keyword: str
    score: float
    elements: list[ElementCoverage] = field(default_factory=list)
    missing_from: list[str] = field(default_factory=list)
    proposed_title: str | None = None
    meta_guidance: str | None = None

    @property
    def aligned(self) -> bool:
        return self.score >= ALIGNMENT_PASS

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "keyword": self.keyword,
            "score": self.score,
            "aligned": self.aligned,
            "missing_from": self.missing_from,
            "elements": {
                e.element: {"coverage": e.coverage, "carries_keyword": e.carries_keyword}
                for e in self.elements
            },
            "proposed_title": self.proposed_title,
            "meta_guidance": self.meta_guidance,
        }


def _coverage(keyword_tokens: set[str], text: str) -> float:
    if not keyword_tokens:
        return 0.0
    return round(len(keyword_tokens & content_tokens(text)) / len(keyword_tokens), 3)


def assess_alignment(page: PageFacts, keyword: str, *, brand_name: str = "") -> PageAlignment:
    """Score how clearly one page signals the keyword mapped to it."""
    tokens = content_tokens(keyword)
    opening = " ".join(page.text.split()[:OPENING_WORDS])
    url_text = page.path.replace("-", " ").replace("/", " ").replace("_", " ")
    texts = {
        "title": page.title,
        "h1": page.h1,
        "meta_description": page.meta_description,
        "opening_copy": opening,
        "url": url_text,
    }

    elements: list[ElementCoverage] = []
    score = 0.0
    for element, text in texts.items():
        coverage = _coverage(tokens, text)
        carries = coverage >= COVERAGE_THRESHOLD
        elements.append(
            ElementCoverage(
                element=element, coverage=coverage, carries_keyword=carries, current=text[:200]
            )
        )
        score += ELEMENT_WEIGHTS[element] * min(coverage / COVERAGE_THRESHOLD, 1.0)

    missing = [e.element for e in elements if not e.carries_keyword]
    alignment = PageAlignment(
        url=page.url,
        keyword=keyword,
        score=round(score, 1),
        elements=elements,
        missing_from=missing,
    )
    if "title" in missing:
        alignment.proposed_title = propose_title(keyword, brand_name, page.title)
    if "meta_description" in missing:
        alignment.meta_guidance = (
            f"Rewrite the meta description to state, in 70-160 characters, what this "
            f"page offers for '{keyword}' and the next step a visitor can take. "
            "The wording is left to a writer; no description has been generated."
        )
    return alignment


def propose_title(keyword: str, brand_name: str, current: str = "") -> str:
    """A title that leads with the keyword and closes with the brand.

    Built only from the keyword and brand name. If the result would exceed the
    title length limit the brand is dropped before the keyword is truncated.
    """
    head = " ".join(word.capitalize() if word.islower() else word for word in keyword.split())
    brand = brand_name.strip()
    candidate = f"{head} | {brand}" if brand else head
    if len(candidate) <= TITLE_MAX_LENGTH:
        return candidate
    if len(head) <= TITLE_MAX_LENGTH:
        return head
    return head[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


def alignment_report(
    pages: list[PageFacts], mapping: dict[str, str], *, brand_name: str = ""
) -> list[PageAlignment]:
    """Assess every page that has a keyword mapped to it.

    ``mapping`` is URL → keyword, as the keyword pipeline's page mapping
    produced it. Pages with no mapped keyword are not judged: alignment
    without a target is meaningless, and is not invented here.
    """
    from seo_engine.engines.seo.pages import key

    by_key = {key(p.url): p for p in pages if p.is_indexable or p.indexability == "unknown"}
    results: list[PageAlignment] = []
    for url, keyword in mapping.items():
        page = by_key.get(key(url))
        if page is None or not keyword:
            continue
        results.append(assess_alignment(page, keyword, brand_name=brand_name))
    return sorted(results, key=lambda a: a.score)


__all__ = [
    "ALIGNMENT_PASS",
    "COVERAGE_THRESHOLD",
    "ELEMENT_WEIGHTS",
    "PageAlignment",
    "alignment_report",
    "assess_alignment",
    "propose_title",
]
