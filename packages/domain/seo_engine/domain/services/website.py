"""Website service: registration, crawl job lifecycle and page persistence."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from seo_engine.domain.models.website import (
    CrawlJob,
    CrawlPageRecord,
    Page,
    PageImage,
    PageIssue,
    PageLink,
    PageSchemaBlock,
    Website,
    WebsiteScorecard,
)
from seo_engine.domain.repositories import TenantScopedRepository, repository_for
from seo_engine.domain.services.brand import BrandRepository, _normalise_domain
from seo_engine.events.bus import emit
from seo_engine.observability.audit import record_audit
from seo_engine.observability.metrics import counter
from seo_engine.permissions.rbac import (
    P_CRAWL_RUN,
    P_WEBSITE_READ,
    P_WEBSITE_WRITE,
    Principal,
)
from seo_engine.schemas.crawl import CrawlPage, CrawlResult
from seo_engine.schemas.enums import CrawlJobStatus
from seo_engine.schemas.events import EventType
from seo_engine.schemas.seo import SEOIssue, SEOScorecard
from seo_engine.shared.errors import ConflictError
from seo_engine.shared.ids import utcnow
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

WebsiteRepository = repository_for(Website)
CrawlJobRepository = repository_for(CrawlJob)
PageRepository = repository_for(Page)
PageIssueRepository = repository_for(PageIssue)


def _indexability(page: CrawlPage) -> tuple[str, str | None]:
    directives = {d.lower() for d in [*page.meta_robots, *page.x_robots_tag]}
    if page.error:
        return "error", page.error
    if page.status_code is None:
        return "unknown", "no response"
    if page.status_code >= 400:
        return "not_indexable", f"HTTP {page.status_code}"
    if page.is_redirect:
        return "not_indexable", f"redirect ({page.status_code})"
    if "noindex" in directives or "none" in directives:
        return "not_indexable", "noindex directive"
    if page.canonical_url and page.canonical_url.rstrip("/") != (page.final_url or page.url).rstrip(
        "/"
    ):
        return "canonicalised", f"canonical points to {page.canonical_url}"
    return "indexable", None


class WebsiteService:
    """Owns websites, crawl jobs and the page inventory."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.websites: TenantScopedRepository[Website] = WebsiteRepository(
            session, principal.tenant_id
        )
        self.jobs: TenantScopedRepository[CrawlJob] = CrawlJobRepository(
            session, principal.tenant_id
        )
        self.pages: TenantScopedRepository[Page] = PageRepository(session, principal.tenant_id)
        self.issues: TenantScopedRepository[PageIssue] = PageIssueRepository(
            session, principal.tenant_id
        )
        self._brands = BrandRepository(session, principal.tenant_id)

    # -- websites --------------------------------------------------------
    async def add_website(
        self,
        brand_id: uuid.UUID,
        *,
        url: str,
        cms: str | None = None,
        crawl_frequency: str = "weekly",
        crawl_config: dict[str, Any] | None = None,
    ) -> Website:
        self.principal.require(P_WEBSITE_WRITE)
        await self._brands.get_or_raise(brand_id)

        parsed = urlparse(url if "//" in url else f"https://{url}")
        domain = _normalise_domain(url)
        protocol = parsed.scheme if parsed.scheme in {"http", "https"} else "https"

        if await self.websites.exists(Website.brand_id == brand_id, Website.domain == domain):
            raise ConflictError("that website is already connected", {"domain": domain})

        website = self.websites.add(
            Website(
                brand_id=brand_id,
                domain=domain,
                protocol=protocol,
                base_path=parsed.path or "/",
                cms=cms,
                crawl_frequency=crawl_frequency,
                crawl_config=crawl_config or {},
                robots_url=f"{protocol}://{domain}/robots.txt",
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.WEBSITE_ADDED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="website",
            aggregate_id=str(website.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"domain": domain, "protocol": protocol},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="website.add",
            resource_type="website",
            resource_id=str(website.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=brand_id,
            after_state={"domain": domain},
        )
        return website

    async def get_website(self, website_id: uuid.UUID) -> Website:
        self.principal.require(P_WEBSITE_READ)
        return await self.websites.get_or_raise(website_id)

    async def list_websites(self, brand_id: uuid.UUID) -> list[Website]:
        self.principal.require(P_WEBSITE_READ)
        return list(await self.websites.list(Website.brand_id == brand_id))

    # -- crawl jobs ------------------------------------------------------
    async def create_crawl_job(
        self,
        website_id: uuid.UUID,
        *,
        config: dict[str, Any] | None = None,
        trigger: str = "manual",
        correlation_id: str | None = None,
    ) -> CrawlJob:
        self.principal.require(P_CRAWL_RUN)
        website = await self.websites.get_or_raise(website_id)

        running = await self.jobs.find_one(
            CrawlJob.website_id == website_id,
            CrawlJob.status.in_([CrawlJobStatus.QUEUED, CrawlJobStatus.RUNNING]),
        )
        if running is not None:
            raise ConflictError(
                "a crawl is already in progress for this website",
                {"crawl_job_id": str(running.id)},
            )

        job = self.jobs.add(
            CrawlJob(
                website_id=website_id,
                brand_id=website.brand_id,
                status=CrawlJobStatus.QUEUED,
                trigger=trigger,
                config=config or {},
                correlation_id=correlation_id,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.CRAWL_STARTED,
            tenant_id=self.principal.tenant_id,
            brand_id=website.brand_id,
            aggregate_type="crawl_job",
            aggregate_id=str(job.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            correlation_id=correlation_id,
            payload={"website_id": str(website_id), "trigger": trigger},
        )
        return job

    async def get_crawl_job(self, job_id: uuid.UUID) -> CrawlJob:
        self.principal.require(P_WEBSITE_READ)
        return await self.jobs.get_or_raise(job_id)

    async def mark_crawl_running(self, job_id: uuid.UUID) -> CrawlJob:
        job = await self.jobs.get_or_raise(job_id)
        job.status = CrawlJobStatus.RUNNING
        job.started_at = utcnow()
        await self.session.flush()
        return job

    async def record_crawl_result(self, job_id: uuid.UUID, result: CrawlResult) -> CrawlJob:
        """Persist a completed crawl: raw observations, then the page inventory.

        Raw crawl rows are immutable history; ``pages`` is the current state and
        is upserted.  Page copy keeps its untrusted marking in both.
        """
        job = await self.jobs.get_or_raise(job_id)
        website = await self.websites.get_or_raise(job.website_id)

        crawl_pages = repository_for(CrawlPageRecord)(self.session, self.principal.tenant_id)
        links_repo = repository_for(PageLink)(self.session, self.principal.tenant_id)
        images_repo = repository_for(PageImage)(self.session, self.principal.tenant_id)
        schema_repo = repository_for(PageSchemaBlock)(self.session, self.principal.tenant_id)

        sitemap_urls = {e.loc.rstrip("/") for e in result.sitemap.entries}
        linked_targets: set[str] = set()

        for page in result.pages:
            crawl_pages.add(
                CrawlPageRecord(
                    crawl_job_id=job.id,
                    website_id=website.id,
                    url=page.url,
                    final_url=page.final_url,
                    status_code=page.status_code,
                    content_type=page.content_type,
                    depth=page.depth,
                    discovered_from=page.discovered_from,
                    response_time_ms=page.response_time_ms,
                    html_bytes=page.html_bytes,
                    content_hash=page.content_hash,
                    redirect_chain=page.redirect_chain,
                    raw_extract=page.model_dump(
                        mode="json", exclude={"text_content", "links", "images"}
                    ),
                    text_content=page.text_content,
                    is_untrusted_external_content=True,
                    injection_findings=page.injection_findings,
                    error=page.error,
                    fetched_at=page.fetched_at,
                )
            )

        await self.session.flush()

        for page in result.pages:
            if page.error or page.status_code is None:
                continue
            indexability, reason = _indexability(page)
            url_key = page.url
            existing = await self.pages.find_one(Page.website_id == website.id, Page.url == url_key)
            h1s = page.h1s
            fields = {
                "brand_id": website.brand_id,
                "path": urlparse(page.url).path or "/",
                "canonical_url": page.canonical_url,
                "status_code": page.status_code,
                "indexability": indexability,
                "indexability_reason": reason,
                "title": page.title,
                "meta_description": page.meta_description,
                "h1": h1s[0] if h1s else None,
                "h1_count": len(h1s),
                "headings": [h.model_dump() for h in page.headings],
                "meta_robots": [*page.meta_robots, *page.x_robots_tag],
                "hreflang": [h.model_dump() for h in page.hreflang],
                "lang": page.lang,
                "word_count": page.word_count,
                "content_hash": page.content_hash,
                "internal_links_out": len(page.internal_links),
                "external_links_out": len(page.external_links),
                "depth": page.depth,
                "in_sitemap": page.url.rstrip("/") in sitemap_urls,
                "accessibility": page.accessibility.model_dump(),
                "text_content": page.text_content,
                "is_untrusted_external_content": True,
                "last_crawled_at": page.fetched_at,
            }
            if existing is None:
                record = self.pages.add(Page(website_id=website.id, url=url_key, **fields))
            else:
                record = existing
                for key, value in fields.items():
                    setattr(record, key, value)
            await self.session.flush()

            await links_repo.delete_where(PageLink.source_page_id == record.id)
            for link in page.links:
                if link.is_internal:
                    linked_targets.add(link.url.rstrip("/"))
                links_repo.add(
                    PageLink(
                        website_id=website.id,
                        crawl_job_id=job.id,
                        source_page_id=record.id,
                        source_url=page.url,
                        target_url=link.url,
                        anchor_text=link.anchor_text[:2000],
                        rel=link.rel,
                        is_internal=link.is_internal,
                    )
                )

            await images_repo.delete_where(PageImage.page_id == record.id)
            for image in page.images:
                images_repo.add(
                    PageImage(
                        website_id=website.id,
                        page_id=record.id,
                        src=image.src,
                        alt=image.alt,
                        title=image.title,
                        has_alt=image.has_alt,
                        width=image.width,
                        height=image.height,
                        loading=image.loading,
                    )
                )

            await schema_repo.delete_where(PageSchemaBlock.page_id == record.id)
            for block in page.schema_blocks:
                schema_repo.add(
                    PageSchemaBlock(
                        website_id=website.id,
                        page_id=record.id,
                        format=block.get("_format", "json-ld"),
                        schema_type=str(block.get("@type") or block.get("type") or "")[:120]
                        or None,
                        raw=block,
                    )
                )

        await self.session.flush()
        await self._recompute_link_graph(website.id, linked_targets, result.start_url)

        job.status = (
            CrawlJobStatus.COMPLETED if not result.stopped_reason else CrawlJobStatus.PARTIAL
        )
        job.pages_crawled = result.pages_crawled
        job.pages_discovered = max(result.pages_crawled, len(sitemap_urls))
        job.errors_count = result.error_count
        job.robots = result.robots.model_dump(mode="json")
        job.sitemap_report = result.sitemap.model_dump(mode="json")
        job.stopped_reason = result.stopped_reason
        job.finished_at = result.finished_at or utcnow()
        website.last_crawled_at = job.finished_at
        if result.robots.sitemaps:
            website.sitemap_url = result.robots.sitemaps[0]
        await self.session.flush()

        counter("crawl_pages_total", value=result.pages_crawled, website=str(website.id))
        counter("crawl_errors_total", value=result.error_count, website=str(website.id))

        injected = sum(1 for p in result.pages if p.injection_findings)
        if injected:
            await emit(
                self.session,
                EventType.PROMPT_INJECTION_DETECTED,
                tenant_id=self.principal.tenant_id,
                brand_id=website.brand_id,
                aggregate_type="crawl_job",
                aggregate_id=str(job.id),
                payload={"pages_with_findings": injected, "website_id": str(website.id)},
            )

        await emit(
            self.session,
            EventType.CRAWL_COMPLETED,
            tenant_id=self.principal.tenant_id,
            brand_id=website.brand_id,
            aggregate_type="crawl_job",
            aggregate_id=str(job.id),
            correlation_id=job.correlation_id,
            payload={
                "website_id": str(website.id),
                "pages_crawled": result.pages_crawled,
                "errors": result.error_count,
                "stopped_reason": result.stopped_reason,
            },
        )
        return job

    async def _recompute_link_graph(
        self, website_id: uuid.UUID, linked_targets: set[str], start_url: str
    ) -> None:
        """Recount inbound internal links and re-flag orphans."""
        counts = await self.session.execute(
            select(PageLink.target_url, func.count())
            .where(
                PageLink.tenant_id == self.principal.tenant_id,
                PageLink.website_id == website_id,
                PageLink.is_internal.is_(True),
            )
            .group_by(PageLink.target_url)
        )
        inbound: dict[str, int] = {}
        for target, count in counts.all():
            inbound[target.rstrip("/")] = inbound.get(target.rstrip("/"), 0) + int(count)

        home = start_url.rstrip("/")
        for page in await self.pages.list(Page.website_id == website_id):
            key = page.url.rstrip("/")
            page.internal_links_in = inbound.get(key, 0)
            # The entry point is never an orphan, and a sitemap listing counts
            # as discovery even without an internal link.
            page.is_orphan = page.internal_links_in == 0 and key != home and not page.in_sitemap
        await self.session.flush()

    async def fail_crawl_job(self, job_id: uuid.UUID, error: str) -> CrawlJob:
        job = await self.jobs.get_or_raise(job_id)
        job.status = CrawlJobStatus.FAILED
        job.error_detail = error[:4000]
        job.finished_at = utcnow()
        await self.session.flush()
        await emit(
            self.session,
            EventType.CRAWL_FAILED,
            tenant_id=self.principal.tenant_id,
            brand_id=job.brand_id,
            aggregate_type="crawl_job",
            aggregate_id=str(job.id),
            payload={"error": error[:500]},
        )
        return job

    # -- pages and issues -------------------------------------------------
    async def list_pages(
        self, website_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[Page]:
        self.principal.require(P_WEBSITE_READ)
        await self.websites.get_or_raise(website_id)
        return list(
            await self.pages.list(
                Page.website_id == website_id, limit=limit, offset=offset, order_by=Page.depth
            )
        )

    async def count_pages(self, website_id: uuid.UUID) -> int:
        return await self.pages.count(Page.website_id == website_id)

    async def replace_issues(
        self, website_id: uuid.UUID, crawl_job_id: uuid.UUID | None, issues: list[SEOIssue]
    ) -> list[PageIssue]:
        """Store a fresh audit's issues, resolving ones that no longer appear."""
        await self.websites.get_or_raise(website_id)

        previous = await self.issues.list(
            PageIssue.website_id == website_id, PageIssue.status == "open"
        )
        still_present = {(i.check_id, i.url) for i in issues}
        for old in previous:
            if (old.check_id, old.url) not in still_present:
                old.status = "resolved"
                old.resolved_at = utcnow()

        url_to_page: dict[str, uuid.UUID] = {
            p.url: p.id for p in await self.pages.list(Page.website_id == website_id)
        }

        stored: list[PageIssue] = []
        existing_keys = {(i.check_id, i.url): i for i in previous}
        for issue in issues:
            current = existing_keys.get((issue.check_id, issue.url))
            if current is not None:
                current.detail = issue.detail
                current.evidence_data = issue.evidence_data
                current.affected_urls = issue.affected_urls
                current.crawl_job_id = crawl_job_id
                stored.append(current)
                continue
            record = self.issues.add(
                PageIssue(
                    website_id=website_id,
                    crawl_job_id=crawl_job_id,
                    page_id=url_to_page.get(issue.url or ""),
                    url=issue.url,
                    check_id=issue.check_id,
                    title=issue.title,
                    severity=issue.severity.value,
                    dimension=issue.dimension.value,
                    detail=issue.detail,
                    recommendation=issue.recommendation,
                    evidence_data=issue.evidence_data,
                    affected_urls=issue.affected_urls,
                )
            )
            stored.append(record)
        await self.session.flush()
        return stored

    async def list_issues(
        self,
        website_id: uuid.UUID,
        *,
        severity: str | None = None,
        status: str = "open",
        limit: int = 200,
        offset: int = 0,
    ) -> list[PageIssue]:
        self.principal.require(P_WEBSITE_READ)
        criteria: list[Any] = [PageIssue.website_id == website_id, PageIssue.status == status]
        if severity:
            criteria.append(PageIssue.severity == severity)
        return list(await self.issues.list(*criteria, limit=limit, offset=offset))

    async def store_scorecard(
        self,
        website_id: uuid.UUID,
        brand_id: uuid.UUID,
        crawl_job_id: uuid.UUID | None,
        scorecard: SEOScorecard,
    ) -> WebsiteScorecard:
        repo = repository_for(WebsiteScorecard)(self.session, self.principal.tenant_id)
        record = repo.add(
            WebsiteScorecard(
                website_id=website_id,
                brand_id=brand_id,
                crawl_job_id=crawl_job_id,
                dimensions=[d.model_dump(mode="json") for d in scorecard.dimensions],
                overall=scorecard.overall,
                pages_evaluated=scorecard.pages_evaluated,
                issues_total=scorecard.issues_total,
                method=scorecard.method,
            )
        )
        await self.session.flush()
        return record

    async def latest_scorecard(self, website_id: uuid.UUID) -> WebsiteScorecard | None:
        repo = repository_for(WebsiteScorecard)(self.session, self.principal.tenant_id)
        rows = await repo.list(
            WebsiteScorecard.website_id == website_id,
            limit=1,
            order_by=WebsiteScorecard.created_at.desc(),
        )
        return rows[0] if rows else None


__all__ = [
    "CrawlJobRepository",
    "PageRepository",
    "WebsiteRepository",
    "WebsiteService",
]
