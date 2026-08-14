"""Search intent classification.

Deterministic and lexical by design (Rule 11).  Intent is returned as a
*distribution*, not a single label, because real queries are genuinely mixed:
"dna test cost lagos" is commercial, transactional and local at once.

The classifier is honest about its own limits — it reads the query string, not
the SERP.  When a SERP snapshot is available, :func:`refine_with_serp` adjusts
the distribution using observed result types, which is a stronger signal than
any keyword list.
"""

from __future__ import annotations

import re

from seo_engine.schemas.search import IntentDistribution, SERPSnapshot

#: Signals, weighted.  A term appearing in several buckets contributes to each,
#: which is what produces a genuine distribution rather than a hard label.
SIGNALS: dict[str, dict[str, float]] = {
    "informational": {
        "how": 2.0,
        "what": 2.0,
        "why": 2.0,
        "when": 1.5,
        "who": 1.5,
        "guide": 2.0,
        "tutorial": 2.0,
        "learn": 1.5,
        "explained": 2.0,
        "meaning": 1.5,
        "definition": 2.0,
        "examples": 1.5,
        "tips": 1.5,
        "does": 1.2,
        "can": 1.0,
        "is": 0.8,
        "are": 0.8,
        "difference": 1.8,
        "checklist": 1.2,
        "steps": 1.2,
        "guidance": 1.2,
        "faq": 1.5,
    },
    "commercial": {
        "best": 2.5,
        "top": 2.0,
        "review": 2.5,
        "reviews": 2.5,
        "compare": 2.5,
        "comparison": 2.5,
        "vs": 2.5,
        "versus": 2.5,
        "alternative": 2.0,
        "alternatives": 2.0,
        "cheapest": 2.0,
        "affordable": 1.8,
        "rated": 1.5,
        "recommended": 1.5,
        "options": 1.2,
        "which": 1.5,
        "cost": 1.8,
        "price": 1.8,
        "prices": 1.8,
        "pricing": 1.8,
        "fees": 1.5,
        "quote": 1.5,
    },
    "transactional": {
        "buy": 3.0,
        "order": 2.5,
        "book": 2.5,
        "booking": 2.5,
        "purchase": 3.0,
        "hire": 2.5,
        "apply": 2.0,
        "sign up": 2.5,
        "subscribe": 2.5,
        "download": 2.0,
        "get": 1.2,
        "schedule": 2.0,
        "appointment": 2.2,
        "discount": 1.8,
        "deal": 1.8,
        "coupon": 2.0,
        "shop": 2.5,
    },
    "navigational": {
        "login": 3.0,
        "log in": 3.0,
        "sign in": 3.0,
        "portal": 2.0,
        "dashboard": 2.0,
        "account": 1.8,
        "website": 1.5,
        "official": 2.0,
        "contact": 1.5,
        "careers": 1.5,
        "app": 1.2,
    },
    "local": {
        "near me": 3.5,
        "nearby": 3.0,
        "near": 1.5,
        "in": 0.4,
        "local": 2.5,
        "directions": 2.5,
        "opening hours": 2.5,
        "open now": 2.5,
        "address": 2.0,
        "branch": 1.8,
        "centre": 1.2,
        "center": 1.2,
        "clinic": 1.0,
        "office": 1.0,
        "location": 1.5,
    },
    "investigational": {
        "should i": 2.5,
        "worth it": 2.5,
        "pros and cons": 2.5,
        "risks": 2.0,
        "benefits": 1.8,
        "accuracy": 1.8,
        "accurate": 1.8,
        "reliable": 1.8,
        "safe": 1.8,
        "legal": 1.5,
        "requirements": 1.5,
        "process": 1.2,
        "how long": 2.0,
        "evidence": 1.5,
    },
}

QUESTION_PREFIXES = (
    "how",
    "what",
    "why",
    "when",
    "where",
    "who",
    "which",
    "can",
    "is",
    "are",
    "do",
    "does",
    "should",
    "will",
    "may",
)

#: SERP result types that indicate intent far better than the query wording.
SERP_SIGNALS: dict[str, tuple[str, float]] = {
    "local_pack": ("local", 3.0),
    "map": ("local", 3.0),
    "shopping": ("transactional", 3.0),
    "product": ("transactional", 2.0),
    "people_also_ask": ("informational", 1.5),
    "featured_snippet": ("informational", 1.5),
    "video": ("informational", 1.0),
    "review": ("commercial", 2.0),
}

_WORD = re.compile(r"[a-z0-9']+")


def classify_intent(
    keyword: str,
    *,
    brand_terms: set[str] | None = None,
    location_terms: set[str] | None = None,
) -> IntentDistribution:
    """Classify a keyword into a probability distribution over intents."""
    text = f" {keyword.lower().strip()} "
    tokens = set(_WORD.findall(text))
    scores: dict[str, float] = dict.fromkeys(SIGNALS, 0.0)

    for intent, signals in SIGNALS.items():
        for term, weight in signals.items():
            if " " in term:
                if term in text:
                    scores[intent] += weight
            elif term in tokens:
                scores[intent] += weight

    # A brand term in the query is a strong navigational signal.
    if brand_terms and any(term.lower() in text for term in brand_terms if term):
        scores["navigational"] += 3.0

    # A known location makes it local, whatever else it is.
    if location_terms and any(term.lower() in text for term in location_terms if term):
        scores["local"] += 2.5

    first = keyword.strip().lower().split()
    if first and first[0] in QUESTION_PREFIXES:
        scores["informational"] += 1.5

    # A bare service phrase with no other signal is usually commercial
    # investigation rather than pure information seeking.
    if sum(scores.values()) == 0:
        scores["commercial"] = 1.0
        scores["informational"] = 1.0

    return IntentDistribution(**scores)


def refine_with_serp(
    distribution: IntentDistribution, snapshot: SERPSnapshot | None
) -> IntentDistribution:
    """Adjust a lexical classification using observed SERP features.

    Returns the distribution unchanged when no SERP was actually observed —
    absent data never silently becomes a signal.
    """
    if snapshot is None or not snapshot.available or not snapshot.features:
        return distribution

    scores = distribution.model_dump()
    for feature in snapshot.features:
        mapped = SERP_SIGNALS.get(feature.lower())
        if mapped:
            intent, weight = mapped
            scores[intent] = scores.get(intent, 0.0) + weight
    return IntentDistribution(**scores)


def intent_commercial_value(distribution: IntentDistribution) -> float:
    """0-100 score for how close an intent sits to a business outcome.

    Used by the keyword scorer's `intent_value` dimension.  Transactional and
    local intent convert; informational intent builds authority but rarely
    converts directly.
    """
    weights = {
        "transactional": 100.0,
        "local": 85.0,
        "commercial": 80.0,
        "investigational": 55.0,
        "navigational": 40.0,
        "informational": 30.0,
    }
    data = distribution.model_dump()
    return round(sum(data[intent] * weight for intent, weight in weights.items()), 2)


def is_question(keyword: str) -> bool:
    text = keyword.strip().lower()
    return text.endswith("?") or text.split()[0] in QUESTION_PREFIXES if text else False


__all__ = [
    "QUESTION_PREFIXES",
    "SERP_SIGNALS",
    "SIGNALS",
    "classify_intent",
    "intent_commercial_value",
    "is_question",
    "refine_with_serp",
]
