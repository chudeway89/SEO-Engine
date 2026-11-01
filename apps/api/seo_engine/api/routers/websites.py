"""Website, crawl and audit endpoints.

A crawl is never run inline in a request: ``POST /websites/{id}/audit``
dispatches the Technical SEO agent through the Agent Runtime in the background
and returns 202 with the identifiers to poll. The route contains no agent
logic — it creates work (Build Specification rule 2).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import BaseModel, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import WebsiteService
from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import P_CRAWL_RUN, Principal
from seo_engine.shared.db import session_scope

log = get_logger(__name__)

router = APIRouter(tags=["websites"])


class WebsiteCreate(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    cms: str | None = None
    crawl_frequency: str = "weekly"


class AuditRequest(BaseModel):
    max_pages: int | None = Field(default=None, ge=1, le=1000)
    max_depth: int | None = Field(default=None, ge=1, le=10)


@router.post("/brands/{brand_id}/websites", status_code=201)
async def add_website(
    brand_id: uuid.UUID,
    body: WebsiteCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    website = await WebsiteService(session, principal).add_website(brand_id, **body.model_dump())
    return envelope(serialize.website(website), request_id=request.state.request_id)


@router.get("/brands/{brand_id}/websites")
async def list_websites(
    brand_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    rows = await WebsiteService(session, principal).list_websites(brand_id)
    return envelope([serialize.website(w) for w in rows], request_id=request.state.request_id)


@router.get("/websites/{website_id}")
async def get_website(
    website_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    website = await WebsiteService(session, principal).get_website(website_id)
    return envelope(serialize.website(website), request_id=request.state.request_id)


async def _run_audit(
    principal: Principal,
    website_id: uuid.UUID,
    brand_id: uuid.UUID,
    options: dict[str, Any],
) -> None:
    """Background execution: its own session, through the Agent Runtime."""
    from seo_engine.agent_runtime.runner import AgentRunner, RunRequest
    from seo_engine.domain.services.integration import IntegrationService
    from seo_engine.workflows.services import build_services

    try:
        async with session_scope() as session:
            connected = await IntegrationService(session, principal).connected_providers(brand_id)
            await AgentRunner(session).run(
                RunRequest(
                    agent_id="SEO-001",
                    objective="Crawl the website and run the deterministic technical audit",
                    principal=principal,
                    brand_id=brand_id,
                    inputs={
                        "website_id": str(website_id),
                        "brand_id": str(brand_id),
                        **{k: v for k, v in options.items() if v is not None},
                    },
                    services=build_services(session, principal),
                    available_integrations=connected,
                )
            )
    except Exception:
        log.exception("background_audit_failed", website_id=str(website_id))


@router.post("/websites/{website_id}/audit", status_code=202)
async def start_audit(
    website_id: uuid.UUID,
    body: AuditRequest,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    background: BackgroundTasks,
) -> dict:
    principal.require(P_CRAWL_RUN)
    website = await WebsiteService(session, principal).get_website(website_id)
    background.add_task(_run_audit, principal, website.id, website.brand_id, body.model_dump())
    return envelope(
        {
            "status": "accepted",
            "website_id": str(website.id),
            "poll": {
                "crawl_jobs": f"/api/v1/websites/{website.id}/crawls",
                "agent_runs": f"/api/v1/agents/runs?brand_id={website.brand_id}&agent_id=SEO-001",
            },
        },
        request_id=request.state.request_id,
    )


@router.get("/websites/{website_id}/crawls")
async def list_crawls(
    website_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    service = WebsiteService(session, principal)
    await service.get_website(website_id)
    jobs = await service.list_crawl_jobs(website_id, limit=page.limit, offset=page.offset)
    return envelope(
        [serialize.crawl_job(j) for j in jobs],
        meta=page_meta(jobs, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/websites/{website_id}/pages")
async def list_pages(
    website_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    rows = await WebsiteService(session, principal).list_pages(
        website_id, limit=page.limit, offset=page.offset
    )
    return envelope(
        [serialize.page(p) for p in rows],
        meta=page_meta(rows, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/websites/{website_id}/issues")
async def list_issues(
    website_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    severity: str | None = Query(default=None),
) -> dict:
    rows = await WebsiteService(session, principal).list_issues(
        website_id, severity=severity, limit=page.limit, offset=page.offset
    )
    return envelope(
        [serialize.issue(i) for i in rows],
        meta=page_meta(rows, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/websites/{website_id}/scorecard")
async def latest_scorecard(
    website_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    row = await WebsiteService(session, principal).latest_scorecard(website_id)
    data = serialize.scorecard(row)
    meta = {}
    if data is None:
        meta["note"] = (
            "No audit has produced a scorecard for this website yet. "
            "Run POST /websites/{id}/audit first."
        )
    return envelope(data, meta=meta, request_id=request.state.request_id)
