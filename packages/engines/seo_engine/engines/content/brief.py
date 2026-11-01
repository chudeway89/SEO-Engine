"""Content brief construction.

A brief is the contract the writer works to. It is assembled deterministically
from things the platform already knows — the cluster, the gap decision, the
brand graph, approved claims, existing pages — so the writer never has to invent
context, and every constraint on the writer is traceable to a source.

Sources are only listed as authoritative if the platform actually fetched them.
An unverified source is carried with ``verified=False`` and the writer is
instructed not to cite it.
"""

from __future__ import annotations

from seo_engine.engines.keywords.pipeline import content_tokens, jaccard
from seo_engine.schemas.content import ContentBrief, InternalLinkTarget
from seo_engine.schemas.enums import (
    HIGH_RISK_CATEGORIES,
    ContentAssetType,
    ContentDecision,
    RiskCategory,
    SearchIntent,
)
from seo_engine.schemas.evidence import SourceReference
from seo_engine.schemas.search import ContentGap, KeywordCluster, KeywordRecord

#: Sections every commercial page needs to be useful rather than merely present.
BASE_SECTIONS: dict[SearchIntent, list[str]] = {
    SearchIntent.INFORMATIONAL: [
        "What this covers and who it is for",
        "The direct answer, stated early",
        "How it works, step by step",
        "Common misunderstandings",
        "What to do next",
    ],
    SearchIntent.COMMERCIAL: [
        "What you are choosing between",
        "How the options genuinely differ",
        "What each option costs and what is included",
        "How to decide which fits your situation",
        "Next step",
    ],
    SearchIntent.TRANSACTIONAL: [
        "What you get",
        "What it costs",
        "How to book or order it",
        "What happens after you order",
        "Answers to the questions people ask before committing",
    ],
    SearchIntent.LOCAL: [
        "Where we are and how to reach us",
        "What is available at this location",
        "Opening times and appointment options",
        "How to get here",
        "Contact",
    ],
    SearchIntent.INVESTIGATIONAL: [
        "The short answer",
        "The evidence behind it",
        "Where the limits are",
        "How to judge your own situation",
        "What to do next",
    ],
    SearchIntent.NAVIGATIONAL: [
        "What this page is",
        "What you can do here",
        "Where to go next",
    ],
}


def build_brief(
    *,
    gap: ContentGap,
    cluster: KeywordCluster,
    keywords: list[KeywordRecord],
    brand_profile: dict,
    approved_claims: list[str],
    prohibited_claims: list[str],
    existing_pages: dict[str, dict] | None = None,
    sources: list[SourceReference] | None = None,
    questions: list[str] | None = None,
    evidence_ids: list[str] | None = None,
) -> ContentBrief:
    """Assemble the definitive brief for one topic."""
    primary = max(
        (k for k in keywords if k.cluster_id == cluster.id or k.keyword in cluster.keywords),
        key=lambda k: k.score.opportunity_score,
        default=None,
    )
    secondary = [
        k.keyword
        for k in keywords
        if k.keyword in cluster.keywords and (primary is None or k.keyword != primary.keyword)
    ][:12]

    intent = gap.intent if gap.intent.as_dict() else cluster.intent
    primary_intent = intent.primary
    intents = [
        SearchIntent(name)
        for name, weight in sorted(intent.as_dict().items(), key=lambda kv: -kv[1])
        if weight >= 0.15
    ] or [primary_intent]

    audience = _select_audience(brand_profile, intent)
    business_goal = _business_goal(brand_profile, gap)
    risk_category = RiskCategory(brand_profile.get("risk_category", RiskCategory.GENERAL))

    internal_links = _internal_links(cluster, existing_pages or {}, exclude=gap.target_url)

    verified_sources = [s for s in (sources or []) if s.verified]
    unverified = [s for s in (sources or []) if not s.verified]

    claims_to_verify: list[str] = []
    if unverified:
        claims_to_verify = [
            f"Any statement resting on {s.url}, which the platform did not fetch"
            for s in unverified[:5]
        ]

    prohibited = list(prohibited_claims)
    if risk_category in HIGH_RISK_CATEGORIES:
        prohibited.extend(
            [
                "Any guarantee of a clinical, financial or legal outcome",
                "Any comparative superiority claim without a cited source",
                "Any statistic that does not appear in an authoritative source listed here",
            ]
        )

    title = _title(cluster.label, primary_intent, brand_profile.get("name", ""))

    return ContentBrief(
        title=title,
        primary_topic=cluster.label,
        primary_keyword=primary.keyword if primary else cluster.head_keyword,
        secondary_keywords=secondary,
        search_intent=intents,
        audience=audience,
        business_goal=business_goal,
        unique_value_proposition=_value_proposition(brand_profile, gap, cluster),
        required_sections=_sections(primary_intent, gap),
        questions_to_answer=(questions or [])[:12],
        authoritative_sources=verified_sources,
        internal_links=internal_links,
        entities=_entities(brand_profile, cluster),
        claims_requiring_verification=claims_to_verify,
        prohibited_claims=prohibited,
        approved_claims=approved_claims,
        cta=_cta(primary_intent, brand_profile),
        content_type=_content_type(primary_intent),
        risk_category=risk_category,
        target_word_count=_word_count(gap, primary_intent),
        decision=gap.decision,
        target_url=gap.target_url,
        evidence_ids=list(evidence_ids or []) + list(gap.evidence_ids),
    )


# ---------------------------------------------------------------------------
def _select_audience(brand_profile: dict, intent) -> str:
    audiences = brand_profile.get("audiences") or []
    if not audiences:
        return (
            "Not specified in the brand profile. The writer must not assume an "
            "audience; write for a general reader with the stated need."
        )
    return audiences[0] if isinstance(audiences[0], str) else str(audiences[0])


def _business_goal(brand_profile: dict, gap: ContentGap) -> str:
    goals = brand_profile.get("goals") or []
    if goals:
        return goals[0] if isinstance(goals[0], str) else str(goals[0])
    return f"Support the brand's commercial objectives for {gap.topic}."


def _value_proposition(brand_profile: dict, gap: ContentGap, cluster: KeywordCluster) -> str:
    if gap.competitor_urls:
        return (
            f"Competitor pages already cover {cluster.label}. This page earns its place "
            "only by being more specific and more directly useful than they are: state "
            "the answer plainly, show the actual constraints, and be explicit about "
            "what the reader should do."
        )
    if gap.decision is ContentDecision.UPDATE:
        return (
            f"An existing page already ranks for {cluster.label} but is thin or dated. "
            "The update must add substance a reader can act on, not length."
        )
    return (
        f"Give a reader researching {cluster.label} a complete, accurate answer they can "
        "act on without needing another source."
    )


def _sections(intent: SearchIntent, gap: ContentGap) -> list[str]:
    sections = list(BASE_SECTIONS.get(intent, BASE_SECTIONS[SearchIntent.INFORMATIONAL]))
    if gap.decision is ContentDecision.CONSOLIDATE and gap.consolidate_urls:
        sections.insert(
            0,
            (
                "A single consolidated introduction that replaces the "
                f"{len(gap.consolidate_urls) + 1} competing pages"
            ),
        )
    return sections


def _internal_links(
    cluster: KeywordCluster, pages: dict[str, dict], *, exclude: str | None
) -> list[InternalLinkTarget]:
    """Pick genuinely related existing pages, never an arbitrary sample."""
    cluster_tokens: set[str] = set()
    for keyword in cluster.keywords or [cluster.head_keyword]:
        cluster_tokens |= content_tokens(keyword)

    scored: list[tuple[float, str, dict]] = []
    for url, page in pages.items():
        if exclude and url == exclude:
            continue
        page_tokens = content_tokens(page.get("title") or "") | content_tokens(page.get("h1") or "")
        overlap = jaccard(cluster_tokens, page_tokens)
        if overlap > 0.05:
            scored.append((overlap, url, page))
    scored.sort(key=lambda item: -item[0])

    return [
        InternalLinkTarget(
            url=url,
            anchor_text=(page.get("title") or url)[:80],
            reason=f"Related existing page (topic overlap {overlap:.0%}).",
        )
        for overlap, url, page in scored[:5]
    ]


def _entities(brand_profile: dict, cluster: KeywordCluster) -> list[str]:
    entities: list[str] = []
    if brand_profile.get("name"):
        entities.append(brand_profile["name"])
    entities.extend(brand_profile.get("services") or [])
    entities.extend(brand_profile.get("products") or [])
    entities.append(cluster.label)
    seen: set[str] = set()
    unique: list[str] = []
    for entity in entities:
        text = str(entity).strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            unique.append(text)
    return unique[:20]


def _cta(intent: SearchIntent, brand_profile: dict) -> str:
    name = brand_profile.get("name", "the team")
    return {
        SearchIntent.TRANSACTIONAL: f"Book directly with {name}.",
        SearchIntent.COMMERCIAL: f"Compare the options, then speak to {name}.",
        SearchIntent.LOCAL: f"Find your nearest {name} location and get in touch.",
        SearchIntent.INFORMATIONAL: (
            f"If this applies to your situation, {name} can talk it through with you."
        ),
        SearchIntent.INVESTIGATIONAL: f"Ask {name} about your specific circumstances.",
        SearchIntent.NAVIGATIONAL: f"Continue to the relevant {name} page.",
    }.get(intent, f"Get in touch with {name}.")


def _content_type(intent: SearchIntent) -> ContentAssetType:
    return {
        SearchIntent.TRANSACTIONAL: ContentAssetType.SERVICE_PAGE,
        SearchIntent.COMMERCIAL: ContentAssetType.GUIDE,
        SearchIntent.LOCAL: ContentAssetType.LOCATION_PAGE,
        SearchIntent.INFORMATIONAL: ContentAssetType.ARTICLE,
        SearchIntent.INVESTIGATIONAL: ContentAssetType.GUIDE,
        SearchIntent.NAVIGATIONAL: ContentAssetType.LANDING_PAGE,
    }.get(intent, ContentAssetType.ARTICLE)


def _word_count(gap: ContentGap, intent: SearchIntent) -> int:
    """Length follows the job, not a target.

    A transactional page that answers the question in 500 words is better than
    one padded to 2,000.
    """
    base = {
        SearchIntent.TRANSACTIONAL: 700,
        SearchIntent.LOCAL: 600,
        SearchIntent.NAVIGATIONAL: 400,
        SearchIntent.COMMERCIAL: 1200,
        SearchIntent.INFORMATIONAL: 1200,
        SearchIntent.INVESTIGATIONAL: 1400,
    }.get(intent, 1000)
    if gap.decision is ContentDecision.CONSOLIDATE:
        base = int(base * 1.4)
    return base


def _title(topic: str, intent: SearchIntent, brand: str) -> str:
    subject = topic.strip().capitalize()
    if intent is SearchIntent.TRANSACTIONAL:
        return f"{subject} — book with {brand}" if brand else subject
    if intent is SearchIntent.COMMERCIAL:
        return f"{subject}: how to choose"
    if intent is SearchIntent.LOCAL:
        return f"{subject} — locations and appointments"
    if intent is SearchIntent.INVESTIGATIONAL:
        return f"{subject}: what the evidence shows"
    return f"{subject}: a practical guide"


__all__ = ["BASE_SECTIONS", "build_brief"]
