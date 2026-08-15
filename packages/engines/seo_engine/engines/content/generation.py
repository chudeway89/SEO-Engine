"""Content generation, updating and repurposing.

Two paths, and the output always says which one produced it:

* **LLM path** — a model writes from the brief, with the brief's constraints in
  the developer channel and any external reference material in the untrusted
  channel.
* **Deterministic path** — used when no model is configured. It assembles a
  *structured outline* from the brief: real headings, the questions to answer,
  the approved claims, the internal links and the CTA. It does not write prose
  it cannot ground, and it says so in the draft. That is deliberately less
  useful than a written article, because a fabricated article would be worse
  than an honest outline.
"""

from __future__ import annotations

import re
from typing import Any

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.observability.logging import get_logger
from seo_engine.schemas.content import (
    REPURPOSE_PLATFORMS,
    ContentBrief,
    ContentDraft,
    ContentSection,
    ContentUpdatePlan,
    RepurposedAsset,
)
from seo_engine.schemas.crawl import CrawlPage
from seo_engine.schemas.enums import SynthesisMode
from seo_engine.shared.llm import (
    DeterministicFallbackRequired,
    LLMMessage,
    ModelGateway,
    get_gateway,
)

log = get_logger(__name__)

OUTLINE_NOTICE = (
    "This is a structured outline, not finished prose. No language model is "
    "configured, and SEO Engine will not generate article text it cannot ground in "
    "the brief. Every heading, question, claim and link below comes from the brief; "
    "a writer (or a configured model) supplies the prose."
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:80] or "untitled"


async def generate_draft(
    brief: ContentBrief,
    *,
    gateway: ModelGateway | None = None,
    reference_pages: list[CrawlPage] | None = None,
    brand_voice: dict[str, Any] | None = None,
) -> ContentDraft:
    """Produce a draft from a brief, by model where possible."""
    gateway = gateway or get_gateway()
    try:
        return await _generate_with_model(
            brief, gateway=gateway, reference_pages=reference_pages, brand_voice=brand_voice
        )
    except DeterministicFallbackRequired:
        log.info("content_generation_deterministic", topic=brief.primary_topic)
        return build_outline(brief)


async def _generate_with_model(
    brief: ContentBrief,
    *,
    gateway: ModelGateway,
    reference_pages: list[CrawlPage] | None,
    brand_voice: dict[str, Any] | None,
) -> ContentDraft:
    from seo_engine.shared.untrusted import wrap_external

    messages = [
        LLMMessage(
            role="system",
            channel="system",
            content=(
                "You are a specialist writer inside SEO Engine. Write for a person "
                "who has a real decision to make. Never state a statistic, price or "
                "credential that is not in the brief. If the brief does not support a "
                "claim, leave it out and note it. Never write filler to reach a word "
                "count. Do not narrate your own process."
            ),
        ),
        LLMMessage(
            role="system",
            channel="developer_policy",
            content=_constraints_block(brief, brand_voice or {}),
        ),
        LLMMessage(role="user", channel="user", content=_brief_block(brief)),
    ]

    for page in (reference_pages or [])[:3]:
        # Competitor copy is reference material and is fenced as untrusted.
        untrusted = wrap_external(
            page.text_content[:4000], source=page.url, source_type="competitor_page"
        )
        messages.append(
            LLMMessage(role="user", channel="external_content", content=untrusted.render())
        )

    response = await gateway.complete(
        messages,
        temperature=0.4,
        prompt_key="agents/content/writer",
        prompt_version="content-writer.v1",
    )
    return _parse_markdown(response.text, brief, synthesis_mode=SynthesisMode.LLM)


def _constraints_block(brief: ContentBrief, voice: dict[str, Any]) -> str:
    lines = [
        "Hard constraints for this piece:",
        f"- Risk category: {brief.risk_category.value}.",
    ]
    if brief.approved_claims:
        lines.append("- You may state these approved claims verbatim:")
        lines += [f"    - {claim}" for claim in brief.approved_claims]
    else:
        lines.append(
            "- No approved commercial claims are on record, so make none. Describe "
            "what the service is, not how good it is."
        )
    if brief.prohibited_claims:
        lines.append("- You must never state, imply or paraphrase:")
        lines += [f"    - {claim}" for claim in brief.prohibited_claims]
    if brief.authoritative_sources:
        lines.append("- You may cite only these verified sources:")
        lines += [f"    - {s.title or s.url} ({s.url})" for s in brief.authoritative_sources]
    else:
        lines.append("- No verified sources are available, so cite none. Do not invent any.")
    if voice.get("forbidden_terminology"):
        lines.append(f"- Never use: {', '.join(voice['forbidden_terminology'])}.")
    if voice.get("tone"):
        lines.append(f"- Brand tone: {voice['tone']}.")
    return "\n".join(lines)


def _brief_block(brief: ContentBrief) -> str:
    lines = [
        f"Write a {brief.content_type.value.replace('_', ' ')} titled: {brief.title}",
        f"Primary topic: {brief.primary_topic}",
        f"Primary keyword: {brief.primary_keyword or 'none specified'}",
        f"Audience: {brief.audience}",
        f"Business goal: {brief.business_goal}",
        f"Why this page should exist: {brief.unique_value_proposition}",
        f"Target length: about {brief.target_word_count} words — a floor for substance, "
        "not a target to pad towards.",
        "",
        "Required sections (use these as H2 headings, adapting the wording):",
    ]
    lines += [f"- {section}" for section in brief.required_sections]
    if brief.questions_to_answer:
        lines += ["", "Questions the reader needs answered:"]
        lines += [f"- {question}" for question in brief.questions_to_answer]
    if brief.internal_links:
        lines += ["", "Link to these existing pages where genuinely relevant:"]
        lines += [f"- {link.anchor_text} → {link.url}" for link in brief.internal_links]
    if brief.cta:
        lines += ["", f"Close with this call to action: {brief.cta}"]
    lines += [
        "",
        "Return markdown: an H1, then H2 sections. No preamble, no commentary.",
    ]
    return "\n".join(lines)


def build_outline(brief: ContentBrief) -> ContentDraft:
    """The deterministic path: a real outline, honestly labelled."""
    sections = [
        ContentSection(
            heading=heading,
            level=2,
            body=_section_guidance(heading, brief),
        )
        for heading in brief.required_sections
    ]

    if brief.questions_to_answer:
        sections.append(
            ContentSection(
                heading="Questions this page must answer",
                level=2,
                body="\n".join(f"- {q}" for q in brief.questions_to_answer),
            )
        )
    if brief.approved_claims:
        sections.append(
            ContentSection(
                heading="Approved claims available to the writer",
                level=2,
                body="\n".join(f"- {c}" for c in brief.approved_claims),
            )
        )
    if brief.prohibited_claims:
        sections.append(
            ContentSection(
                heading="Claims that must not appear",
                level=2,
                body="\n".join(f"- {c}" for c in brief.prohibited_claims),
            )
        )

    body_parts = [f"# {brief.title}", "", f"> {OUTLINE_NOTICE}", ""]
    for section in sections:
        body_parts += [f"## {section.heading}", "", section.body, ""]
    if brief.cta:
        body_parts += ["## Next step", "", brief.cta, ""]

    body = "\n".join(body_parts)
    return ContentDraft(
        title=brief.title,
        meta_description=_meta_description(brief),
        slug=slugify(brief.title),
        sections=sections,
        body_markdown=body,
        word_count=len(body.split()),
        internal_links=list(brief.internal_links),
        cited_sources=list(brief.authoritative_sources),
        entities=list(brief.entities),
        schema_recommendation=_schema_for(brief),
        cta=brief.cta,
        unverified_claims=list(brief.claims_requiring_verification),
        synthesis_mode=SynthesisMode.DETERMINISTIC.value,
    )


def _section_guidance(heading: str, brief: ContentBrief) -> str:
    relevant = [q for q in brief.questions_to_answer if content_tokens(q) & content_tokens(heading)]
    lines = [
        f"_Cover: {heading.lower()}, for {brief.audience}._",
    ]
    if relevant:
        lines.append("")
        lines += [f"- Answer: {q}" for q in relevant]
    return "\n".join(lines)


def _meta_description(brief: ContentBrief) -> str:
    text = f"{brief.primary_topic.capitalize()} — {brief.unique_value_proposition}"
    return text[:155].rsplit(" ", 1)[0] if len(text) > 155 else text


def _schema_for(brief: ContentBrief) -> dict[str, Any] | None:
    from seo_engine.schemas.enums import ContentAssetType

    mapping = {
        ContentAssetType.ARTICLE: "Article",
        ContentAssetType.GUIDE: "Article",
        ContentAssetType.FAQ: "FAQPage",
        ContentAssetType.SERVICE_PAGE: "Service",
        ContentAssetType.PRODUCT_PAGE: "Product",
        ContentAssetType.LOCATION_PAGE: "LocalBusiness",
    }
    schema_type = mapping.get(brief.content_type)
    if not schema_type:
        return None
    return {
        "@context": "https://schema.org",
        "@type": schema_type,
        "name": brief.title,
        "_note": (
            "Only publish this markup if the corresponding information is visible to "
            "a reader on the page."
        ),
    }


def _parse_markdown(
    text: str, brief: ContentBrief, *, synthesis_mode: SynthesisMode
) -> ContentDraft:
    lines = text.strip().splitlines()
    title = brief.title
    sections: list[ContentSection] = []
    current: ContentSection | None = None
    buffer: list[str] = []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip() or title
            continue
        if line.startswith("## "):
            if current is not None:
                current.body = "\n".join(buffer).strip()
                sections.append(current)
            current = ContentSection(heading=line[3:].strip(), level=2, body="")
            buffer = []
            continue
        buffer.append(line)
    if current is not None:
        current.body = "\n".join(buffer).strip()
        sections.append(current)

    used_links = [link for link in brief.internal_links if link.url in text]
    return ContentDraft(
        title=title,
        meta_description=_meta_description(brief),
        slug=slugify(title),
        sections=sections,
        body_markdown=text.strip(),
        word_count=len(text.split()),
        internal_links=used_links or list(brief.internal_links),
        cited_sources=[s for s in brief.authoritative_sources if s.url in text],
        entities=list(brief.entities),
        schema_recommendation=_schema_for(brief),
        cta=brief.cta,
        unverified_claims=list(brief.claims_requiring_verification),
        synthesis_mode=synthesis_mode.value,
    )


# ---------------------------------------------------------------------------
# Updating
# ---------------------------------------------------------------------------
def build_update_plan(
    page: CrawlPage,
    brief: ContentBrief,
    *,
    competitor_pages: list[CrawlPage] | None = None,
    evidence_ids: list[str] | None = None,
) -> ContentUpdatePlan:
    """Diff an existing page against what the brief says it should cover."""
    page_tokens = content_tokens(page.text_content)
    heading_text = " ".join(h.text for h in page.headings)
    heading_tokens = content_tokens(heading_text)

    missing_sections = [
        section
        for section in brief.required_sections
        if not (content_tokens(section) & heading_tokens)
    ]
    missing_questions = [
        question
        for question in brief.questions_to_answer
        if len(content_tokens(question) & page_tokens) < max(1, len(content_tokens(question)) // 2)
    ]

    outdated: list[str] = []
    years = re.findall(r"\b(20[12]\d)\b", page.text_content)
    if years:
        newest = max(int(y) for y in years)
        from datetime import date

        if newest < date.today().year - 1:
            outdated.append(
                f"The most recent year mentioned on the page is {newest}, which suggests "
                "the information has not been reviewed recently."
            )

    weak: list[str] = []
    if page.word_count < brief.target_word_count * 0.5:
        weak.append(
            f"The page has {page.word_count} words against a brief target of "
            f"{brief.target_word_count}; several briefed sections are likely absent."
        )
    if not page.h1s:
        weak.append("The page has no H1, so its subject is not stated structurally.")
    if not page.meta_description:
        weak.append("The page has no meta description.")

    unsupported = [
        claim
        for claim in brief.prohibited_claims
        if claim.lower()[:40] in page.text_content.lower()
    ]

    # Topics competitors address on the same subject that this page does not.
    competitor_topics: set[str] = set()
    for competitor in competitor_pages or []:
        competitor_topics |= content_tokens(competitor.title or "")
        for heading in competitor.headings:
            if heading.level == 2:
                competitor_topics |= content_tokens(heading.text)
    competitor_only = sorted(competitor_topics - page_tokens)[:15]
    if competitor_only:
        missing_questions.append(
            "Competitor pages on this subject cover terms this page does not: "
            + ", ".join(competitor_only)
        )

    metadata_changes: dict[str, str] = {}
    if not page.meta_description:
        metadata_changes["meta_description"] = _meta_description(brief)
    if page.title and len(page.title) > 60:
        metadata_changes["title"] = brief.title

    return ContentUpdatePlan(
        target_url=page.url,
        outdated_information=outdated,
        missing_information=missing_questions,
        weak_sections=weak,
        unsupported_claims=unsupported,
        sections_to_add=missing_sections,
        sections_to_rewrite=[h.text for h in page.headings if h.level == 2][:3]
        if page.word_count < brief.target_word_count * 0.5
        else [],
        internal_links_to_add=[
            link
            for link in brief.internal_links
            if link.url not in {link_.url for link_ in page.links}
        ],
        metadata_changes=metadata_changes,
        rationale=(
            f"The page already targets {brief.primary_topic}. Updating it preserves its "
            "existing history and internal links, which a new competing page would "
            "dilute."
        ),
        evidence_ids=list(evidence_ids or []),
    )


# ---------------------------------------------------------------------------
# Repurposing
# ---------------------------------------------------------------------------
PLATFORM_SPECS: dict[str, dict[str, str]] = {
    "linkedin": {
        "format": "post",
        "tone": "professional, first person, no hashtags spam",
        "objective": "start a conversation with decision makers",
    },
    "instagram": {
        "format": "caption",
        "tone": "direct, warm, visual-first",
        "objective": "reach a non-technical audience",
    },
    "facebook": {
        "format": "post",
        "tone": "plain and community-minded",
        "objective": "reach an existing local audience",
    },
    "x": {
        "format": "thread",
        "tone": "compressed, one idea per post",
        "objective": "reach practitioners quickly",
    },
    "youtube_script": {
        "format": "script",
        "tone": "spoken, second person",
        "objective": "explain the topic on camera",
    },
    "short_form_video_script": {
        "format": "script",
        "tone": "immediate, one hook",
        "objective": "answer one question in under a minute",
    },
    "email": {
        "format": "email",
        "tone": "personal and specific",
        "objective": "prompt a reply from an existing contact",
    },
    "newsletter": {
        "format": "newsletter section",
        "tone": "editorial",
        "objective": "keep subscribers informed",
    },
    "carousel": {
        "format": "slides",
        "tone": "one point per slide",
        "objective": "make the argument skimmable",
    },
    "faq": {
        "format": "question and answer",
        "tone": "plain",
        "objective": "answer the questions readers actually ask",
    },
    "press_angle": {
        "format": "pitch",
        "tone": "newsworthy and factual",
        "objective": "offer a journalist a story",
    },
    "sales_enablement": {
        "format": "one pager",
        "tone": "objection-handling",
        "objective": "equip the sales team",
    },
}


def repurpose(
    draft: ContentDraft,
    *,
    platforms: list[str],
    audience: str,
    canonical_url: str | None = None,
    canonical_asset_id: str | None = None,
) -> list[RepurposedAsset]:
    """Derive platform assets from the canonical piece.

    The canonical source stays identifiable on every derivative, and each one
    carries its own platform, audience, objective, format, tone and CTA.
    """
    assets: list[RepurposedAsset] = []
    key_points = [s.heading for s in draft.sections][:5]

    for platform in platforms:
        spec = PLATFORM_SPECS.get(platform)
        if spec is None:
            continue
        assets.append(
            RepurposedAsset(
                platform=platform,
                audience=audience,
                objective=spec["objective"],
                format=spec["format"],
                tone=spec["tone"],
                cta=draft.cta or "Read the full piece.",
                body=_derivative_body(platform, draft, key_points, canonical_url),
                canonical_source_url=canonical_url,
                canonical_content_asset_id=canonical_asset_id,
            )
        )
    return assets


def _derivative_body(
    platform: str, draft: ContentDraft, key_points: list[str], canonical_url: str | None
) -> str:
    header = f"Source: {draft.title}"
    if canonical_url:
        header += f" ({canonical_url})"

    if platform == "faq":
        return "\n\n".join(
            f"**{point}?**\n\n{_first_paragraph(draft, point)}" for point in key_points
        )
    if platform in {"x", "carousel"}:
        return "\n\n".join(f"{index + 1}. {point}" for index, point in enumerate(key_points))
    if platform in {"youtube_script", "short_form_video_script"}:
        return "\n".join(
            [
                f"HOOK: {draft.title}",
                *[f"BEAT {i + 1}: {point}" for i, point in enumerate(key_points)],
                f"CLOSE: {draft.cta or 'Get in touch.'}",
            ]
        )
    return "\n\n".join([header, *[f"- {point}" for point in key_points], draft.cta or ""]).strip()


def _first_paragraph(draft: ContentDraft, heading: str) -> str:
    for section in draft.sections:
        if section.heading == heading:
            return section.body.split("\n\n")[0][:400]
    return ""


def available_platforms() -> tuple[str, ...]:
    return REPURPOSE_PLATFORMS


__all__ = [
    "OUTLINE_NOTICE",
    "PLATFORM_SPECS",
    "available_platforms",
    "build_outline",
    "build_update_plan",
    "generate_draft",
    "repurpose",
    "slugify",
]
