"""The keyword pipeline.

    Seeds → Expand → Normalise → Deduplicate → Classify intent →
    Cluster → Score → Map to URLs → Identify gaps

Two rules shape every stage:

* **Rule 14 — nothing is invented.** Volume, difficulty and CPC come only from a
  connected provider. With none connected the metric is ``None`` with
  ``provenance=unknown``; the ``demand`` scoring dimension then contributes
  nothing rather than a guessed value, and the report says so.
* **Rule 11 — deterministic where possible.** Normalisation, deduplication,
  clustering, scoring and URL mapping are all deterministic and reproducible.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

from seo_engine.engines.keywords.intent import (
    classify_intent,
    intent_commercial_value,
    is_question,
)
from seo_engine.schemas.enums import ContentDecision, DataProvenance
from seo_engine.schemas.search import (
    KeywordCluster,
    KeywordMetric,
    KeywordRecord,
    KeywordScoreBreakdown,
)

_WORD = re.compile(r"[a-z0-9']+")

#: Words that carry no topical meaning for clustering or matching.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "doing",
        "have",
        "has",
        "had",
        "having",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "my",
        "your",
        "our",
        "their",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "when",
        "where",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "not",
        "no",
        "yes",
    ]
)

#: Modifiers that produce a genuine long-tail variant of a seed.
EXPANSION_MODIFIERS: dict[str, list[str]] = {
    "commercial": ["best", "top", "compare", "reviews", "cost of", "price of"],
    "transactional": ["book", "order", "buy"],
    "informational": ["how does", "what is", "guide to", "explained"],
    "investigational": ["is it worth", "how accurate is", "how long does"],
}


def normalise(keyword: str) -> str:
    """Canonical comparable form: unaccented, lowercased, single-spaced."""
    text = unicodedata.normalize("NFKD", keyword or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    return " ".join(text.split())


def content_tokens(keyword: str) -> set[str]:
    return {t for t in _WORD.findall(normalise(keyword)) if t not in STOPWORDS}


def dedupe_key(keyword: str) -> str:
    """Key that treats word-order and stopword variants as the same keyword."""
    return " ".join(sorted(content_tokens(keyword)))


@dataclass(slots=True)
class KeywordInputs:
    """Everything the pipeline is allowed to derive keywords from."""

    brand_name: str = ""
    services: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    audience_vocabulary: list[str] = field(default_factory=list)
    audience_pains: list[str] = field(default_factory=list)
    existing_keywords: list[str] = field(default_factory=list)
    competitor_terms: list[str] = field(default_factory=list)
    #: Queries observed in Search Console — the only *measured* demand signal
    #: available without a paid provider.
    observed_queries: list[tuple[str, int, int, float]] = field(default_factory=list)

    @property
    def brand_terms(self) -> set[str]:
        return {t for t in self.brand_name.split() if len(t) > 2} | (
            {self.brand_name} if self.brand_name else set()
        )


def generate_seeds(inputs: KeywordInputs) -> list[str]:
    """Seeds come only from supplied business facts — never from imagination."""
    seeds: list[str] = []
    seeds.extend(inputs.services)
    seeds.extend(inputs.products)
    seeds.extend(inputs.audience_vocabulary)
    seeds.extend(inputs.audience_pains)
    seeds.extend(inputs.existing_keywords)
    seeds.extend(inputs.competitor_terms)
    seeds.extend(q for q, _, _, _ in inputs.observed_queries)

    for offering in [*inputs.services, *inputs.products]:
        for location in inputs.locations:
            seeds.append(f"{offering} {location}")
    return [s for s in (s.strip() for s in seeds) if s]


def expand(seeds: Iterable[str], *, max_per_seed: int = 6) -> list[tuple[str, str]]:
    """Expand seeds into modifier variants.

    Returns ``(keyword, source)`` pairs so provenance survives: a variant this
    function invented is labelled ``expansion``, never ``observed``.
    """
    expanded: list[tuple[str, str]] = []
    # Round-robin across the intent groups so a seed is not expanded entirely
    # into commercial variants before the cap is reached.
    groups = list(EXPANSION_MODIFIERS.values())
    for seed in seeds:
        expanded.append((seed, "seed"))
        produced = 0
        for index in range(max(len(g) for g in groups)):
            for modifiers in groups:
                if produced >= max_per_seed:
                    break
                if index < len(modifiers):
                    expanded.append((f"{modifiers[index]} {seed}", "expansion"))
                    produced += 1
            if produced >= max_per_seed:
                break
    return expanded


def deduplicate(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Collapse variants, preferring the shortest observed surface form."""
    best: dict[str, tuple[str, str]] = {}
    priority = {"observed": 0, "seed": 1, "expansion": 2}
    for keyword, source in pairs:
        cleaned = " ".join(keyword.split())
        if not cleaned:
            continue
        key = dedupe_key(cleaned)
        if not key:
            continue
        current = best.get(key)
        if current is None:
            best[key] = (cleaned, source)
            continue
        # Prefer a measured form, then the shorter phrasing.
        if priority[source] < priority[current[1]] or (
            priority[source] == priority[current[1]] and len(cleaned) < len(current[0])
        ):
            best[key] = (cleaned, source)
    return list(best.values())


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cluster_keywords(
    keywords: list[KeywordRecord], *, threshold: float = 0.34
) -> list[KeywordCluster]:
    """Agglomerate keywords into topic clusters by token overlap.

    Deterministic: keywords are processed in a stable order, so the same input
    always yields the same clusters.
    """
    ordered = sorted(keywords, key=lambda k: (-len(content_tokens(k.keyword)), k.normalised))
    clusters: list[dict] = []

    for record in ordered:
        tokens = content_tokens(record.keyword)
        if not tokens:
            continue
        best_index, best_score = -1, 0.0
        for index, cluster in enumerate(clusters):
            score = jaccard(tokens, cluster["tokens"])
            if score > best_score:
                best_index, best_score = index, score
        if best_index >= 0 and best_score >= threshold:
            cluster = clusters[best_index]
            cluster["members"].append(record)
            # The head keeps the cluster's shared vocabulary rather than
            # accumulating every token from every member.
            cluster["tokens"] &= tokens or cluster["tokens"]
            if not cluster["tokens"]:
                cluster["tokens"] = tokens
        else:
            clusters.append({"tokens": set(tokens), "members": [record]})

    built: list[KeywordCluster] = []
    for index, cluster in enumerate(clusters, start=1):
        members: list[KeywordRecord] = cluster["members"]
        head = max(members, key=lambda k: k.score.opportunity_score or 0.0)
        totals = {
            key: sum(m.intent.model_dump()[key] for m in members)
            for key in members[0].intent.model_dump()
        }
        cluster_id = f"cl_{index:03d}"
        for member in members:
            member.cluster_id = cluster_id
        built.append(
            KeywordCluster(
                id=cluster_id,
                label=head.keyword,
                head_keyword=head.keyword,
                keywords=[m.keyword for m in members],
                intent=type(head.intent)(**totals),
                opportunity_score=round(
                    sum(m.score.opportunity_score for m in members) / len(members), 2
                ),
            )
        )
    built.sort(key=lambda c: -c.opportunity_score)
    return built


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_keyword(
    record: KeywordRecord,
    *,
    inputs: KeywordInputs,
    brand_page_tokens: dict[str, set[str]] | None = None,
    competitor_coverage: dict[str, int] | None = None,
    max_observed_impressions: int = 0,
) -> KeywordScoreBreakdown:
    """Score one keyword on SEO Engine's internal opportunity model.

    Dimensions with no data contribute 0 and are excluded from
    ``dimensions_with_observed_data``, so the UI can show *why* a score is what
    it is rather than implying every dimension was measured.
    """
    tokens = content_tokens(record.keyword)
    observed: list[str] = []

    # 1. Business relevance — overlap with what the brand actually sells.
    offering_tokens: set[str] = set()
    for offering in [*inputs.services, *inputs.products]:
        offering_tokens |= content_tokens(offering)
    relevance = 100.0 * jaccard(tokens, offering_tokens) if offering_tokens else 0.0
    if offering_tokens:
        observed.append("business_relevance")
        # A direct service-name match is worth more than token overlap suggests.
        for offering in [*inputs.services, *inputs.products]:
            if content_tokens(offering) and content_tokens(offering) <= tokens:
                relevance = max(relevance, 85.0)

    # 2. Intent value.
    intent_value = intent_commercial_value(record.intent)
    observed.append("intent_value")

    # 3. Demand — only from measured impressions.  Never estimated.
    demand = 0.0
    impressions = record.metric("impressions")
    if impressions and impressions.value is not None and max_observed_impressions > 0:
        demand = 100.0 * min(impressions.value / max_observed_impressions, 1.0)
        observed.append("demand")

    # 4. Ranking feasibility — from an observed position where we have one.
    feasibility = 0.0
    position = record.metric("position")
    if position and position.value is not None:
        # Positions 4-20 are the realistic movement band.
        if position.value <= 3:
            feasibility = 40.0
        elif position.value <= 20:
            feasibility = 100.0 - (position.value - 3) * 3.0
        else:
            feasibility = 25.0
        observed.append("ranking_feasibility")

    # 5. Competitive gap — competitors cover it and we do not.
    gap = 0.0
    if competitor_coverage:
        covering = competitor_coverage.get(record.normalised, 0)
        if covering:
            gap = min(100.0, 40.0 + 20.0 * covering)
            if record.mapped_url:
                gap *= 0.4
            observed.append("competitive_gap")

    # 6. Conversion potential — intent plus proximity to a commercial page.
    conversion = intent_value * 0.7
    if brand_page_tokens and record.mapped_url:
        conversion = min(100.0, conversion + 20.0)
    observed.append("conversion_potential")

    return KeywordScoreBreakdown(
        business_relevance=round(min(relevance, 100.0), 2),
        intent_value=round(intent_value, 2),
        demand=round(demand, 2),
        ranking_feasibility=round(feasibility, 2),
        competitive_gap=round(gap, 2),
        conversion_potential=round(min(conversion, 100.0), 2),
        dimensions_with_observed_data=observed,
    )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------
def map_to_pages(
    record: KeywordRecord, pages: dict[str, dict], *, minimum: float = 0.3
) -> tuple[str | None, float]:
    """Match a keyword to the page that already targets it, if any.

    ``pages`` maps URL to ``{"title": ..., "h1": ..., "text": ...}``.  Title and
    H1 matches count for more than body matches, because they state what the
    page is *for*.
    """
    tokens = content_tokens(record.keyword)
    if not tokens:
        return None, 0.0

    best_url, best_score = None, 0.0
    for url, page in pages.items():
        title_tokens = content_tokens(page.get("title") or "")
        h1_tokens = content_tokens(page.get("h1") or "")
        body_tokens = content_tokens(page.get("text") or "")

        score = (
            0.5 * jaccard(tokens, title_tokens)
            + 0.3 * jaccard(tokens, h1_tokens)
            + 0.2 * (len(tokens & body_tokens) / len(tokens))
        )
        if score > best_score:
            best_url, best_score = url, score

    if best_score < minimum:
        return None, round(best_score, 3)
    return best_url, round(best_score, 3)


def recommend_cluster_decision(
    cluster: KeywordCluster,
    *,
    mapped_urls: list[str],
    best_page_quality: float | None,
) -> ContentDecision:
    """Decide what to do about a cluster.

    Rule 13: existing assets before new ones. A cluster already served by a
    decent page is an UPDATE, not a CREATE, and several competing pages are a
    CONSOLIDATE.
    """
    if len(mapped_urls) > 1:
        return ContentDecision.CONSOLIDATE
    if mapped_urls:
        if best_page_quality is not None and best_page_quality >= 75:
            return ContentDecision.DO_NOTHING
        return ContentDecision.UPDATE
    if cluster.opportunity_score >= 40:
        return ContentDecision.CREATE
    return ContentDecision.DO_NOTHING


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def build_keyword_records(
    inputs: KeywordInputs,
    *,
    pages: dict[str, dict] | None = None,
    competitor_coverage: dict[str, int] | None = None,
    max_keywords: int = 500,
) -> list[KeywordRecord]:
    """Run seeds → expand → normalise → dedupe → intent → map → score."""
    seeds = generate_seeds(inputs)
    observed_map = {
        normalise(query): (query, impressions, clicks, position)
        for query, impressions, clicks, position in inputs.observed_queries
    }

    pairs = expand(seeds)
    pairs.extend((query, "observed") for query, _, _, _ in inputs.observed_queries)
    unique = deduplicate(pairs)[:max_keywords]

    location_terms = {loc.lower() for loc in inputs.locations}
    max_impressions = max(
        (impressions for _, impressions, _, _ in inputs.observed_queries), default=0
    )

    records: list[KeywordRecord] = []
    for keyword, source in unique:
        normalised = normalise(keyword)
        record = KeywordRecord(
            keyword=keyword,
            normalised=normalised,
            source=source,
            is_branded=any(term.lower() in normalised for term in inputs.brand_terms if term),
            is_local=any(term in normalised for term in location_terms),
            is_question=is_question(keyword),
            intent=classify_intent(
                keyword,
                brand_terms=inputs.brand_terms,
                location_terms=location_terms,
            ),
        )

        measured = observed_map.get(normalised)
        if measured:
            _, impressions, clicks, position = measured
            record.metrics = [
                KeywordMetric(
                    name="impressions",
                    value=float(impressions),
                    provenance=DataProvenance.OBSERVED,
                    source="google_search_console",
                ),
                KeywordMetric(
                    name="clicks",
                    value=float(clicks),
                    provenance=DataProvenance.OBSERVED,
                    source="google_search_console",
                ),
                KeywordMetric(
                    name="position",
                    value=float(position),
                    provenance=DataProvenance.OBSERVED,
                    source="google_search_console",
                ),
            ]
        else:
            # Explicitly unknown, so nothing downstream can mistake it for zero.
            record.metrics = [
                KeywordMetric(
                    name="search_volume",
                    value=None,
                    provenance=DataProvenance.UNKNOWN,
                    note=(
                        "No keyword data provider is connected, and this query was "
                        "not observed in Search Console."
                    ),
                )
            ]

        if pages:
            record.mapped_url, record.mapping_confidence = map_to_pages(record, pages)

        record.score = score_keyword(
            record,
            inputs=inputs,
            brand_page_tokens=None,
            competitor_coverage=competitor_coverage,
            max_observed_impressions=max_impressions,
        )
        records.append(record)

    records.sort(key=lambda r: -r.score.opportunity_score)
    return records


__all__ = [
    "EXPANSION_MODIFIERS",
    "STOPWORDS",
    "KeywordInputs",
    "build_keyword_records",
    "cluster_keywords",
    "content_tokens",
    "dedupe_key",
    "deduplicate",
    "expand",
    "generate_seeds",
    "jaccard",
    "map_to_pages",
    "normalise",
    "recommend_cluster_decision",
    "score_keyword",
]
