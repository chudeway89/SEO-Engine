"""Content assets and the editorial decision.

Agents draft, evaluate and gate content; only a person approves it. The approve
route is the one place that decision is taken, and it goes through the
non-agent content service, which still refuses approval until the current
version has passed the quality gate.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import ContentService
from seo_engine.schemas.enums import ContentStatus

router = APIRouter(tags=["content"])


class EditorialNote(BaseModel):
    note: str = Field(default="", max_length=4000)


@router.get("/brands/{brand_id}/content")
async def list_content(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    status: str | None = Query(default=None),
) -> dict:
    rows = await ContentService(session, principal).list_assets(
        brand_id, status=status, limit=page.limit
    )
    return envelope(
        [serialize.content_asset(r) for r in rows],
        meta=page_meta(rows, limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/content/{asset_id}")
async def get_content(
    asset_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    content = ContentService(session, principal)
    asset = await content.get_asset(asset_id)
    versions = await content.list_versions(asset_id)
    current = versions[-1] if versions else None
    evaluations = []
    if current is not None:
        for kind in ("quality_evaluation", "quality_gate", "policy_review"):
            row = await content.latest_evaluation(
                asset_id, evaluation_type=kind, version_id=current.id
            )
            if row is not None:
                evaluations.append(serialize.content_evaluation(row))
    return envelope(
        {
            "asset": serialize.content_asset(asset),
            "versions": [serialize.content_version(v) for v in versions],
            "current_version_evaluations": evaluations,
            "repairs": [serialize.content_repair(r) for r in await content.list_repairs(asset_id)],
            "representations": [
                serialize.content_representation(r)
                for r in await content.list_representations(asset_id)
            ],
        },
        request_id=request.state.request_id,
    )


@router.post("/content/{asset_id}/approve")
async def approve_content(
    asset_id: uuid.UUID,
    body: EditorialNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await ContentService(session, principal).approve(asset_id, note=body.note)
    return envelope(serialize.content_asset(row), request_id=request.state.request_id)


@router.post("/content/{asset_id}/return-to-draft")
async def return_to_draft(
    asset_id: uuid.UUID,
    body: EditorialNote,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    row = await ContentService(session, principal).set_status(
        asset_id, ContentStatus.DRAFT, reason=body.note or "returned to draft by a reviewer"
    )
    return envelope(serialize.content_asset(row), request_id=request.state.request_id)
