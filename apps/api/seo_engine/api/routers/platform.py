"""Integrations, memory search, events and audit."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.models.observability import AuditLog, EventRecord
from seo_engine.domain.repositories import repository_for
from seo_engine.domain.services import IntegrationService
from seo_engine.memory.service import MemoryService
from seo_engine.permissions.rbac import P_AUDIT_READ
from seo_engine.schemas.enums import IntegrationProvider

router = APIRouter(tags=["platform"])

EventRepository = repository_for(EventRecord)
AuditRepository = repository_for(AuditLog)


# --- integrations ------------------------------------------------------------
class ConnectRequest(BaseModel):
    provider: IntegrationProvider
    account_label: str | None = None


@router.post("/brands/{brand_id}/integrations", status_code=201)
async def connect_integration(
    brand_id: uuid.UUID,
    body: ConnectRequest,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    connection = await IntegrationService(session, principal).connect(
        brand_id, body.provider, account_label=body.account_label
    )
    data = serialize.integration_connection(connection)
    meta = {}
    if connection.mode == "development_adapter":
        meta["notice"] = (
            "No credentials are configured, so this connection uses the development "
            "adapter. Every figure it produces is synthetic demonstration data and is "
            "labelled as such; nothing from it describes the real property."
        )
    return envelope(data, meta=meta, request_id=request.state.request_id)


@router.get("/brands/{brand_id}/integrations")
async def list_integrations(
    brand_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    rows = await IntegrationService(session, principal).list_connections(brand_id)
    return envelope(
        [serialize.integration_connection(c) for c in rows],
        request_id=request.state.request_id,
    )


@router.post("/brands/{brand_id}/integrations/{provider}/sync", status_code=202)
async def sync_integration(
    brand_id: uuid.UUID,
    provider: IntegrationProvider,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    days: int = Query(default=28, ge=1, le=180),
) -> dict:
    service = IntegrationService(session, principal)
    if provider is IntegrationProvider.GOOGLE_SEARCH_CONSOLE:
        summary = await service.sync_search_console(brand_id, days=days)
    elif provider is IntegrationProvider.GOOGLE_ANALYTICS_4:
        summary = await service.sync_analytics(brand_id, days=days)
    else:
        from seo_engine.shared.errors import ValidationError

        raise ValidationError("that provider has no sync operation", {"provider": provider.value})
    return envelope(summary, request_id=request.state.request_id)


# --- memory ------------------------------------------------------------------
@router.get("/memory/search")
async def search_memory(
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    q: str = Query(min_length=1, max_length=500),
    brand_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    hits = await MemoryService(session, principal.tenant_id).search_semantic(
        q, brand_id=brand_id, limit=limit
    )
    return envelope(
        [serialize.memory_hit(h) for h in hits],
        meta={
            "note": (
                "Semantic retrieval over this tenant's memory only. Similarity is from "
                "a deterministic local embedder, not a hosted model."
            )
        },
        request_id=request.state.request_id,
    )


# --- events and audit --------------------------------------------------------
@router.get("/events")
async def list_events(
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    brand_id: uuid.UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    correlation_id: str | None = Query(default=None),
) -> dict:
    criteria = []
    if brand_id is not None:
        criteria.append(EventRecord.brand_id == brand_id)
    if event_type is not None:
        criteria.append(EventRecord.event_type == event_type)
    if correlation_id is not None:
        criteria.append(EventRecord.correlation_id == correlation_id)

    rows = await EventRepository(session, principal.tenant_id).list(
        *criteria, limit=page.limit, offset=page.offset, order_by=EventRecord.occurred_at.desc()
    )
    return envelope(
        [serialize.event(e) for e in rows],
        meta=page_meta(list(rows), limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/audit")
async def list_audit(
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
) -> dict:
    principal.require(P_AUDIT_READ)
    criteria = []
    if action is not None:
        criteria.append(AuditLog.action == action)
    if resource_type is not None:
        criteria.append(AuditLog.resource_type == resource_type)

    rows = await AuditRepository(session, principal.tenant_id).list(
        *criteria, limit=page.limit, offset=page.offset, order_by=AuditLog.created_at.desc()
    )
    return envelope(
        [serialize.audit_log(a) for a in rows],
        meta=page_meta(list(rows), limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )
