"""What the website says about the business, compared with what the customer told us.

The brand graph is the customer's own account of their business. The website is
a second account, written for visitors. Where they disagree, one of them is out
of date, and either way the platform's analysis is working from a wrong premise.

This engine compares the two:

* **declared, not found** — a service or location in the brand graph that no
  crawled page appears to cover;
* **found, not declared** — a page structured as a service or location page
  whose topic the brand graph does not mention;
* **vocabulary** — the terms the site leads with in titles and headings, so the
  customer can see the language they actually use.

Everything extracted from the site is *untrusted data* and is returned as a
proposal with the URL it came from. Nothing here writes to the brand graph: only
the customer can confirm a fact about their own business.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.engines.seo.pages import PageFacts

SERVICE_PATH = re.compile(r"/(services?|solutions?|treatments?|tests?|what-we-do)/([^/]+)/?$")
LOCATION_PATH = re.compile(r"/(locations?|branches|clinics|offices?|stores?)/([^/]+)/?$")

#: A declared item is "covered" when a page's title/H1/path carries this share
#: of its name's terms.
COVERAGE_THRESHOLD = 0.6


@dataclass(slots=True)
class DeclaredItem:
    kind: str  # "service" | "location"
    name: str
    terms: list[str] = field(default_factory=list)
    landing_url: str | None = None


@dataclass(slots=True)
class ProfileProposal:
    kind: str
    proposal: str
    subject: str
    url: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "proposal": self.proposal,
            "subject": self.subject,
            "url": self.url,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ProfileComparison:
    covered: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[ProfileProposal] = field(default_factory=list)
    vocabulary: list[dict[str, Any]] = field(default_factory=list)
    pages_compared: int = 0


def _page_tokens(page: PageFacts) -> set[str]:
    path_words = page.path.replace("-", " ").replace("/", " ")
    return content_tokens(page.title) | content_tokens(page.h1) | content_tokens(path_words)


def _slug_words(slug: str) -> str:
    return " ".join(part for part in re.split(r"[-_]+", slug) if part)


def compare_profile(
    pages: list[PageFacts],
    declared: list[DeclaredItem],
    *,
    brand_name: str = "",
    vocabulary_size: int = 20,
) -> ProfileComparison:
    comparison = ProfileComparison(pages_compared=len(pages))
    indexable = [p for p in pages if p.is_indexable or p.indexability == "unknown"]
    page_tokens = {p.url: _page_tokens(p) for p in indexable}

    # Declared → found?
    for item in declared:
        tokens = content_tokens(" ".join([item.name, *item.terms[:1]]))
        if not tokens:
            continue
        best_url, best = None, 0.0
        for url, terms in page_tokens.items():
            overlap = len(tokens & terms) / len(tokens)
            if overlap > best:
                best_url, best = url, overlap
        if best >= COVERAGE_THRESHOLD and best_url:
            comparison.covered.append(
                {"kind": item.kind, "name": item.name, "url": best_url, "coverage": round(best, 2)}
            )
        else:
            comparison.proposals.append(
                ProfileProposal(
                    kind=item.kind,
                    proposal="declared_not_found",
                    subject=item.name,
                    url=item.landing_url,
                    detail=(
                        f"The brand profile lists the {item.kind} '{item.name}', but no "
                        "crawled page's title, heading or URL covers it. Either the site "
                        "does not describe it yet, or the profile is out of date."
                    ),
                )
            )

    # Found → declared?
    declared_tokens = [
        (item.kind, content_tokens(" ".join([item.name, *item.terms]))) for item in declared
    ]
    for page in indexable:
        for kind, pattern in (("service", SERVICE_PATH), ("location", LOCATION_PATH)):
            match = pattern.search(page.path.lower())
            if not match:
                continue
            subject = _slug_words(match.group(2))
            subject_tokens = content_tokens(subject)
            if not subject_tokens:
                continue
            known = any(
                k == kind and len(subject_tokens & t) / len(subject_tokens) >= COVERAGE_THRESHOLD
                for k, t in declared_tokens
            )
            if not known:
                comparison.proposals.append(
                    ProfileProposal(
                        kind=kind,
                        proposal="found_not_declared",
                        subject=subject,
                        url=page.url,
                        detail=(
                            f"The site has a {kind} page for '{subject}' that the brand "
                            "profile does not mention. Confirm whether it belongs in the "
                            "profile; it has not been added."
                        ),
                    )
                )

    # The site's own vocabulary, from titles and headings only.
    brand_terms = content_tokens(brand_name)
    counts: Counter[str] = Counter()
    for page in indexable:
        for word in content_tokens(page.title) | content_tokens(page.h1):
            if word in brand_terms or len(word) < 3 or word.isdigit():
                continue
            counts[word] += 1
    comparison.vocabulary = [
        {"term": term, "pages": count}
        for term, count in counts.most_common(vocabulary_size)
        if count > 1
    ]
    return comparison


__all__ = [
    "COVERAGE_THRESHOLD",
    "DeclaredItem",
    "ProfileComparison",
    "ProfileProposal",
    "compare_profile",
]
