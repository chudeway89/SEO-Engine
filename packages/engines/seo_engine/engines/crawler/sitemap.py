"""Sitemap and sitemap-index discovery.

Handles nested sitemap indexes with a depth bound, because a malformed or
malicious sitemap can otherwise reference itself forever.
"""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup
from seo_engine.observability.logging import get_logger
from seo_engine.schemas.crawl import SitemapEntry, SitemapReport

log = get_logger(__name__)

MAX_INDEX_DEPTH = 3
MAX_SITEMAPS = 50
MAX_ENTRIES = 50_000


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


async def discover_sitemaps(
    client,
    *,
    candidates: list[str],
    max_entries: int = MAX_ENTRIES,
) -> SitemapReport:
    """Fetch every candidate sitemap, following indexes breadth-first."""
    report = SitemapReport()
    queue: list[tuple[str, int]] = [(url, 0) for url in dict.fromkeys(candidates)]
    seen: set[str] = set()

    while queue and len(report.discovered) < MAX_SITEMAPS:
        url, depth = queue.pop(0)
        if url in seen or depth > MAX_INDEX_DEPTH:
            continue
        seen.add(url)

        try:
            response = await client.get(url)
        except Exception as exc:
            report.errors.append({"url": url, "error": str(exc)})
            continue

        if response.status_code >= 400:
            report.errors.append({"url": url, "error": f"HTTP {response.status_code}"})
            continue

        report.discovered.append(url)
        soup = BeautifulSoup(response.text, "xml")

        if soup.find("sitemapindex"):
            report.index_files.append(url)
            for node in soup.find_all("sitemap"):
                loc = node.find("loc")
                if loc and loc.get_text(strip=True):
                    queue.append((loc.get_text(strip=True), depth + 1))
            continue

        for node in soup.find_all("url"):
            if len(report.entries) >= max_entries:
                report.errors.append(
                    {"url": url, "error": f"entry cap of {max_entries} reached; truncated"}
                )
                return report
            loc = node.find("loc")
            if not loc or not loc.get_text(strip=True):
                continue
            lastmod = node.find("lastmod")
            changefreq = node.find("changefreq")
            priority = node.find("priority")
            report.entries.append(
                SitemapEntry(
                    loc=loc.get_text(strip=True),
                    lastmod=_parse_datetime(lastmod.get_text(strip=True) if lastmod else None),
                    changefreq=changefreq.get_text(strip=True) if changefreq else None,
                    priority=_float_or_none(priority.get_text(strip=True) if priority else None),
                    source_sitemap=url,
                )
            )

    return report


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


__all__ = ["MAX_INDEX_DEPTH", "MAX_SITEMAPS", "discover_sitemaps"]
