"""Keyword and cluster read endpoints, agent registry, runs, memory and audit."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import SearchService

router = APIRouter(tags=["search"])


@router.get("/brands/{brand_id}/keywords")
async def list_keywords(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    service = SearchService(session, principal)
    rows = await service.list_keywords(brand_id, limit=page.limit, offset=page.offset)
    summary = await service.keyword_summary(brand_id)
    return envelope(
        [serialize.keyword(k) for k in rows],
        meta={
            **page_meta(rows, limit=page.limit, offset=page.offset),
            "summary": summary,
            "note": (
                "Keywords without a metrics row carry no measured demand; their scores "
                "rest on business relevance, intent and competitive gap only."
            ),
        },
        request_id=request.state.request_id,
    )


@router.get("/brands/{brand_id}/keyword-clusters")
async def list_clusters(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    rows = await SearchService(session, principal).list_clusters(brand_id, limit=page.limit)
    return envelope(
        [serialize.keyword_cluster(c) for c in rows],
        meta=page_meta(rows, limit=page.limit, offset=0),
        request_id=request.state.request_id,
    )
