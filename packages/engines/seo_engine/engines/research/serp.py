"""What the observed results pages say.

Summarises a set of SERP snapshots: which features appear and how often, which
domains recur, where the brand itself appears, and how the observed features
refine each query's lexical intent.

Synthetic snapshots (from the development adapter) are summarised with the same
code and carry ``synthetic=True`` through every figure, so a SERP-derived claim
can never lose the fact that no real results page stood behind it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.intent import classify_intent, refine_with_serp
from seo_engine.schemas.enums import DataProvenance
from seo_engine.schemas.search import SERPSnapshot


def _domain(value: str) -> str:
    return value.lower().removeprefix("www.")


@dataclass(slots=True)
class SERPLandscape:
    queries_observed: int = 0
    queries_unavailable: list[str] = field(default_factory=list)
    synthetic: bool = False
    feature_frequency: dict[str, int] = field(default_factory=dict)
    recurring_domains: list[dict[str, Any]] = field(default_factory=list)
    brand_positions: dict[str, int | None] = field(default_factory=dict)
    intent_shifts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def brand_visible_share(self) -> float:
        if not self.brand_positions:
            return 0.0
        visible = sum(1 for p in self.brand_positions.values() if p is not None)
        return round(visible / len(self.brand_positions), 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "queries_observed": self.queries_observed,
            "queries_unavailable": self.queries_unavailable,
            "synthetic": self.synthetic,
            "feature_frequency": self.feature_frequency,
            "recurring_domains": self.recurring_domains,
            "brand_positions": self.brand_positions,
            "brand_visible_share": self.brand_visible_share,
            "intent_shifts": self.intent_shifts,
        }


def summarise_serps(
    snapshots: list[SERPSnapshot], *, brand_domain: str | None, top_domains: int = 15
) -> SERPLandscape:
    landscape = SERPLandscape()
    own = _domain(brand_domain or "")
    features: Counter[str] = Counter()
    appearances: Counter[str] = Counter()
    positions: dict[str, list[int]] = defaultdict(list)

    for snapshot in snapshots:
        if snapshot.provenance is DataProvenance.SYNTHETIC_DEMO:
            landscape.synthetic = True
        if not snapshot.available:
            landscape.queries_unavailable.append(snapshot.query)
            continue
        landscape.queries_observed += 1
        features.update(set(snapshot.features))

        brand_position: int | None = None
        for item in snapshot.results:
            if item.result_type != "organic":
                continue
            domain = _domain(item.domain)
            if own and domain == own:
                if brand_position is None or item.position < brand_position:
                    brand_position = item.position
                continue
            appearances[domain] += 1
            positions[domain].append(item.position)
        landscape.brand_positions[snapshot.query] = brand_position

        lexical = classify_intent(snapshot.query)
        refined = refine_with_serp(lexical, snapshot)
        if refined.primary is not lexical.primary:
            landscape.intent_shifts.append(
                {
                    "query": snapshot.query,
                    "lexical_intent": lexical.primary.value,
                    "observed_intent": refined.primary.value,
                    "features": sorted(snapshot.features),
                }
            )

    landscape.feature_frequency = dict(features.most_common())
    landscape.recurring_domains = [
        {
            "domain": domain,
            "appearances": count,
            "average_position": round(sum(positions[domain]) / len(positions[domain]), 1),
        }
        for domain, count in appearances.most_common(top_domains)
    ]
    return landscape


__all__ = ["SERPLandscape", "summarise_serps"]
