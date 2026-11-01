"""A storage-independent view of a crawled page.

The analysis engines take :class:`PageFacts` rather than ORM rows or full
``CrawlPage`` objects, so they stay pure functions that a unit test can drive
with three lines of data. Agents adapt whatever they loaded into this shape.

Every text field here came from a crawled website and is untrusted data: the
engines compare and count it, they never interpret it as instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class PageFacts:
    url: str
    status_code: int | None = 200
    title: str = ""
    h1: str = ""
    meta_description: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    word_count: int = 0
    canonical_url: str | None = None
    meta_robots: list[str] = field(default_factory=list)
    indexability: str = "unknown"
    indexability_reason: str | None = None
    in_sitemap: bool = False
    internal_links_in: int = 0
    depth: int = 0
    schema_types: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return urlparse(self.url).path or "/"

    @property
    def is_indexable(self) -> bool:
        return self.indexability == "indexable"


def key(url: str) -> str:
    """Comparison key for a URL: scheme-insensitive, trailing-slash-insensitive."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


def from_page_row(row: Any, *, schema_types: list[str] | None = None) -> PageFacts:
    """Adapt a stored ``Page`` row."""
    headings = [
        str(h.get("text", ""))
        for h in (getattr(row, "headings", None) or [])
        if isinstance(h, dict)
    ]
    return PageFacts(
        url=row.url,
        status_code=row.status_code,
        title=row.title or "",
        h1=row.h1 or "",
        meta_description=row.meta_description or "",
        headings=[h for h in headings if h],
        text=(row.text_content or "")[:20_000],
        word_count=row.word_count or 0,
        canonical_url=row.canonical_url,
        meta_robots=list(row.meta_robots or []),
        indexability=row.indexability or "unknown",
        indexability_reason=row.indexability_reason,
        in_sitemap=bool(row.in_sitemap),
        internal_links_in=row.internal_links_in or 0,
        depth=row.depth or 0,
        schema_types=list(schema_types or []),
    )


__all__ = ["PageFacts", "from_page_row", "key"]
