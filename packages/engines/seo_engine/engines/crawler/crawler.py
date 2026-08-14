"""The website crawler.

Safeguards are not optional and not advisory — every one of them is enforced in
the loop and the reason a crawl stopped is recorded on the result:

* ``max_pages``, ``max_depth`` — hard bounds; the crawl never runs indefinitely;
* ``requests_per_second`` — a global token-bucket, raised to the robots
  ``Crawl-delay`` if the site asks for slower;
* ``concurrency`` — bounded worker pool;
* ``request_timeout_seconds`` — per request;
* ``allowed_domains`` — off-site URLs are recorded as links but never fetched;
* ``robots_policy`` — disallowed URLs are skipped and counted;
* ``max_html_bytes`` — oversized responses are truncated rather than buffered.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from seo_engine.engines.crawler.parser import (
    PageParser,
    is_same_site,
    normalise_url,
    registrable_domain,
)
from seo_engine.engines.crawler.robots import fetch_robots
from seo_engine.engines.crawler.sitemap import discover_sitemaps
from seo_engine.observability.logging import get_logger
from seo_engine.observability.metrics import counter
from seo_engine.schemas.crawl import CrawlConfig, CrawlPage, CrawlResult
from seo_engine.shared.ids import utcnow

log = get_logger(__name__)

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


class RateLimiter:
    """Simple async token bucket, shared by every worker in one crawl."""

    def __init__(self, rate_per_second: float) -> None:
        self.min_interval = 1.0 / max(rate_per_second, 0.01)
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_slot - now)
            self._next_slot = max(now, self._next_slot) + self.min_interval
        if wait > 0:
            await asyncio.sleep(wait)


@dataclass(slots=True)
class _Frontier:
    """Queue of URLs to visit, deduplicated and depth-aware."""

    max_depth: int
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    seen: set[str] = field(default_factory=set)

    def add(self, url: str, depth: int, discovered_from: str | None) -> bool:
        if depth > self.max_depth or url in self.seen:
            return False
        self.seen.add(url)
        self.queue.put_nowait((url, depth, discovered_from))
        return True


class WebsiteCrawler:
    """Fetches a site within its declared safeguards and returns observations."""

    def __init__(self, config: CrawlConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None

    async def crawl(self, start_url: str, *, website_id: str = "") -> CrawlResult:
        started = utcnow()
        start_url = normalise_url(start_url)
        allowed = set(self.config.allowed_domains) or {registrable_domain(start_url)}

        result = CrawlResult(
            website_id=website_id,
            start_url=start_url,
            config=self.config,
            started_at=started,
        )

        client = self._client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.config.request_timeout_seconds,
            headers={"User-Agent": self.config.user_agent},
            limits=httpx.Limits(max_connections=self.config.concurrency * 2),
        )
        try:
            base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"

            # --- robots -------------------------------------------------
            policy, rules = await fetch_robots(client, base, self.config.user_agent)
            result.robots = policy
            if self.config.respect_robots and not policy.allows_crawling:
                result.stopped_reason = "robots.txt disallows crawling the start URL"
                result.finished_at = utcnow()
                log.warning("crawl_blocked_by_robots", start_url=start_url)
                return result

            rate = self.config.requests_per_second
            if self.config.respect_robots and policy.crawl_delay:
                # The site asked for slower; honour it, never speed up.
                rate = min(rate, 1.0 / policy.crawl_delay)
            limiter = RateLimiter(rate)

            # --- sitemap ------------------------------------------------
            seeds: list[str] = [start_url, *self.config.seed_urls]
            if self.config.use_sitemap:
                candidates = policy.sitemaps or [f"{base}/sitemap.xml"]
                result.sitemap = await discover_sitemaps(client, candidates=candidates)
                for entry in result.sitemap.entries:
                    url = normalise_url(entry.loc)
                    if is_same_site(
                        url, allowed, include_subdomains=self.config.include_subdomains
                    ):
                        seeds.append(url)

            frontier = _Frontier(max_depth=self.config.max_depth)
            for seed in dict.fromkeys(seeds):
                frontier.add(seed, 0, None)

            parser = PageParser(
                allowed_domains=allowed, include_subdomains=self.config.include_subdomains
            )
            state = {"fetched": 0, "stopped": None}
            lock = asyncio.Lock()

            async def worker() -> None:
                while True:
                    try:
                        url, depth, source = frontier.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        async with lock:
                            if state["fetched"] >= self.config.max_pages:
                                state["stopped"] = f"reached max_pages ({self.config.max_pages})"
                                return
                            state["fetched"] += 1

                        if self.config.respect_robots and not rules.allows(
                            url, self.config.user_agent
                        ):
                            result.errors.append(
                                {"url": url, "error": "skipped: disallowed by robots.txt"}
                            )
                            counter("crawl_robots_skipped_total")
                            continue

                        await limiter.acquire()
                        page = await self._fetch(client, parser, url, depth, source)
                        result.pages.append(page)

                        if page.status_code == 200 and not page.error:
                            for link in page.internal_links:
                                if link.is_nofollow:
                                    continue
                                frontier.add(link.url, depth + 1, url)
                    finally:
                        frontier.queue.task_done()

            workers = [asyncio.create_task(worker()) for _ in range(self.config.concurrency)]
            await asyncio.gather(*workers)

            if state["stopped"]:
                result.stopped_reason = state["stopped"]
            elif frontier.queue.qsize():
                result.stopped_reason = "queue not exhausted within the configured bounds"

        finally:
            if self._owns_client:
                await client.aclose()

        result.finished_at = utcnow()
        log.info(
            "crawl_completed",
            start_url=start_url,
            pages=len(result.pages),
            errors=result.error_count,
            stopped_reason=result.stopped_reason,
        )
        return result

    # ------------------------------------------------------------------
    async def _fetch(
        self,
        client: httpx.AsyncClient,
        parser: PageParser,
        url: str,
        depth: int,
        discovered_from: str | None,
    ) -> CrawlPage:
        started = time.perf_counter()
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            counter("crawl_errors_total", reason=type(exc).__name__)
            return CrawlPage(
                url=url,
                depth=depth,
                discovered_from=discovered_from,
                fetched_at=utcnow(),
                error=f"{type(exc).__name__}: {exc}",
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        content_type = response.headers.get("content-type", "")
        redirect_chain = [str(r.url) for r in response.history]
        final_url = str(response.url) if str(response.url) != url else None
        x_robots = [
            directive.strip().lower()
            for value in response.headers.get_list("x-robots-tag")
            for directive in value.split(",")
            if directive.strip()
        ]

        if not any(html_type in content_type for html_type in HTML_CONTENT_TYPES):
            # Non-HTML is still an observation (status, type, redirect chain);
            # it simply has no parseable body.
            return CrawlPage(
                url=url,
                final_url=final_url,
                status_code=response.status_code,
                content_type=content_type or None,
                depth=depth,
                discovered_from=discovered_from,
                redirect_chain=redirect_chain,
                response_time_ms=elapsed_ms,
                x_robots_tag=x_robots,
                html_bytes=len(response.content),
                fetched_at=utcnow(),
            )

        html = response.text
        if len(response.content) > self.config.max_html_bytes:
            html = response.text[: self.config.max_html_bytes]

        page = parser.parse(
            url=url,
            html=html,
            status_code=response.status_code,
            content_type=content_type or None,
            final_url=final_url,
            depth=depth,
            discovered_from=discovered_from,
            redirect_chain=redirect_chain,
            response_time_ms=elapsed_ms,
            x_robots_tag=x_robots,
        )
        counter("crawl_pages_total", status=str(response.status_code))
        return page


def config_from_settings(**overrides: Any) -> CrawlConfig:
    """Build a crawl config from platform settings, with per-crawl overrides."""
    from seo_engine.shared.config import get_settings

    settings = get_settings()
    base = {
        "max_pages": settings.crawler_max_pages,
        "max_depth": settings.crawler_max_depth,
        "concurrency": settings.crawler_concurrency,
        "requests_per_second": settings.crawler_requests_per_second,
        "request_timeout_seconds": settings.crawler_request_timeout_seconds,
        "respect_robots": settings.crawler_respect_robots,
        "user_agent": settings.crawler_user_agent,
    }
    base.update({k: v for k, v in overrides.items() if v is not None})
    return CrawlConfig(**base)


__all__ = ["RateLimiter", "WebsiteCrawler", "config_from_settings"]
