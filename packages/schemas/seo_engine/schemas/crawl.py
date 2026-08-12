"""Crawl contracts.

The crawler never returns raw strings for page copy — extracted text is always
carried as :class:`seo_engine.shared.untrusted.UntrustedContent` so the
untrusted marker survives into the agent context layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Heading(BaseModel):
    level: int = Field(ge=1, le=6)
    text: str


class Link(BaseModel):
    url: str
    anchor_text: str = ""
    rel: list[str] = Field(default_factory=list)
    is_internal: bool = True

    @property
    def is_nofollow(self) -> bool:
        return "nofollow" in self.rel


class Image(BaseModel):
    src: str
    alt: str | None = None
    title: str | None = None
    width: int | None = None
    height: int | None = None
    loading: str | None = None

    @property
    def has_alt(self) -> bool:
        return self.alt is not None and self.alt.strip() != ""


class HreflangEntry(BaseModel):
    lang: str
    url: str


class AccessibilitySignals(BaseModel):
    """Signals for the agentic-web-readiness audit (Architecture Pack §61)."""

    semantic_landmarks: list[str] = Field(default_factory=list)
    buttons_total: int = 0
    buttons_with_accessible_name: int = 0
    links_total: int = 0
    links_with_accessible_name: int = 0
    forms_total: int = 0
    form_controls_total: int = 0
    form_controls_labelled: int = 0
    images_total: int = 0
    images_with_alt: int = 0
    has_main_landmark: bool = False
    has_skip_link: bool = False
    heading_order_valid: bool = True
    aria_roles: list[str] = Field(default_factory=list)
    tabindex_positive_count: int = 0
    script_tags: int = 0
    noscript_present: bool = False
    body_text_chars: int = 0
    rendered_by_javascript: bool = False


class CrawlPage(BaseModel):
    """One fetched URL, fully parsed.

    ``text_content`` is intentionally excluded from serialisation defaults; use
    :attr:`untrusted_text` when passing page copy anywhere near a model.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    depth: int = 0
    discovered_from: str | None = None

    title: str | None = None
    meta_description: str | None = None
    meta_robots: list[str] = Field(default_factory=list)
    x_robots_tag: list[str] = Field(default_factory=list)
    canonical_url: str | None = None
    lang: str | None = None

    headings: list[Heading] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    hreflang: list[HreflangEntry] = Field(default_factory=list)
    schema_blocks: list[dict[str, Any]] = Field(default_factory=list)
    open_graph: dict[str, str] = Field(default_factory=dict)

    text_content: str = ""
    word_count: int = 0
    content_hash: str = ""
    html_bytes: int = 0
    response_time_ms: int | None = None

    redirect_chain: list[str] = Field(default_factory=list)
    accessibility: AccessibilitySignals = Field(default_factory=AccessibilitySignals)

    fetched_at: datetime
    error: str | None = None
    injection_findings: list[dict[str, str]] = Field(default_factory=list)

    # ------------------------------------------------------------------
    @property
    def h1s(self) -> list[str]:
        return [h.text for h in self.headings if h.level == 1]

    @property
    def internal_links(self) -> list[Link]:
        return [link for link in self.links if link.is_internal]

    @property
    def external_links(self) -> list[Link]:
        return [link for link in self.links if not link.is_internal]

    @property
    def is_indexable(self) -> bool:
        directives = {d.lower() for d in [*self.meta_robots, *self.x_robots_tag]}
        if "noindex" in directives or "none" in directives:
            return False
        return self.status_code == 200

    @property
    def is_redirect(self) -> bool:
        return self.status_code is not None and 300 <= self.status_code < 400

    @property
    def is_error(self) -> bool:
        return self.status_code is not None and self.status_code >= 400

    def untrusted_text(self):
        from seo_engine.shared.untrusted import wrap_external

        return wrap_external(self.text_content, source=self.url, source_type="web_page")


class RobotsPolicy(BaseModel):
    fetched: bool = False
    url: str | None = None
    allows_crawling: bool = True
    sitemaps: list[str] = Field(default_factory=list)
    crawl_delay: float | None = None
    raw: str = ""
    error: str | None = None


class SitemapEntry(BaseModel):
    loc: str
    lastmod: datetime | None = None
    changefreq: str | None = None
    priority: float | None = None
    source_sitemap: str | None = None


class SitemapReport(BaseModel):
    discovered: list[str] = Field(default_factory=list)
    index_files: list[str] = Field(default_factory=list)
    entries: list[SitemapEntry] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class CrawlConfig(BaseModel):
    max_pages: int = Field(gt=0, le=50_000, default=200)
    max_depth: int = Field(ge=0, le=20, default=4)
    concurrency: int = Field(gt=0, le=32, default=4)
    requests_per_second: float = Field(gt=0, le=50, default=2.0)
    request_timeout_seconds: float = Field(gt=0, le=120, default=20.0)
    respect_robots: bool = True
    allowed_domains: list[str] = Field(default_factory=list)
    include_subdomains: bool = False
    follow_external_links: bool = False
    user_agent: str = "SEOEngineBot/0.1"
    max_html_bytes: int = Field(gt=0, default=3_000_000)
    seed_urls: list[str] = Field(default_factory=list)
    use_sitemap: bool = True


class CrawlResult(BaseModel):
    website_id: str
    start_url: str
    config: CrawlConfig
    robots: RobotsPolicy = Field(default_factory=RobotsPolicy)
    sitemap: SitemapReport = Field(default_factory=SitemapReport)
    pages: list[CrawlPage] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None
    stopped_reason: str | None = None
    errors: list[dict[str, str]] = Field(default_factory=list)

    @property
    def pages_crawled(self) -> int:
        return len(self.pages)

    @property
    def error_count(self) -> int:
        return len(self.errors) + sum(1 for p in self.pages if p.error)


__all__ = [
    "AccessibilitySignals",
    "CrawlConfig",
    "CrawlPage",
    "CrawlResult",
    "Heading",
    "HreflangEntry",
    "Image",
    "Link",
    "RobotsPolicy",
    "SitemapEntry",
    "SitemapReport",
]
