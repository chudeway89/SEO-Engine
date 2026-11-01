"""Decision stack: opportunities, recommendations, actions, approvals, outcomes.

This is where the human is in the loop. Approving a recommendation or an action
is a permission-checked, audited domain operation; the API adds nothing but the
transport.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import DecisionService

router = APIRouter(tags=["decisions"])


class DecisionNote(BaseModel):
    note: str = Field(default="", max_length=4000)


@router.get("/brands/{brand_id}/opportunities")
async def list_opportunities(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    status: str | None = Query(default=None),
) -> dict:
    rows = await DecisionService(session, principal).list_opportunities(
        brand_id, status=status, limit=page.limit, offset=page.offset
    )
    return envelope(
        [serialize.opportunity(o) for o in rows],
        meta=page_meta(rows, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/brands/{brand_id}/recommendations")
async def list_recommendations(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    status: str | None = Query(default=None),
) -> dict:
    rows = await DecisionService(session, principal).list_recommendations(
        brand_id, status=status, limit=page.limit, offset=page.offset
    )
    return envelope(
        [serialize.recommendation(r) for r in rows],
        meta=page_meta(rows, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.post("/recommendations/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: uuid.UUID,
    body: DecisionNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await DecisionService(session, principal).approve_recommendation(
        recommendation_id, note=body.note
    )
    return envelope(serialize.recommendation(row), request_id=request.state.request_id)


@router.post("/recommendations/{recommendation_id}/reject")
async def reject_recommendation(
    recommendation_id: uuid.UUID,
    body: DecisionNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await DecisionService(session, principal).reject_recommendation(
        recommendation_id, note=body.note
    )
    return envelope(serialize.recommendation(row), request_id=request.state.request_id)


@router.post("/recommendations/{recommendation_id}/defer")
async def defer_recommendation(
    recommendation_id: uuid.UUID,
    body: DecisionNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await DecisionService(session, principal).defer_recommendation(
        recommendation_id, note=body.note
    )
    return envelope(serialize.recommendation(row), request_id=request.state.request_id)


@router.get("/brands/{brand_id}/actions")
async def list_actions(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    status: str | None = Query(default=None),
) -> dict:
    rows = await DecisionService(session, principal).list_actions(
        brand_id, status=status, limit=page.limit
    )
    return envelope(
        [serialize.action(a) for a in rows],
        meta=page_meta(rows, limit=page.limit, offset=0),
        request_id=request.state.request_id,
    )


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: uuid.UUID,
    body: DecisionNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await DecisionService(session, principal).approve_action(action_id, note=body.note)
    return envelope(serialize.action(row), request_id=request.state.request_id)


@router.post("/actions/{action_id}/reject")
async def reject_action(
    action_id: uuid.UUID,
    body: DecisionNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await DecisionService(session, principal).reject_action(action_id, note=body.note)
    return envelope(serialize.action(row), request_id=request.state.request_id)


@router.get("/brands/{brand_id}/outcomes")
async def list_outcomes(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    rows = await DecisionService(session, principal).list_outcomes(brand_id, limit=page.limit)
    return envelope(
        [
            {
                "id": str(o.id),
                "action_id": str(o.action_id) if o.action_id else None,
                "metric": o.metric,
                "baseline": o.baseline,
                "result": o.result,
                "delta": o.delta,
                "delta_percent": o.delta_percent,
                "provenance": o.provenance,
                "source": o.source,
                "status": o.status,
                "detail": o.detail,
                "observed_at": o.observed_at.isoformat() if o.observed_at else None,
            }
            for o in rows
        ],
        meta=page_meta(rows, limit=page.limit, offset=0),
        request_id=request.state.request_id,
    )
