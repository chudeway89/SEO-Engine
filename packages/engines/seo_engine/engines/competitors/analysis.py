"""Competitor and content-gap analysis.

Two principles from the specification shape this module:

* **A business competitor is not automatically a search competitor.** Types are
  tracked separately and only promoted on evidence — a competitor becomes a SERP
  competitor when it is *observed* in a SERP, not because someone listed it.
* **Rule 13: a keyword is not a reason to create a page.** Every gap resolves to
  exactly one of CREATE / UPDATE / CONSOLIDATE / REDIRECT / DO_NOTHING, and the
  reasoning is recorded as evidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from seo_engine.engines.keywords.pipeline import content_tokens, jaccard, normalise
from seo_engine.schemas.crawl import CrawlPage
from seo_engine.schemas.enums import CompetitorType, ContentDecision, DataProvenance
from seo_engine.schemas.search import (
    CompetitorProfile,
    ContentGap,
    IntentDistribution,
    KeywordCluster,
    KeywordGap,
    SERPSnapshot,
)

#: A page scoring at or above this is good enough that rewriting it is not the
#: highest-value action available.
GOOD_PAGE_QUALITY = 75.0

#: Below this, a page nominally covering a topic is not really covering it.
WEAK_PAGE_QUALITY = 45.0


@dataclass(slots=True)
class CompetitorPages:
    """Pages observed on one competitor domain."""

    domain: str
    pages: list[CrawlPage] = field(default_factory=list)

    def topics(self) -> dict[str, set[str]]:
        """URL → content tokens from the title and H1."""
        topics: dict[str, set[str]] = {}
        for page in self.pages:
            if not page.is_indexable:
                continue
            tokens = content_tokens(page.title or "") | content_tokens(
                page.h1s[0] if page.h1s else ""
            )
            if tokens:
                topics[page.url] = tokens
        return topics


def page_quality_score(page: CrawlPage) -> float:
    """A deterministic 0-100 quality proxy from observable page attributes.

    It is explicitly a proxy: it measures whether a page is *equipped* to serve
    an intent (title, heading, depth, structure, links, next step), not whether
    the prose is any good. The content evaluator judges that separately.
    """
    score = 0.0
    if page.title:
        score += 15
    if page.meta_description:
        score += 5
    if page.h1s:
        score += 10
    if len(page.headings) >= 4:
        score += 10
    if page.word_count >= 300:
        score += 15
    if page.word_count >= 900:
        score += 10
    if page.schema_blocks:
        score += 10
    if page.internal_links:
        score += 10
    if page.accessibility.forms_total or page.accessibility.buttons_total:
        score += 10
    if page.images and any(i.has_alt for i in page.images):
        score += 5
    return min(score, 100.0)


def classify_competitor_types(
    profile: CompetitorProfile,
    *,
    serp_snapshots: list[SERPSnapshot],
    brand_locations: list[str] | None = None,
) -> list[CompetitorType]:
    """Promote a competitor's types only on observed evidence."""
    types = set(profile.types) or {CompetitorType.BUSINESS}

    for snapshot in serp_snapshots:
        if not snapshot.available:
            continue
        for item in snapshot.results:
            if item.domain.lower().removeprefix("www.") != profile.domain:
                continue
            if item.result_type == "paid":
                types.add(CompetitorType.PAID)
            elif item.result_type in {"local_pack", "map"}:
                types.add(CompetitorType.LOCAL)
            else:
                types.add(CompetitorType.SERP)

    if profile.pages_analysed > 0:
        types.add(CompetitorType.CONTENT)

    return sorted(types, key=lambda t: t.value)


def keyword_gaps(
    *,
    brand_pages: dict[str, dict],
    competitors: dict[str, CompetitorPages],
    keywords: list[str],
) -> list[KeywordGap]:
    """Keywords competitors address on a page and the brand does not.

    Only *observed* competitor pages count. A competitor we could not crawl
    produces no gaps rather than assumed ones.
    """
    brand_topics = {
        url: content_tokens(page.get("title") or "") | content_tokens(page.get("h1") or "")
        for url, page in brand_pages.items()
    }

    gaps: list[KeywordGap] = []
    for keyword in keywords:
        tokens = content_tokens(keyword)
        if not tokens:
            continue

        brand_url, brand_score = None, 0.0
        for url, page_tokens in brand_topics.items():
            score = jaccard(tokens, page_tokens)
            if score > brand_score:
                brand_url, brand_score = url, score

        covering: list[str] = []
        for domain, competitor in competitors.items():
            for _url, page_tokens in competitor.topics().items():
                if jaccard(tokens, page_tokens) >= 0.34:
                    covering.append(domain)
                    break

        if covering and brand_score < 0.34:
            gaps.append(
                KeywordGap(
                    keyword=keyword,
                    competitor_domains=sorted(set(covering)),
                    brand_covers=False,
                    brand_url=brand_url if brand_score > 0 else None,
                    evidence_ref=f"observed on {len(set(covering))} competitor domain(s)",
                    opportunity_score=round(min(100.0, 40.0 + 20.0 * len(set(covering))), 2),
                )
            )
    return sorted(gaps, key=lambda g: -g.opportunity_score)


def analyse_content_gap(
    cluster: KeywordCluster,
    *,
    brand_pages: dict[str, CrawlPage],
    competitors: dict[str, CompetitorPages],
    serp_snapshot: SERPSnapshot | None = None,
    demand_signal: float | None = None,
    demand_provenance: DataProvenance = DataProvenance.UNKNOWN,
) -> ContentGap:
    """Decide the single correct action for one topic cluster.

    The decision order matters, and it is deliberately biased against creating
    new pages:

    1. several brand pages already compete for the topic → CONSOLIDATE;
    2. one page covers it well → DO_NOTHING;
    3. one page covers it weakly → UPDATE;
    4. nothing covers it, and there is a reason to → CREATE;
    5. otherwise → DO_NOTHING.
    """
    cluster_tokens: set[str] = set()
    for keyword in cluster.keywords:
        cluster_tokens |= content_tokens(keyword)

    matches: list[tuple[str, float, float]] = []
    for url, page in brand_pages.items():
        if not page.is_indexable:
            continue
        page_tokens = content_tokens(page.title or "") | content_tokens(
            page.h1s[0] if page.h1s else ""
        )
        overlap = jaccard(cluster_tokens, page_tokens)
        if overlap >= 0.25:
            matches.append((url, overlap, page_quality_score(page)))
    matches.sort(key=lambda m: (-m[1], -m[2]))

    competitor_urls: list[str] = []
    for competitor in competitors.values():
        for url, tokens in competitor.topics().items():
            if jaccard(cluster_tokens, tokens) >= 0.25:
                competitor_urls.append(url)

    serp_coverage = 0.0
    if serp_snapshot and serp_snapshot.available and serp_snapshot.results:
        competitor_domains = set(competitors)
        hits = sum(
            1
            for item in serp_snapshot.results
            if item.domain.lower().removeprefix("www.") in competitor_domains
        )
        serp_coverage = round(hits / len(serp_snapshot.results), 3)

    brand_coverage = round(matches[0][1], 3) if matches else 0.0
    best_quality = matches[0][2] if matches else None

    # --- the decision ---------------------------------------------------
    strong_matches = [m for m in matches if m[1] >= 0.45]
    if len(strong_matches) > 1:
        decision = ContentDecision.CONSOLIDATE
        reason = (
            f"{len(strong_matches)} existing pages target this topic and compete with "
            "each other. Consolidating into one authoritative page is worth more than "
            "adding another."
        )
        target = strong_matches[0][0]
        consolidate = [m[0] for m in strong_matches[1:]]
    elif matches and best_quality is not None and best_quality >= GOOD_PAGE_QUALITY:
        decision = ContentDecision.DO_NOTHING
        reason = (
            f"{matches[0][0]} already covers this topic and scores "
            f"{best_quality:.0f}/100 on structural quality. No content action is "
            "justified; effort is better spent elsewhere."
        )
        target, consolidate = matches[0][0], []
    elif matches:
        decision = ContentDecision.UPDATE
        reason = (
            f"{matches[0][0]} already targets this topic but scores "
            f"{best_quality:.0f}/100. Improving the existing page preserves its "
            "history and is lower risk than publishing a competing one."
        )
        target, consolidate = matches[0][0], []
    elif competitor_urls or serp_coverage > 0 or (demand_signal or 0) > 0:
        decision = ContentDecision.CREATE
        drivers = []
        if competitor_urls:
            drivers.append(f"{len(competitor_urls)} competitor page(s) cover it")
        if serp_coverage:
            drivers.append(f"competitors hold {serp_coverage:.0%} of the observed SERP")
        if demand_signal:
            drivers.append(f"measured demand signal of {demand_signal:.0f}")
        reason = (
            "No existing page addresses this topic, and there is a reason for one: "
            + "; ".join(drivers)
            + "."
        )
        target, consolidate = None, []
    else:
        decision = ContentDecision.DO_NOTHING
        reason = (
            "No existing page covers this topic, but there is no observed demand, no "
            "competitor coverage and no SERP evidence to justify creating one. A "
            "keyword alone is not a reason to publish."
        )
        target, consolidate = None, []

    confidence = 0.4
    if matches:
        confidence += 0.2
    if competitor_urls:
        confidence += 0.15
    if serp_snapshot and serp_snapshot.available:
        confidence += 0.15
    if demand_provenance is DataProvenance.OBSERVED:
        confidence += 0.1

    return ContentGap(
        topic=cluster.label,
        cluster_id=cluster.id,
        brand_coverage=brand_coverage,
        brand_urls=[m[0] for m in matches],
        competitor_coverage=round(min(1.0, len(competitor_urls) / 3), 3),
        competitor_urls=sorted(set(competitor_urls))[:20],
        serp_coverage=serp_coverage,
        demand_signal=demand_signal,
        demand_provenance=demand_provenance,
        intent=cluster.intent or IntentDistribution(),
        existing_page_quality=best_quality,
        decision=decision,
        decision_reason=reason,
        target_url=target,
        consolidate_urls=consolidate,
        confidence=round(min(confidence, 0.95), 2),
    )


def coverage_comparison(
    *, brand_pages: dict[str, CrawlPage], competitors: dict[str, CompetitorPages]
) -> dict:
    """Side-by-side topical coverage, from observed pages only."""
    brand_topics: set[str] = set()
    for page in brand_pages.values():
        brand_topics |= content_tokens(page.title or "")

    per_competitor: dict[str, dict] = {}
    for domain, competitor in competitors.items():
        topics: set[str] = set()
        for tokens in competitor.topics().values():
            topics |= tokens
        per_competitor[domain] = {
            "pages_observed": len(competitor.pages),
            "topic_terms": len(topics),
            "shared_with_brand": len(topics & brand_topics),
            "unique_to_competitor": sorted(topics - brand_topics)[:40],
        }

    return {
        "brand": {"pages_observed": len(brand_pages), "topic_terms": len(brand_topics)},
        "competitors": per_competitor,
        "note": (
            "Coverage is computed from pages this platform actually crawled. It is "
            "not an estimate of a competitor's full site."
        ),
    }


def discover_serp_competitors(
    snapshots: list[SERPSnapshot], *, brand_domain: str, minimum_appearances: int = 2
) -> list[CompetitorProfile]:
    """Find domains that repeatedly appear for the brand's own queries.

    Returns nothing when no SERP data was observed — it never guesses at who a
    competitor might be.
    """
    appearances: dict[str, int] = defaultdict(int)
    positions: dict[str, list[int]] = defaultdict(list)

    for snapshot in snapshots:
        if not snapshot.available:
            continue
        for item in snapshot.results:
            domain = item.domain.lower().removeprefix("www.")
            if domain == brand_domain.lower().removeprefix("www.") or item.result_type == "paid":
                continue
            appearances[domain] += 1
            positions[domain].append(item.position)

    profiles: list[CompetitorProfile] = []
    for domain, count in sorted(appearances.items(), key=lambda kv: -kv[1]):
        if count < minimum_appearances:
            continue
        average = sum(positions[domain]) / len(positions[domain])
        profiles.append(
            CompetitorProfile(
                name=domain,
                domain=domain,
                types=[CompetitorType.SERP],
                priority=1 if average <= 5 else 2 if average <= 10 else 3,
                discovered_via="serp_observation",
                notes=(
                    f"Observed {count} time(s) across the analysed SERPs at an average "
                    f"position of {average:.1f}."
                ),
            )
        )
    return profiles


def normalise_topic(text: str) -> str:
    return normalise(text)


__all__ = [
    "GOOD_PAGE_QUALITY",
    "WEAK_PAGE_QUALITY",
    "CompetitorPages",
    "analyse_content_gap",
    "classify_competitor_types",
    "coverage_comparison",
    "discover_serp_competitors",
    "keyword_gaps",
    "page_quality_score",
]
