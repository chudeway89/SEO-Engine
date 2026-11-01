"""Search intent versus page type.

Ranking for a query needs the *right kind* of page, not just the right words. A
transactional query answered by a blog post, or an informational question
answered by a sales page, underperforms however well the copy is optimised.

This engine classifies a page's type from observable structure — its URL, its
title and heading vocabulary, its structured data — and compares it with the
intent distribution of the query mapped to it. The classification is lexical
and deterministic, and it says which signal decided it, so a reviewer can
disagree with a specific reason rather than a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from seo_engine.engines.seo.pages import PageFacts
from seo_engine.schemas.enums import SearchIntent
from seo_engine.schemas.search import IntentDistribution


class PageType(StrEnum):
    HOME = "home"
    SERVICE = "service"
    PRODUCT = "product"
    PRICING = "pricing"
    LOCATION = "location"
    ARTICLE = "article"
    GUIDE = "guide"
    FAQ = "faq"
    COMPARISON = "comparison"
    CONTACT = "contact"
    CATEGORY = "category"
    OTHER = "other"


#: (page type, URL path pattern). Checked in order; the first match wins.
PATH_RULES: tuple[tuple[PageType, re.Pattern[str]], ...] = (
    (PageType.PRICING, re.compile(r"/(pricing|prices?|cost|fees?|plans?)(/|$)")),
    (PageType.CONTACT, re.compile(r"/(contact|book|booking|appointments?|enquir\w*)(/|$)")),
    (PageType.FAQ, re.compile(r"/(faqs?|questions|help)(/|$)")),
    (PageType.LOCATION, re.compile(r"/(locations?|branches|clinics|stores?|near-me)(/|$)")),
    (PageType.COMPARISON, re.compile(r"(-vs-|/compare|/comparison|/alternatives?)")),
    (PageType.SERVICE, re.compile(r"/(services?|solutions?|treatments?|tests?)(/|$)")),
    (PageType.PRODUCT, re.compile(r"/(products?|shop|store)/")),
    (PageType.GUIDE, re.compile(r"/(guides?|learn|resources?|how-to)(/|$)")),
    (PageType.ARTICLE, re.compile(r"/(blog|news|articles?|insights?|posts?)(/|$)")),
)

SCHEMA_RULES: dict[str, PageType] = {
    "faqpage": PageType.FAQ,
    "article": PageType.ARTICLE,
    "blogposting": PageType.ARTICLE,
    "newsarticle": PageType.ARTICLE,
    "howto": PageType.GUIDE,
    "product": PageType.PRODUCT,
    "service": PageType.SERVICE,
    "medicaltest": PageType.SERVICE,
    "localbusiness": PageType.LOCATION,
    "medicalclinic": PageType.LOCATION,
    "offercatalog": PageType.PRICING,
}

TITLE_RULES: tuple[tuple[PageType, re.Pattern[str]], ...] = (
    (PageType.FAQ, re.compile(r"\b(faq|frequently asked)\b", re.I)),
    (PageType.PRICING, re.compile(r"\b(pricing|prices|cost|how much)\b", re.I)),
    (PageType.COMPARISON, re.compile(r"\b(vs\.?|versus|compared?|alternatives?)\b", re.I)),
    (PageType.GUIDE, re.compile(r"\b(guide|how to|explained|what is|what are)\b", re.I)),
    (PageType.CONTACT, re.compile(r"\b(contact|book an?|get in touch)\b", re.I)),
)

#: Page types that serve each intent well. Anything else is a mismatch.
INTENT_FIT: dict[SearchIntent, frozenset[PageType]] = {
    SearchIntent.INFORMATIONAL: frozenset(
        {PageType.ARTICLE, PageType.GUIDE, PageType.FAQ, PageType.CATEGORY}
    ),
    SearchIntent.INVESTIGATIONAL: frozenset(
        {PageType.GUIDE, PageType.COMPARISON, PageType.ARTICLE, PageType.FAQ}
    ),
    SearchIntent.COMMERCIAL: frozenset(
        {
            PageType.SERVICE,
            PageType.PRODUCT,
            PageType.PRICING,
            PageType.COMPARISON,
            PageType.CATEGORY,
        }
    ),
    SearchIntent.TRANSACTIONAL: frozenset(
        {PageType.SERVICE, PageType.PRODUCT, PageType.PRICING, PageType.CONTACT}
    ),
    SearchIntent.LOCAL: frozenset({PageType.LOCATION, PageType.CONTACT, PageType.SERVICE}),
    SearchIntent.NAVIGATIONAL: frozenset({PageType.HOME, PageType.CONTACT, PageType.SERVICE}),
}

#: The page type to recommend when the current one does not fit.
RECOMMENDED_TYPE: dict[SearchIntent, PageType] = {
    SearchIntent.INFORMATIONAL: PageType.GUIDE,
    SearchIntent.INVESTIGATIONAL: PageType.COMPARISON,
    SearchIntent.COMMERCIAL: PageType.SERVICE,
    SearchIntent.TRANSACTIONAL: PageType.SERVICE,
    SearchIntent.LOCAL: PageType.LOCATION,
    SearchIntent.NAVIGATIONAL: PageType.HOME,
}

#: The secondary intent counts when it carries at least this weight.
SECONDARY_INTENT_WEIGHT = 0.3


@dataclass(slots=True)
class PageTypeDecision:
    page_type: PageType
    signal: str


def classify_page_type(page: PageFacts) -> PageTypeDecision:
    path = page.path.lower()
    if path in {"", "/"}:
        return PageTypeDecision(PageType.HOME, "the URL is the site root")
    for schema in page.schema_types:
        mapped = SCHEMA_RULES.get(schema.lower().split("/")[-1])
        if mapped:
            return PageTypeDecision(mapped, f"structured data declares {schema}")
    for page_type, pattern in PATH_RULES:
        if pattern.search(path):
            return PageTypeDecision(page_type, f"the URL path matches {page_type.value}")
    heading = f"{page.title} {page.h1}"
    for page_type, pattern in TITLE_RULES:
        if pattern.search(heading):
            return PageTypeDecision(page_type, f"the title or H1 reads as {page_type.value}")
    return PageTypeDecision(PageType.OTHER, "no structural signal identified the page type")


@dataclass(slots=True)
class IntentFit:
    url: str
    keyword: str
    page_type: PageType
    page_type_signal: str
    primary_intent: SearchIntent
    intent_confidence: float
    fits: bool
    recommended_page_type: PageType | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "keyword": self.keyword,
            "page_type": self.page_type.value,
            "page_type_signal": self.page_type_signal,
            "primary_intent": self.primary_intent.value,
            "intent_confidence": self.intent_confidence,
            "fits": self.fits,
            "recommended_page_type": (
                self.recommended_page_type.value if self.recommended_page_type else None
            ),
            "detail": self.detail,
        }


def assess_fit(page: PageFacts, keyword: str, intent: IntentDistribution) -> IntentFit:
    """Does this page's type serve the query's intent?"""
    decision = classify_page_type(page)
    primary = intent.primary
    data = intent.model_dump()
    acceptable = set(INTENT_FIT[primary])
    for name, weight in data.items():
        if name != primary.value and weight >= SECONDARY_INTENT_WEIGHT:
            acceptable |= INTENT_FIT[SearchIntent(name)]

    if decision.page_type is PageType.OTHER:
        return IntentFit(
            url=page.url,
            keyword=keyword,
            page_type=decision.page_type,
            page_type_signal=decision.signal,
            primary_intent=primary,
            intent_confidence=intent.primary_probability,
            fits=True,
            recommended_page_type=None,
            detail=(
                "The page type could not be identified from its structure, so no "
                "mismatch is asserted."
            ),
        )

    fits = decision.page_type in acceptable
    recommended = None if fits else RECOMMENDED_TYPE[primary]
    detail = (
        f"'{keyword}' is primarily {primary.value} ({intent.primary_probability:.0%}); "
        f"the page reads as a {decision.page_type.value} page because {decision.signal}. "
        + (
            "That type serves the intent."
            if fits
            else f"A {recommended.value if recommended else ''} page would serve it better."
        )
    )
    return IntentFit(
        url=page.url,
        keyword=keyword,
        page_type=decision.page_type,
        page_type_signal=decision.signal,
        primary_intent=primary,
        intent_confidence=intent.primary_probability,
        fits=fits,
        recommended_page_type=recommended,
        detail=detail,
    )


__all__ = [
    "INTENT_FIT",
    "RECOMMENDED_TYPE",
    "IntentFit",
    "PageType",
    "PageTypeDecision",
    "assess_fit",
    "classify_page_type",
]
