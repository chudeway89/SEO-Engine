"""Deterministic technical and on-page SEO checks.

Rule 11: deterministic problems get deterministic code.  Not one of these checks
consults a model — they are rules over observed crawl data, so they are
reproducible, explainable and testable.  An LLM's job is to *interpret* these
findings, never to detect them.

Every check declares the dimension it scores, so an issue always lands in a
named dimension rather than an opaque total.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from seo_engine.schemas.crawl import CrawlPage, CrawlResult
from seo_engine.schemas.enums import IssueSeverity, SEODimension
from seo_engine.schemas.seo import SEOIssue

# --- thresholds -------------------------------------------------------------
TITLE_MIN_LENGTH = 15
TITLE_MAX_LENGTH = 60
META_DESCRIPTION_MIN_LENGTH = 70
META_DESCRIPTION_MAX_LENGTH = 160
THIN_CONTENT_WORDS = 300
MAX_REDIRECT_HOPS = 2


@dataclass(slots=True)
class CheckContext:
    """Everything the checks need, computed once."""

    result: CrawlResult
    pages: list[CrawlPage]
    by_url: dict[str, CrawlPage]
    status_by_url: dict[str, int | None]
    sitemap_urls: set[str]
    inbound_links: dict[str, int]
    start_url: str

    @classmethod
    def build(cls, result: CrawlResult) -> CheckContext:
        pages = [p for p in result.pages if not p.error]
        by_url = {p.url.rstrip("/") or "/": p for p in pages}
        status = {p.url.rstrip("/") or "/": p.status_code for p in result.pages}

        inbound: dict[str, int] = defaultdict(int)
        for page in pages:
            for link in page.internal_links:
                inbound[link.url.rstrip("/") or "/"] += 1

        return cls(
            result=result,
            pages=pages,
            by_url=by_url,
            status_by_url=status,
            sitemap_urls={e.loc.rstrip("/") or "/" for e in result.sitemap.entries},
            inbound_links=dict(inbound),
            start_url=result.start_url.rstrip("/") or "/",
        )


CheckFn = Any  # Callable[[CheckContext], list[SEOIssue]]
_REGISTRY: list[tuple[str, CheckFn]] = []


def check(check_id: str):
    """Register a check function under a stable id."""

    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY.append((check_id, fn))
        return fn

    return decorator


def _issue(
    check_id: str,
    title: str,
    severity: IssueSeverity,
    dimension: SEODimension,
    *,
    url: str | None = None,
    detail: str = "",
    recommendation: str = "",
    data: dict[str, Any] | None = None,
    affected: list[str] | None = None,
) -> SEOIssue:
    return SEOIssue(
        check_id=check_id,
        title=title,
        severity=severity,
        dimension=dimension,
        url=url,
        detail=detail,
        recommendation=recommendation,
        evidence_data=data or {},
        affected_urls=affected or [],
    )


def _indexable(page: CrawlPage) -> bool:
    return page.is_indexable and not page.is_redirect


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------
@check("missing_title")
def missing_title(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_title",
            "Page has no title element",
            IssueSeverity.CRITICAL,
            SEODimension.SEARCH_ALIGNMENT,
            url=page.url,
            detail=(
                "Without a <title>, Google generates the title link from other "
                "on-page signals, which rarely matches the page's commercial intent."
            ),
            recommendation="Add a descriptive, unique <title> that names the page's subject.",
        )
        for page in ctx.pages
        if _indexable(page) and not (page.title or "").strip()
    ]


@check("duplicate_title")
def duplicate_title(ctx: CheckContext) -> list[SEOIssue]:
    groups: dict[str, list[str]] = defaultdict(list)
    for page in ctx.pages:
        if _indexable(page) and page.title:
            groups[page.title.strip().lower()].append(page.url)
    return [
        _issue(
            "duplicate_title",
            "Multiple pages share the same title",
            IssueSeverity.HIGH,
            SEODimension.SEARCH_ALIGNMENT,
            url=urls[0],
            detail=f"{len(urls)} pages use the title {title!r}.",
            recommendation=(
                "Differentiate the titles, or consolidate the pages if they serve the same intent."
            ),
            data={"title": title, "count": len(urls)},
            affected=urls,
        )
        for title, urls in groups.items()
        if len(urls) > 1
    ]


@check("title_length")
def title_length(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        if not _indexable(page) or not page.title:
            continue
        length = len(page.title)
        if length < TITLE_MIN_LENGTH:
            issues.append(
                _issue(
                    "title_length",
                    "Title is very short",
                    IssueSeverity.MEDIUM,
                    SEODimension.SEARCH_ALIGNMENT,
                    url=page.url,
                    detail=f"The title is {length} characters.",
                    recommendation="Expand the title to describe the page's subject and value.",
                    data={"length": length, "title": page.title},
                )
            )
        elif length > TITLE_MAX_LENGTH:
            issues.append(
                _issue(
                    "title_length",
                    "Title is likely to be truncated",
                    IssueSeverity.LOW,
                    SEODimension.SEARCH_ALIGNMENT,
                    url=page.url,
                    detail=(
                        f"The title is {length} characters; the meaningful part may be "
                        "cut off in the search result."
                    ),
                    recommendation="Lead with the distinctive words and shorten the tail.",
                    data={"length": length, "title": page.title},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Meta descriptions
# ---------------------------------------------------------------------------
@check("missing_meta_description")
def missing_meta_description(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_meta_description",
            "Page has no meta description",
            IssueSeverity.MEDIUM,
            SEODimension.SEARCH_ALIGNMENT,
            url=page.url,
            detail="Google will compose a snippet from the page body instead.",
            recommendation="Write a description that states what the page offers the reader.",
        )
        for page in ctx.pages
        if _indexable(page) and not (page.meta_description or "").strip()
    ]


@check("duplicate_meta_description")
def duplicate_meta_description(ctx: CheckContext) -> list[SEOIssue]:
    groups: dict[str, list[str]] = defaultdict(list)
    for page in ctx.pages:
        if _indexable(page) and page.meta_description:
            groups[page.meta_description.strip().lower()].append(page.url)
    return [
        _issue(
            "duplicate_meta_description",
            "Multiple pages share the same meta description",
            IssueSeverity.LOW,
            SEODimension.SEARCH_ALIGNMENT,
            url=urls[0],
            detail=f"{len(urls)} pages use an identical description.",
            recommendation="Write a distinct description per page, or consolidate the pages.",
            data={"count": len(urls)},
            affected=urls,
        )
        for urls in groups.values()
        if len(urls) > 1
    ]


@check("meta_description_length")
def meta_description_length(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        if not _indexable(page) or not page.meta_description:
            continue
        length = len(page.meta_description)
        if length > META_DESCRIPTION_MAX_LENGTH:
            issues.append(
                _issue(
                    "meta_description_length",
                    "Meta description is likely to be truncated",
                    IssueSeverity.LOW,
                    SEODimension.SEARCH_ALIGNMENT,
                    url=page.url,
                    detail=f"The description is {length} characters.",
                    recommendation="Put the key proposition in the first 120 characters.",
                    data={"length": length},
                )
            )
        elif length < META_DESCRIPTION_MIN_LENGTH:
            issues.append(
                _issue(
                    "meta_description_length",
                    "Meta description is very short",
                    IssueSeverity.INFO,
                    SEODimension.SEARCH_ALIGNMENT,
                    url=page.url,
                    detail=f"The description is {length} characters.",
                    recommendation="Use the available space to state the page's value.",
                    data={"length": length},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------
@check("missing_h1")
def missing_h1(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_h1",
            "Page has no H1",
            IssueSeverity.MEDIUM,
            SEODimension.CONTENT_QUALITY,
            url=page.url,
            detail="No top-level heading states what the page is about.",
            recommendation="Add a single H1 that names the page's subject.",
        )
        for page in ctx.pages
        if _indexable(page) and not page.h1s
    ]


@check("multiple_h1")
def multiple_h1(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "multiple_h1",
            "Page has more than one H1",
            IssueSeverity.LOW,
            SEODimension.CONTENT_QUALITY,
            url=page.url,
            detail=f"{len(page.h1s)} H1 elements were found.",
            recommendation="Keep one H1 and demote the rest to H2.",
            data={"h1s": page.h1s[:10]},
        )
        for page in ctx.pages
        if _indexable(page) and len(page.h1s) > 1
    ]


@check("heading_order")
def heading_order(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "heading_order",
            "Heading levels skip a level",
            IssueSeverity.LOW,
            SEODimension.AI_SEARCH_READINESS,
            url=page.url,
            detail=(
                "A heading jumps more than one level, which weakens the document "
                "outline that both assistive technology and extraction systems rely on."
            ),
            recommendation="Use heading levels sequentially.",
        )
        for page in ctx.pages
        if _indexable(page) and not page.accessibility.heading_order_valid
    ]


# ---------------------------------------------------------------------------
# Canonicals and indexability
# ---------------------------------------------------------------------------
@check("missing_canonical")
def missing_canonical(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_canonical",
            "Page declares no canonical URL",
            IssueSeverity.LOW,
            SEODimension.INDEXABILITY,
            url=page.url,
            detail="Without a canonical, duplicate URL variants may compete.",
            recommendation="Add a self-referencing canonical link.",
        )
        for page in ctx.pages
        if _indexable(page) and not page.canonical_url
    ]


@check("canonical_mismatch")
def canonical_mismatch(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        if not page.canonical_url or page.is_redirect:
            continue
        current = (page.final_url or page.url).rstrip("/") or "/"
        canonical = page.canonical_url.rstrip("/") or "/"
        if canonical == current:
            continue
        target = ctx.by_url.get(canonical)
        detail = f"The page points its canonical at {page.canonical_url}."
        severity = IssueSeverity.MEDIUM
        if target is not None and not target.is_indexable:
            detail += " That target is itself non-indexable, so neither URL can rank."
            severity = IssueSeverity.HIGH
        issues.append(
            _issue(
                "canonical_mismatch",
                "Canonical points to a different URL",
                severity,
                SEODimension.INDEXABILITY,
                url=page.url,
                detail=detail,
                recommendation=(
                    "Confirm this page is a genuine duplicate. If it is not, "
                    "make the canonical self-referencing."
                ),
                data={"canonical": page.canonical_url},
            )
        )
    return issues


@check("noindex")
def noindex(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        directives = {*page.meta_robots, *page.x_robots_tag}
        if "noindex" in directives or "none" in directives:
            source = "X-Robots-Tag header" if "noindex" in page.x_robots_tag else "meta robots tag"
            issues.append(
                _issue(
                    "noindex",
                    "Page is excluded from the index",
                    IssueSeverity.HIGH,
                    SEODimension.INDEXABILITY,
                    url=page.url,
                    detail=f"A noindex directive was found in the {source}.",
                    recommendation=(
                        "Remove the directive if this page should rank; otherwise "
                        "confirm the exclusion is intentional."
                    ),
                    data={"directives": sorted(directives), "source": source},
                )
            )
    return issues


@check("nofollow_internal_links")
def nofollow_internal_links(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        nofollowed = [link.url for link in page.internal_links if link.is_nofollow]
        if nofollowed:
            issues.append(
                _issue(
                    "nofollow_internal_links",
                    "Internal links are marked nofollow",
                    IssueSeverity.LOW,
                    SEODimension.INTERNAL_LINKING,
                    url=page.url,
                    detail=f"{len(nofollowed)} internal link(s) carry rel=nofollow.",
                    recommendation="Remove nofollow from internal links you want crawled.",
                    data={"links": nofollowed[:20]},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Status codes, redirects and links
# ---------------------------------------------------------------------------
@check("http_4xx")
def http_4xx(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "http_4xx",
            f"URL returns {page.status_code}",
            IssueSeverity.HIGH,
            SEODimension.TECHNICAL_HEALTH,
            url=page.url,
            detail=f"The URL responded {page.status_code}.",
            recommendation="Restore the page, or redirect the URL to its closest equivalent.",
            data={"status_code": page.status_code},
        )
        for page in ctx.result.pages
        if page.status_code and 400 <= page.status_code < 500
    ]


@check("http_5xx")
def http_5xx(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "http_5xx",
            f"URL returns {page.status_code}",
            IssueSeverity.CRITICAL,
            SEODimension.TECHNICAL_HEALTH,
            url=page.url,
            detail=f"The server responded {page.status_code}.",
            recommendation="Investigate the server error; crawlers back off from 5xx responses.",
            data={"status_code": page.status_code},
        )
        for page in ctx.result.pages
        if page.status_code and page.status_code >= 500
    ]


@check("fetch_error")
def fetch_error(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "fetch_error",
            "URL could not be fetched",
            IssueSeverity.HIGH,
            SEODimension.TECHNICAL_HEALTH,
            url=page.url,
            detail=page.error or "The request failed.",
            recommendation="Check DNS, TLS and server availability for this URL.",
        )
        for page in ctx.result.pages
        if page.error
    ]


@check("broken_internal_link")
def broken_internal_link(ctx: CheckContext) -> list[SEOIssue]:
    """Only reports targets we actually fetched — never guesses."""
    broken: dict[str, list[str]] = defaultdict(list)
    for page in ctx.pages:
        for link in page.internal_links:
            key = link.url.rstrip("/") or "/"
            status = ctx.status_by_url.get(key)
            if status is not None and status >= 400:
                broken[link.url].append(page.url)
    return [
        _issue(
            "broken_internal_link",
            "Internal link points to a broken URL",
            IssueSeverity.HIGH,
            SEODimension.INTERNAL_LINKING,
            url=target,
            detail=(
                f"{len(sources)} page(s) link to {target}, which returned "
                f"{ctx.status_by_url.get(target.rstrip('/') or '/')}."
            ),
            recommendation="Update or remove the link.",
            data={"status_code": ctx.status_by_url.get(target.rstrip("/") or "/")},
            affected=sources[:50],
        )
        for target, sources in broken.items()
    ]


@check("redirect_chain")
def redirect_chain(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "redirect_chain",
            "URL redirects more than once before resolving",
            IssueSeverity.MEDIUM,
            SEODimension.TECHNICAL_HEALTH,
            url=page.url,
            detail=f"The chain has {len(page.redirect_chain)} hop(s): "
            + " → ".join([*page.redirect_chain, page.final_url or page.url]),
            recommendation="Point the first URL directly at the final destination.",
            data={"hops": len(page.redirect_chain), "chain": page.redirect_chain},
        )
        for page in ctx.result.pages
        if len(page.redirect_chain) > MAX_REDIRECT_HOPS
    ]


@check("orphan_page")
def orphan_page(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        key = page.url.rstrip("/") or "/"
        if key == ctx.start_url or not _indexable(page):
            continue
        if ctx.inbound_links.get(key, 0) == 0:
            in_sitemap = key in ctx.sitemap_urls
            issues.append(
                _issue(
                    "orphan_page",
                    "Page has no internal links pointing to it",
                    IssueSeverity.MEDIUM if in_sitemap else IssueSeverity.HIGH,
                    SEODimension.INTERNAL_LINKING,
                    url=page.url,
                    detail=(
                        "The page was discovered "
                        + ("via the sitemap only." if in_sitemap else "but nothing links to it.")
                    ),
                    recommendation="Link to it from a relevant parent or hub page.",
                    data={"in_sitemap": in_sitemap},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------
@check("thin_content")
def thin_content(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "thin_content",
            "Page has very little content",
            IssueSeverity.MEDIUM,
            SEODimension.CONTENT_QUALITY,
            url=page.url,
            detail=f"The page has {page.word_count} words of body text.",
            recommendation=(
                "Either give the page substantive, useful information or "
                "consolidate it into a stronger page. Do not pad it."
            ),
            data={"word_count": page.word_count},
        )
        for page in ctx.pages
        if _indexable(page) and 0 < page.word_count < THIN_CONTENT_WORDS
    ]


@check("empty_page")
def empty_page(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "empty_page",
            "Page has no extractable text",
            IssueSeverity.HIGH,
            SEODimension.CONTENT_QUALITY,
            url=page.url,
            detail=(
                "No body text was extracted. "
                + (
                    "The page has several scripts and almost no markup text, which "
                    "suggests its content is rendered by JavaScript."
                    if page.accessibility.rendered_by_javascript
                    else "The page may be genuinely empty."
                )
            ),
            recommendation=(
                "Serve the primary content in the initial HTML response so it can "
                "be crawled and extracted reliably."
            ),
            data={"javascript_dependent": page.accessibility.rendered_by_javascript},
        )
        for page in ctx.pages
        if _indexable(page) and page.word_count == 0
    ]


@check("duplicate_content")
def duplicate_content(ctx: CheckContext) -> list[SEOIssue]:
    groups: dict[str, list[str]] = defaultdict(list)
    for page in ctx.pages:
        if _indexable(page) and page.word_count > 50:
            groups[page.content_hash].append(page.url)
    return [
        _issue(
            "duplicate_content",
            "Pages have identical body content",
            IssueSeverity.HIGH,
            SEODimension.CONTENT_QUALITY,
            url=urls[0],
            detail=f"{len(urls)} URLs return byte-identical body text.",
            recommendation=(
                "Consolidate them into one page and redirect the rest, or "
                "canonicalise to the preferred URL."
            ),
            data={"count": len(urls)},
            affected=urls,
        )
        for urls in groups.values()
        if len(urls) > 1
    ]


@check("missing_image_alt")
def missing_image_alt(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        missing = [i.src for i in page.images if i.alt is None]
        if missing:
            issues.append(
                _issue(
                    "missing_image_alt",
                    "Images have no alt attribute",
                    IssueSeverity.MEDIUM,
                    SEODimension.AI_SEARCH_READINESS,
                    url=page.url,
                    detail=(
                        f"{len(missing)} of {len(page.images)} images have no alt "
                        'attribute at all. (An empty alt="" is a valid declaration '
                        "for decorative images and is not counted here.)"
                    ),
                    recommendation='Describe informative images; use alt="" for decorative ones.',
                    data={"missing": missing[:20], "total_images": len(page.images)},
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Structured data, hreflang, protocol
# ---------------------------------------------------------------------------
@check("invalid_structured_data")
def invalid_structured_data(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        broken = [b for b in page.schema_blocks if b.get("_parse_error")]
        if broken:
            issues.append(
                _issue(
                    "invalid_structured_data",
                    "Structured data could not be parsed",
                    IssueSeverity.MEDIUM,
                    SEODimension.STRUCTURED_DATA,
                    url=page.url,
                    detail="; ".join(str(b["_parse_error"]) for b in broken[:5]),
                    recommendation="Fix the JSON-LD so it parses; invalid blocks are ignored.",
                    data={"errors": [b.get("_parse_error") for b in broken[:5]]},
                )
            )
    return issues


@check("missing_structured_data")
def missing_structured_data(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_structured_data",
            "Page has no structured data",
            IssueSeverity.LOW,
            SEODimension.STRUCTURED_DATA,
            url=page.url,
            detail="No JSON-LD or microdata was found.",
            recommendation=(
                "Add structured data that genuinely describes the page's content. "
                "Only mark up what a user can actually see on the page."
            ),
        )
        for page in ctx.pages
        if _indexable(page) and not page.schema_blocks and page.word_count >= THIN_CONTENT_WORDS
    ]


@check("hreflang_no_return_tag")
def hreflang_no_return_tag(ctx: CheckContext) -> list[SEOIssue]:
    """An hreflang cluster is only valid if the references are reciprocal."""
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        if not page.hreflang:
            continue
        source = (page.final_url or page.url).rstrip("/") or "/"
        for entry in page.hreflang:
            target_key = entry.url.rstrip("/") or "/"
            target = ctx.by_url.get(target_key)
            if target is None or target_key == source:
                continue
            returns = any((alt.url.rstrip("/") or "/") == source for alt in target.hreflang)
            if not returns:
                issues.append(
                    _issue(
                        "hreflang_no_return_tag",
                        "hreflang reference is not reciprocated",
                        IssueSeverity.MEDIUM,
                        SEODimension.TECHNICAL_HEALTH,
                        url=page.url,
                        detail=(
                            f"This page declares {entry.url} as its {entry.lang} "
                            "alternate, but that page does not link back."
                        ),
                        recommendation="Add the return hreflang link on the target page.",
                        data={"lang": entry.lang, "target": entry.url},
                    )
                )
    return issues


@check("hreflang_missing_x_default")
def hreflang_missing_x_default(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "hreflang_missing_x_default",
            "hreflang cluster has no x-default",
            IssueSeverity.LOW,
            SEODimension.TECHNICAL_HEALTH,
            url=page.url,
            detail="No x-default alternate is declared for unmatched languages.",
            recommendation="Add an x-default pointing at the fallback page.",
        )
        for page in ctx.pages
        if len(page.hreflang) > 1 and not any(e.lang.lower() == "x-default" for e in page.hreflang)
    ]


@check("mixed_protocol")
def mixed_protocol(ctx: CheckContext) -> list[SEOIssue]:
    schemes: dict[str, list[str]] = defaultdict(list)
    for page in ctx.pages:
        schemes[urlparse(page.url).scheme].append(page.url)
    if "http" in schemes and "https" in schemes:
        return [
            _issue(
                "mixed_protocol",
                "The site serves pages over both HTTP and HTTPS",
                IssueSeverity.HIGH,
                SEODimension.TECHNICAL_HEALTH,
                url=schemes["http"][0],
                detail=(
                    f"{len(schemes['http'])} HTTP URL(s) and {len(schemes['https'])} "
                    "HTTPS URL(s) were crawled."
                ),
                recommendation="Redirect all HTTP URLs to their HTTPS equivalents.",
                affected=schemes["http"][:50],
            )
        ]
    if "http" in schemes:
        return [
            _issue(
                "mixed_protocol",
                "The site is served over HTTP",
                IssueSeverity.HIGH,
                SEODimension.TECHNICAL_HEALTH,
                url=schemes["http"][0],
                detail="No HTTPS URLs were observed.",
                recommendation="Serve the site over HTTPS.",
                affected=schemes["http"][:50],
            )
        ]
    return []


@check("robots_txt_missing")
def robots_txt_missing(ctx: CheckContext) -> list[SEOIssue]:
    if ctx.result.robots.fetched:
        return []
    return [
        _issue(
            "robots_txt_missing",
            "robots.txt was not retrieved",
            IssueSeverity.LOW,
            SEODimension.TECHNICAL_HEALTH,
            url=ctx.result.robots.url,
            detail=ctx.result.robots.error or "The file was not found.",
            recommendation="Publish a robots.txt that references your sitemap.",
        )
    ]


@check("sitemap_missing")
def sitemap_missing(ctx: CheckContext) -> list[SEOIssue]:
    if ctx.result.sitemap.discovered:
        return []
    return [
        _issue(
            "sitemap_missing",
            "No XML sitemap was found",
            IssueSeverity.MEDIUM,
            SEODimension.INDEXABILITY,
            detail="Neither robots.txt nor /sitemap.xml yielded a readable sitemap.",
            recommendation="Publish a sitemap and reference it from robots.txt.",
            data={"errors": ctx.result.sitemap.errors[:5]},
        )
    ]


@check("sitemap_url_not_indexable")
def sitemap_url_not_indexable(ctx: CheckContext) -> list[SEOIssue]:
    """A sitemap is a set of canonical, indexable URLs — or it misleads."""
    issues: list[SEOIssue] = []
    for key in ctx.sitemap_urls:
        page = ctx.by_url.get(key)
        if page is None:
            continue
        if page.is_error or page.is_redirect or not page.is_indexable:
            reason = (
                f"returns {page.status_code}"
                if page.is_error or page.is_redirect
                else "is marked noindex"
            )
            issues.append(
                _issue(
                    "sitemap_url_not_indexable",
                    "Sitemap lists a URL that cannot be indexed",
                    IssueSeverity.MEDIUM,
                    SEODimension.INDEXABILITY,
                    url=page.url,
                    detail=f"The URL is in the sitemap but {reason}.",
                    recommendation="List only canonical, indexable URLs in the sitemap.",
                    data={"status_code": page.status_code},
                )
            )
    return issues


@check("page_not_in_sitemap")
def page_not_in_sitemap(ctx: CheckContext) -> list[SEOIssue]:
    if not ctx.result.sitemap.entries:
        return []
    missing = [
        p.url
        for p in ctx.pages
        if _indexable(p) and (p.url.rstrip("/") or "/") not in ctx.sitemap_urls
    ]
    if not missing:
        return []
    return [
        _issue(
            "page_not_in_sitemap",
            "Indexable pages are absent from the sitemap",
            IssueSeverity.LOW,
            SEODimension.INDEXABILITY,
            url=missing[0],
            detail=f"{len(missing)} crawled indexable page(s) are not listed.",
            recommendation="Add them to the sitemap so discovery does not depend on crawling.",
            affected=missing[:50],
        )
    ]


@check("missing_lang_attribute")
def missing_lang_attribute(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "missing_lang_attribute",
            "Page does not declare its language",
            IssueSeverity.LOW,
            SEODimension.AI_SEARCH_READINESS,
            url=page.url,
            detail="The <html> element has no lang attribute.",
            recommendation="Add lang to the html element.",
        )
        for page in ctx.pages
        if _indexable(page) and not page.lang
    ]


# ---------------------------------------------------------------------------
# Conversion and machine readiness
# ---------------------------------------------------------------------------
@check("no_conversion_path")
def no_conversion_path(ctx: CheckContext) -> list[SEOIssue]:
    """A page with substance but no next step cannot convert."""
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        if not _indexable(page) or page.word_count < THIN_CONTENT_WORDS:
            continue
        has_form = page.accessibility.forms_total > 0
        has_action = any(
            keyword in link.anchor_text.lower()
            for link in page.internal_links
            for keyword in ("contact", "book", "quote", "enquir", "inquir", "buy", "get started")
        )
        if not has_form and not has_action and page.accessibility.buttons_total == 0:
            issues.append(
                _issue(
                    "no_conversion_path",
                    "Page offers the reader no next step",
                    IssueSeverity.LOW,
                    SEODimension.CONVERSION_READINESS,
                    url=page.url,
                    detail="No form, button or action-oriented internal link was found.",
                    recommendation="Add a relevant next step for a reader who is convinced.",
                )
            )
    return issues


@check("unlabelled_form_controls")
def unlabelled_form_controls(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        signals = page.accessibility
        unlabelled = signals.form_controls_total - signals.form_controls_labelled
        if unlabelled > 0:
            issues.append(
                _issue(
                    "unlabelled_form_controls",
                    "Form controls have no accessible label",
                    IssueSeverity.MEDIUM,
                    SEODimension.CONVERSION_READINESS,
                    url=page.url,
                    detail=(
                        f"{unlabelled} of {signals.form_controls_total} controls have no "
                        "label, aria-label or title. Both people using assistive "
                        "technology and browser agents rely on these names."
                    ),
                    recommendation="Give every control a programmatically associated label.",
                    data={"unlabelled": unlabelled, "total": signals.form_controls_total},
                )
            )
    return issues


@check("unnamed_interactive_elements")
def unnamed_interactive_elements(ctx: CheckContext) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    for page in ctx.pages:
        signals = page.accessibility
        unnamed = signals.buttons_total - signals.buttons_with_accessible_name
        if unnamed > 0:
            issues.append(
                _issue(
                    "unnamed_interactive_elements",
                    "Buttons have no accessible name",
                    IssueSeverity.MEDIUM,
                    SEODimension.AI_SEARCH_READINESS,
                    url=page.url,
                    detail=(
                        f"{unnamed} of {signals.buttons_total} buttons expose no name, "
                        "so an agent cannot tell what activating them would do."
                    ),
                    recommendation="Give each button visible text or an aria-label.",
                    data={"unnamed": unnamed, "total": signals.buttons_total},
                )
            )
    return issues


@check("no_semantic_landmarks")
def no_semantic_landmarks(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "no_semantic_landmarks",
            "Page has no main landmark",
            IssueSeverity.LOW,
            SEODimension.AI_SEARCH_READINESS,
            url=page.url,
            detail=(
                'No <main> element or role="main" was found, so the primary content '
                "is not machine-identifiable."
            ),
            recommendation="Wrap the primary content in a <main> element.",
        )
        for page in ctx.pages
        if _indexable(page) and not page.accessibility.has_main_landmark
    ]


@check("javascript_dependent_content")
def javascript_dependent_content(ctx: CheckContext) -> list[SEOIssue]:
    return [
        _issue(
            "javascript_dependent_content",
            "Content appears to require JavaScript",
            IssueSeverity.HIGH,
            SEODimension.AI_SEARCH_READINESS,
            url=page.url,
            detail=(
                f"Only {page.accessibility.body_text_chars} characters of text were in "
                f"the initial HTML alongside {page.accessibility.script_tags} scripts."
            ),
            recommendation=(
                "Server-render the primary content. Systems that do not execute "
                "JavaScript will otherwise see an empty page."
            ),
            data={
                "text_chars": page.accessibility.body_text_chars,
                "scripts": page.accessibility.script_tags,
            },
        )
        for page in ctx.pages
        if _indexable(page) and page.accessibility.rendered_by_javascript
    ]


# ---------------------------------------------------------------------------
def run_all_checks(result: CrawlResult) -> list[SEOIssue]:
    """Run every registered check and return the issues, most severe first."""
    ctx = CheckContext.build(result)
    issues: list[SEOIssue] = []
    for _check_id, fn in _REGISTRY:
        issues.extend(fn(ctx))
    order = {
        IssueSeverity.CRITICAL: 0,
        IssueSeverity.HIGH: 1,
        IssueSeverity.MEDIUM: 2,
        IssueSeverity.LOW: 3,
        IssueSeverity.INFO: 4,
    }
    issues.sort(key=lambda i: (order[i.severity], i.check_id, i.url or ""))
    return issues


def registered_checks() -> list[str]:
    return [check_id for check_id, _ in _REGISTRY]


__all__ = [
    "META_DESCRIPTION_MAX_LENGTH",
    "META_DESCRIPTION_MIN_LENGTH",
    "THIN_CONTENT_WORDS",
    "TITLE_MAX_LENGTH",
    "TITLE_MIN_LENGTH",
    "CheckContext",
    "registered_checks",
    "run_all_checks",
]
