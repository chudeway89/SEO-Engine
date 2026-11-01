"""The search demand landscape, from measured queries only.

Given the queries a search engine actually reported for the site (Search
Console), this summarises *where demand sits*: how much is branded, how it
divides by intent and topic, how much is asked as a question, and how much sits
in positions where a modest improvement would change clicks.

It never extrapolates beyond what was reported. Search Console shows demand the
site already appears for; demand the site is invisible to is, by construction,
absent from these figures, and the summary states that limitation rather than
estimating the missing market.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.intent import classify_intent, is_question
from seo_engine.engines.keywords.pipeline import content_tokens

POSITION_BANDS: tuple[tuple[str, float, float], ...] = (
    ("top_3", 0.0, 3.5),
    ("page_1", 3.5, 10.5),
    ("striking_distance", 10.5, 20.5),
    ("beyond_page_2", 20.5, 1000.0),
)

#: The limitation every landscape carries, because it is always true.
VISIBILITY_LIMITATION = (
    "Search Console reports only queries the site already appeared for. Demand "
    "for which the site is not visible at all is absent from these figures and "
    "has not been estimated."
)


@dataclass(slots=True)
class DemandLandscape:
    queries: int = 0
    impressions: int = 0
    clicks: int = 0
    branded_impressions: int = 0
    question_impressions: int = 0
    by_intent: dict[str, int] = field(default_factory=dict)
    by_band: dict[str, dict[str, int]] = field(default_factory=dict)
    top_topics: list[dict[str, Any]] = field(default_factory=list)
    striking_distance: list[dict[str, Any]] = field(default_factory=list)
    provenance: str = "unknown"

    @property
    def branded_share(self) -> float:
        return round(self.branded_impressions / self.impressions, 4) if self.impressions else 0.0

    @property
    def question_share(self) -> float:
        return round(self.question_impressions / self.impressions, 4) if self.impressions else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "queries": self.queries,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "branded_share": self.branded_share,
            "question_share": self.question_share,
            "by_intent": self.by_intent,
            "by_band": self.by_band,
            "top_topics": self.top_topics,
            "striking_distance": self.striking_distance,
            "provenance": self.provenance,
            "limitation": VISIBILITY_LIMITATION,
        }


def _band(position: float) -> str:
    for name, low, high in POSITION_BANDS:
        if low <= position < high:
            return name
    return "beyond_page_2"


def demand_landscape(
    rows: list[dict[str, Any]],
    *,
    brand_terms: set[str],
    location_terms: set[str] | None = None,
    topic_limit: int = 15,
) -> DemandLandscape:
    """Summarise measured demand. ``rows`` carry query/impressions/clicks/position/provenance."""
    landscape = DemandLandscape()
    if not rows:
        return landscape

    provenances = {str(r.get("provenance", "unknown")) for r in rows}
    landscape.provenance = (
        "synthetic_demo"
        if "synthetic_demo" in provenances
        else "observed"
        if provenances == {"observed"}
        else "unknown"
    )

    brand = {t.lower() for t in brand_terms if t}
    topics: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"impressions": 0, "clicks": 0, "queries": 0}
    )
    bands: dict[str, dict[str, int]] = {
        name: {"queries": 0, "impressions": 0, "clicks": 0} for name, _, _ in POSITION_BANDS
    }

    for row in rows:
        query = str(row.get("query") or "")
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        position = float(row.get("position") or 0.0)
        if not query:
            continue
        landscape.queries += 1
        landscape.impressions += impressions
        landscape.clicks += clicks

        lowered = query.lower()
        if any(term in lowered for term in brand):
            landscape.branded_impressions += impressions
        if is_question(query):
            landscape.question_impressions += impressions

        intent = classify_intent(
            query, brand_terms=brand, location_terms=location_terms
        ).primary.value
        landscape.by_intent[intent] = landscape.by_intent.get(intent, 0) + impressions

        band = _band(position)
        bands[band]["queries"] += 1
        bands[band]["impressions"] += impressions
        bands[band]["clicks"] += clicks

        tokens = sorted(content_tokens(query) - brand)
        topic = " ".join(tokens[:2]) if tokens else lowered
        topics[topic]["impressions"] += impressions
        topics[topic]["clicks"] += clicks
        topics[topic]["queries"] += 1

        if band == "striking_distance" and impressions > 0:
            landscape.striking_distance.append(
                {
                    "query": query,
                    "impressions": impressions,
                    "clicks": clicks,
                    "position": round(position, 1),
                }
            )

    landscape.by_band = bands
    landscape.top_topics = [
        {"topic": topic, **values}
        for topic, values in sorted(topics.items(), key=lambda kv: -kv[1]["impressions"])[
            :topic_limit
        ]
    ]
    landscape.striking_distance.sort(key=lambda r: -r["impressions"])
    landscape.striking_distance = landscape.striking_distance[:25]
    return landscape


__all__ = ["POSITION_BANDS", "VISIBILITY_LIMITATION", "DemandLandscape", "demand_landscape"]
