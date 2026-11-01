"""Competitive gaps: coverage plus visibility.

Competitor analysis (CMP-002) says which topics competitors *cover* that the
brand does not. SERP research (RES-002) says who is *visible* for the brand's
queries. Neither alone is a competitive gap worth acting on: a topic a
competitor covers but nobody searches for is not a gap, and a query a
competitor ranks for that the brand already ranks better for is not either.

This engine joins the two:

* **coverage** — a competitor page addresses the topic, no brand page does;
* **visibility** — a competitor ranks on page one for the query and the brand
  does not, or ranks below it;
* **both** — the strongest signal, and scored accordingly.

The score is a transparent sum (see :data:`SCORING`). Every gap carries
``synthetic=True`` when any SERP behind it came from the development adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.pipeline import normalise
from seo_engine.schemas.enums import DataProvenance
from seo_engine.schemas.search import SERPSnapshot

SCORING = (
    "score = 30 for a coverage gap + 10 per competitor covering it (max 3) "
    "+ 35 for a visibility gap where a competitor is on page one and the brand is not "
    "+ 15 where both rank and the competitor ranks higher; capped at 100."
)

PAGE_ONE = 10


@dataclass(slots=True)
class CompetitiveGap:
    topic: str
    gap_types: list[str]
    competitors: list[str]
    brand_position: int | None
    best_competitor_position: int | None
    brand_url: str | None
    score: float
    synthetic: bool
    detail: str
    evidence_refs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "gap_types": self.gap_types,
            "competitors": self.competitors,
            "brand_position": self.brand_position,
            "best_competitor_position": self.best_competitor_position,
            "brand_url": self.brand_url,
            "score": self.score,
            "synthetic": self.synthetic,
            "detail": self.detail,
        }


def _domain(value: str) -> str:
    return value.lower().removeprefix("www.")


def competitive_gaps(
    *,
    keyword_gaps: list[dict[str, Any]],
    snapshots: list[SERPSnapshot],
    brand_domain: str | None,
    competitor_domains: set[str],
) -> list[CompetitiveGap]:
    own = _domain(brand_domain or "")
    tracked = {_domain(d) for d in competitor_domains}
    by_query = {normalise(s.query): s for s in snapshots if s.available}

    topics: dict[str, dict[str, Any]] = {}
    for gap in keyword_gaps:
        topic = normalise(str(gap.get("keyword") or ""))
        if topic:
            topics[topic] = {
                "coverage_competitors": sorted(
                    {_domain(d) for d in gap.get("competitor_domains") or []}
                ),
                "brand_url": gap.get("brand_url"),
            }
    for topic in by_query:
        topics.setdefault(topic, {"coverage_competitors": [], "brand_url": None})

    gaps: list[CompetitiveGap] = []
    for topic, info in topics.items():
        coverage = info["coverage_competitors"]
        snapshot = by_query.get(topic)
        brand_position: int | None = None
        competitor_positions: dict[str, int] = {}
        synthetic = False
        if snapshot is not None:
            synthetic = snapshot.provenance is DataProvenance.SYNTHETIC_DEMO
            for item in snapshot.results:
                if item.result_type != "organic":
                    continue
                domain = _domain(item.domain)
                if own and domain == own:
                    brand_position = min(brand_position or item.position, item.position)
                elif domain in tracked or not tracked:
                    current = competitor_positions.get(domain)
                    competitor_positions[domain] = min(current or item.position, item.position)

        best = min(competitor_positions.values()) if competitor_positions else None
        gap_types: list[str] = []
        score = 0.0
        if coverage:
            gap_types.append("coverage")
            score += 30 + 10 * min(len(coverage), 3)
        if (
            best is not None
            and best <= PAGE_ONE
            and (brand_position is None or brand_position > PAGE_ONE)
        ):
            gap_types.append("visibility")
            score += 35
        elif best is not None and brand_position is not None and best < brand_position:
            gap_types.append("visibility")
            score += 15
        if not gap_types:
            continue

        competitors = sorted(
            set(coverage) | {d for d, p in competitor_positions.items() if p <= PAGE_ONE}
        )
        parts = []
        if "coverage" in gap_types:
            parts.append(f"{len(coverage)} competitor(s) cover the topic and no brand page does")
        if "visibility" in gap_types:
            parts.append(
                f"a competitor ranks at position {best} while the brand "
                + (f"ranks at {brand_position}" if brand_position else "was not observed")
            )
        gaps.append(
            CompetitiveGap(
                topic=topic,
                gap_types=gap_types,
                competitors=competitors[:8],
                brand_position=brand_position,
                best_competitor_position=best,
                brand_url=info["brand_url"],
                score=min(score, 100.0),
                synthetic=synthetic,
                detail="; ".join(parts)
                + (" (SERP data is synthetic development data)" if synthetic else "")
                + ".",
            )
        )
    return sorted(gaps, key=lambda g: (-g.score, g.topic))


__all__ = ["PAGE_ONE", "SCORING", "CompetitiveGap", "competitive_gaps"]
