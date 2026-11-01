"""Shared read helpers for agents.

Several agents need the same two things: the brand's facts in a compact form,
and the brand's crawled pages as :class:`PageFacts`. Loading them here, through
the domain services in the run context, keeps every agent on the same path —
tenant-scoped, permission-checked, never touching the database (Rule 4) — and
keeps the adaptation from ORM rows to engine inputs in one place.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from seo_engine.engines.keywords.intent import is_question
from seo_engine.engines.keywords.pipeline import content_tokens, normalise
from seo_engine.engines.seo.pages import PageFacts, from_page_row
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.content import ContentBrief, ContentEvaluation, EvaluationCriterionResult
from seo_engine.schemas.crawl import CrawlPage, Heading
from seo_engine.schemas.enums import DataProvenance, RiskCategory
from seo_engine.schemas.search import (
    IntentDistribution,
    KeywordCluster,
    KeywordRecord,
    KeywordScoreBreakdown,
    SERPSnapshot,
)
from seo_engine.shared.ids import utcnow


@dataclass(slots=True)
class BrandFacts:
    id: uuid.UUID
    name: str
    domain: str | None
    risk_category: RiskCategory
    services: list[tuple[str, list[str], str | None]] = field(default_factory=list)
    locations: list[tuple[str, str | None]] = field(default_factory=list)
    audiences: list[str] = field(default_factory=list)
    audience_questions: list[str] = field(default_factory=list)
    approved_claims: list[tuple[str, str | None]] = field(default_factory=list)
    prohibited_claims: list[str] = field(default_factory=list)
    forbidden_terms: list[str] = field(default_factory=list)
    voice: dict[str, Any] = field(default_factory=dict)
    goals: list[Any] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)

    @property
    def terms(self) -> set[str]:
        """Brand-name terms, for telling branded from non-branded demand."""
        terms = {self.name.lower()}
        terms |= {w.lower() for w in self.name.split() if len(w) > 3}
        if self.domain:
            terms.add(self.domain.split(".")[0].lower())
        return {t for t in terms if t}

    @property
    def location_terms(self) -> set[str]:
        return {name.lower() for name, _ in self.locations if name} | {
            city.lower() for _, city in self.locations if city
        }

    @property
    def priority_urls(self) -> dict[str, str]:
        urls = {url: name for name, _terms, url in self.services if url}
        return urls

    def brief_profile(self) -> dict[str, Any]:
        """The shape the content brief engine expects: plain strings throughout."""
        return {
            "name": self.name,
            "risk_category": self.risk_category.value,
            "services": [name for name, _terms, _url in self.services],
            "audiences": list(self.audiences),
            "goals": [g.description for g in self.goals],
            "voice": self.voice,
        }


def _domain(value: str | None) -> str | None:
    if not value:
        return None
    host = urlparse(value if "://" in value else f"https://{value}").netloc
    return host.lower().removeprefix("www.") or None


async def load_brand_facts(
    context: AgentContext, brand_id: uuid.UUID, *, website_domain: str | None = None
) -> BrandFacts:
    graph = await context.service("brands").profile(brand_id)
    brand = graph["brand"]
    voice = graph.get("voice")
    questions: list[str] = []
    for audience in graph.get("audiences", []):
        questions += [term for term in audience.vocabulary or [] if is_question(term)]
    return BrandFacts(
        id=brand.id,
        name=brand.name,
        domain=_domain(website_domain) or _domain(brand.website),
        risk_category=RiskCategory(brand.risk_category or RiskCategory.GENERAL),
        services=[(s.name, list(s.keywords or []), s.landing_url) for s in graph["services"]],
        locations=[(loc.name, loc.city) for loc in graph["locations"]],
        audiences=[a.name for a in graph["audiences"]],
        audience_questions=questions,
        approved_claims=[(c.claim, c.source) for c in graph["claims"]],
        prohibited_claims=[c.claim for c in graph["prohibited_claims"]],
        forbidden_terms=list(voice.forbidden_terminology or []) if voice else [],
        voice=(
            {
                "tone": voice.tone,
                "approved_terminology": list(voice.approved_terminology or []),
                "forbidden_terminology": list(voice.forbidden_terminology or []),
                "style_rules": list(voice.style_rules or []),
            }
            if voice
            else {}
        ),
        goals=list(graph["goals"]),
        competitors=[c.domain for c in graph["competitors"]],
        profile=dict(brand.profile or {}),
    )


async def load_page_facts(
    context: AgentContext,
    website_id: uuid.UUID | None,
    *,
    limit: int = 500,
    with_schema: bool = False,
) -> list[PageFacts]:
    if website_id is None:
        return []
    websites = context.service("websites")
    schema: dict[str, list[str]] = (
        await websites.schema_types_by_page(website_id) if with_schema else {}
    )
    rows = await websites.list_pages(website_id, limit=limit)
    return [from_page_row(row, schema_types=schema.get(row.url)) for row in rows]


async def website_domain(context: AgentContext, website_id: uuid.UUID | None) -> str | None:
    if website_id is None:
        return None
    website = await context.service("websites").get_website(website_id)
    return website.domain


def snapshots_provenance(snapshots: list[SERPSnapshot]) -> DataProvenance:
    """The weakest provenance across a set of SERPs: one synthetic page taints the set."""
    if not snapshots:
        return DataProvenance.UNKNOWN
    if any(s.provenance is DataProvenance.SYNTHETIC_DEMO for s in snapshots):
        return DataProvenance.SYNTHETIC_DEMO
    if all(s.provenance is DataProvenance.OBSERVED for s in snapshots):
        return DataProvenance.OBSERVED
    return DataProvenance.UNKNOWN


def keyword_record(row: Any) -> KeywordRecord:
    """Rebuild a keyword contract from a stored row, score breakdown included."""
    return KeywordRecord(
        keyword=row.keyword,
        normalised=row.normalised,
        language=row.language or "en",
        country=row.country or None,
        is_branded=row.is_branded,
        is_local=row.is_local,
        is_question=row.is_question,
        source=row.source or "seed",
        intent=IntentDistribution(**(row.intent or {})),
        score=KeywordScoreBreakdown.model_validate(row.score_breakdown or {}),
        mapped_url=row.mapped_url,
        mapping_confidence=row.mapping_confidence or 0.0,
        cluster_id=str(row.cluster_id) if row.cluster_id else None,
    )


async def cluster_for_topic(
    context: AgentContext,
    brand_id: uuid.UUID,
    *,
    topic: str,
    cluster_id: str | None = None,
) -> tuple[KeywordCluster | None, list[KeywordRecord]]:
    """The stored cluster a topic belongs to, with its keywords.

    Matched by id when one is given, otherwise by the cluster whose label or
    head keyword shares the most terms with the topic. Returns ``(None, [])``
    when nothing matches; callers report that rather than invent a cluster.
    """
    search = context.service("search")
    rows = await search.list_clusters(brand_id, limit=500)
    chosen = next((r for r in rows if cluster_id and str(r.id) == cluster_id), None)
    if chosen is None:
        tokens = content_tokens(topic)
        best = 0.0
        for row in rows:
            terms = content_tokens(row.label) | content_tokens(row.head_keyword)
            overlap = len(tokens & terms) / len(tokens) if tokens else 0.0
            if normalise(row.label) == normalise(topic):
                overlap = 2.0
            if overlap > best:
                chosen, best = row, overlap
        if best < 0.5:
            chosen = None
    if chosen is None:
        return None, []
    keywords = [
        keyword_record(k)
        for k in await search.list_keywords(brand_id, limit=2000)
        if k.cluster_id == chosen.id
    ]
    cluster = KeywordCluster(
        id=str(chosen.id),
        label=chosen.label,
        head_keyword=chosen.head_keyword,
        keywords=[k.keyword for k in keywords] or [chosen.head_keyword],
        intent=IntentDistribution(**(chosen.intent or {})),
        opportunity_score=chosen.opportunity_score,
        mapped_urls=list(chosen.mapped_urls or []),
        coverage=chosen.coverage or 0.0,
    )
    return cluster, keywords


def crawl_page_from_row(row: Any) -> CrawlPage:
    """A stored page as the content engines' ``CrawlPage`` (copy is untrusted data)."""
    headings = [
        Heading(level=int(h.get("level", 2)), text=str(h.get("text", "")))
        for h in (row.headings or [])
        if isinstance(h, dict) and h.get("text") and 1 <= int(h.get("level", 2)) <= 6
    ]
    if row.h1 and not any(h.level == 1 for h in headings):
        headings.insert(0, Heading(level=1, text=row.h1))
    return CrawlPage(
        url=row.url,
        status_code=row.status_code,
        title=row.title,
        meta_description=row.meta_description,
        canonical_url=row.canonical_url,
        meta_robots=row.meta_robots or [],
        headings=headings,
        word_count=row.word_count,
        content_hash=row.content_hash,
        text_content=(row.text_content or "")[:20_000],
        fetched_at=row.last_crawled_at or utcnow(),
    )


async def resolve_assets(
    context: AgentContext,
    brand_id: uuid.UUID,
    asset_ids: list[str] | list[uuid.UUID],
    *,
    statuses: set[str],
    limit: int = 10,
) -> list[Any]:
    """The content assets a content agent should act on.

    Explicit ids win (an asset outside ``statuses`` is still returned so the
    agent can say why it skipped it); otherwise the brand's most recent assets
    in one of ``statuses``.
    """
    content = context.service("content")
    if asset_ids:
        return [await content.get_asset(uuid.UUID(str(a))) for a in asset_ids][:limit]
    rows = await content.list_assets(brand_id, limit=200)
    return [a for a in rows if a.status in statuses][:limit]


async def brief_for_version(context: AgentContext, asset: Any, version: Any) -> ContentBrief | None:
    """The brief a version was written against, or ``None`` if none is recorded."""
    content = context.service("content")
    if version is not None and version.brief_id:
        return content.brief_contract(await content.get_brief(version.brief_id))
    for record in await content.list_briefs(asset.brand_id, limit=200):
        if record.content_asset_id == asset.id:
            return content.brief_contract(record)
    return None


def evaluation_contract(record: Any) -> ContentEvaluation:
    """Rehydrate a stored evaluation row."""
    warnings = list(record.warnings or [])
    return ContentEvaluation(
        criteria=[EvaluationCriterionResult.model_validate(c) for c in record.criteria or []],
        overall_score=record.overall_score,
        passed=record.passed,
        blocking_failures=list(record.blocking_failures or []),
        warnings=warnings,
        keyword_stuffing_detected=any("stuffing" in w.lower() for w in warnings),
        requires_human_review=record.requires_human_review,
    )


SYNTHETIC_SERP_LIMITATION = (
    "The SERP integration is running its development adapter: every results page "
    "used here is synthetic (*.example domains), not an observation of a real "
    "search engine. Findings that depend on it are labelled synthetic and must not "
    "be read as facts about the market."
)


__all__ = [
    "SYNTHETIC_SERP_LIMITATION",
    "BrandFacts",
    "brief_for_version",
    "cluster_for_topic",
    "crawl_page_from_row",
    "evaluation_contract",
    "keyword_record",
    "load_brand_facts",
    "load_page_facts",
    "resolve_assets",
    "snapshots_provenance",
    "website_domain",
]
