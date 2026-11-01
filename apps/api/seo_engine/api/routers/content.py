"""Content assets, the human writing path and the editorial decision.

Agents draft, evaluate and gate content; only a person approves it. The approve
route is the one place that decision is taken, and it goes through the
non-agent content service, which still refuses approval until the current
version has passed the quality gate.

Without a language model the writer agent produces outlines, not prose. The
writing path closes that loop: a person writes a version (``POST
/content/{id}/versions``), asks for review (``POST /content/{id}/review`` runs
the evaluator, the quality gate and the policy guardian through the Agent
Runtime against that exact version), approves it, and asks for publication
(``POST /content/{id}/publish`` runs the publishing agent, whose action still
waits for approval where policy requires).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator
from seo_engine.api import serialize
from seo_engine.api.agent_calls import run_agent, run_summary
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import ContentService
from seo_engine.engines.content.generation import OUTLINE_MARKER, sections_from_markdown
from seo_engine.schemas.content import ContentDraft, ContentSection
from seo_engine.schemas.enums import ContentStatus
from seo_engine.schemas.evidence import SourceReference
from seo_engine.shared.errors import ConflictError, ValidationError

router = APIRouter(tags=["content"])

#: The synthesis mode recorded on a version a person wrote.
HUMAN_AUTHORED = "human"


class EditorialNote(BaseModel):
    note: str = Field(default="", max_length=4000)


class SectionIn(BaseModel):
    heading: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=50_000)


class VersionIn(BaseModel):
    """A version written by a person."""

    title: str = Field(min_length=1, max_length=300)
    meta_description: str = Field(default="", max_length=400)
    body_markdown: str = Field(min_length=1, max_length=200_000)
    sections: list[SectionIn] = Field(default_factory=list, max_length=100)
    cta: str | None = Field(default=None, max_length=300)
    change_summary: str = Field(default="Written by a person", min_length=1, max_length=500)
    #: URLs from the brand's source register (``GET /brands/{id}/sources``).
    #: Omitted, the previous version's citations carry over; an empty list
    #: cites nothing. A URL outside the register is refused: whether a source
    #: is verified is decided by the platform fetching it, never by assertion.
    cited_source_urls: list[str] | None = Field(default=None, max_length=50)

    @field_validator("body_markdown")
    @classmethod
    def _not_the_outline_notice(cls, value: str) -> str:
        # A person submitting the generated outline unchanged has not written
        # the piece; recording it as human prose would launder the outline.
        if OUTLINE_MARKER in value:
            raise ValueError(
                "the body still carries the outline notice; replace the outline with "
                "the written piece"
            )
        return value


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


@router.get("/brands/{brand_id}/sources")
async def list_sources(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    """The brand's source register: what a version may cite."""
    rows = await ContentService(session, principal).list_sources(brand_id, limit=page.limit)
    return envelope(
        [serialize.content_source(r) for r in rows],
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


@router.post("/content/{asset_id}/versions", status_code=201)
async def write_version(
    asset_id: uuid.UUID,
    body: VersionIn,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    """Record a new version written by a person.

    The version is attributed to the user, labelled ``human``, and — like any
    new version — sends the asset back to draft, so it must pass review again.
    """
    content = ContentService(session, principal)
    asset = await content.get_asset(asset_id)
    previous = await content.latest_version(asset_id)
    meta = (previous.metadata_json or {}) if previous is not None else {}
    # Explicit sections win; otherwise the body's own ``##`` headings are the
    # sections, so the evaluator sees the structure the person wrote.
    sections = [
        ContentSection(heading=s.heading, body=s.body) for s in body.sections
    ] or sections_from_markdown(body.body_markdown)
    if body.cited_source_urls is None:
        cited = [SourceReference.model_validate(s) for s in meta.get("cited_sources", [])]
    else:
        register = {row.url: row for row in await content.list_sources(asset.brand_id, limit=1000)}
        unknown = [url for url in body.cited_source_urls if url not in register]
        if unknown:
            raise ValidationError(
                "only sources in the brand's source register can be cited; the source and "
                "evidence agent (RES-006) registers sources and verifies them by fetching",
                {"unregistered": unknown},
            )
        cited = [
            ContentService.source_contract(register[url])
            for url in dict.fromkeys(body.cited_source_urls)
        ]
    draft = ContentDraft(
        title=body.title,
        meta_description=body.meta_description,
        slug=meta.get("slug") or asset.slug or "untitled",
        sections=sections,
        body_markdown=body.body_markdown,
        word_count=len(body.body_markdown.split()),
        cta=body.cta if body.cta is not None else meta.get("cta"),
        cited_sources=cited,
        entities=list(meta.get("entities", [])),
        schema_recommendation=meta.get("schema_recommendation"),
        synthesis_mode=HUMAN_AUTHORED,
    )
    version = await content.add_version(
        asset,
        draft,
        change_summary=body.change_summary,
        brief_id=previous.brief_id if previous is not None else None,
    )
    return envelope(
        {
            "asset": serialize.content_asset(await content.get_asset(asset_id)),
            "version": serialize.content_version(version),
        },
        request_id=request.state.request_id,
    )


@router.post("/content/{asset_id}/review")
async def review_content(
    asset_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    """Evaluate, gate and policy-check the current version through the Agent Runtime.

    The three reviewing agents run in mission order. A pass moves the asset to
    ``in_review`` for a person to approve; it never approves anything.
    """
    content = ContentService(session, principal)
    asset = await content.get_asset(asset_id)
    if asset.status != ContentStatus.DRAFT.value:
        raise ConflictError(
            "only a draft is reviewed; return the asset to draft or write a new version first",
            {"asset_id": str(asset_id), "status": asset.status},
        )
    inputs: dict[str, Any] = {"asset_ids": [str(asset_id)]}
    if asset.website_id is not None:
        inputs["website_id"] = str(asset.website_id)
    runs: list[dict[str, Any]] = []
    for agent_id, key, objective in (
        ("CNT-007", "content_evaluation", "Evaluate the current version"),
        ("CNT-009", "content_quality_gate", "Gate the current version for human review"),
        ("POL-001", "policy_review", "Check the current version against brand policy"),
    ):
        stage_inputs = dict(inputs)
        if agent_id == "POL-001":
            stage_inputs.pop("website_id", None)
        outcome = await run_agent(
            session,
            principal,
            agent_id=agent_id,
            brand_id=asset.brand_id,
            objective=objective,
            inputs=stage_inputs,
        )
        runs.append(run_summary(outcome, key))

    refreshed = await content.get_asset(asset_id)
    return envelope(
        {"asset": serialize.content_asset(refreshed), "runs": runs},
        meta={
            "next_step": (
                "A person approves the asset (POST /content/{id}/approve)."
                if refreshed.status == ContentStatus.IN_REVIEW.value
                else "Address the blocking findings, write a new version and review again."
            )
        },
        request_id=request.state.request_id,
    )


@router.post("/content/{asset_id}/publish")
async def publish_content(
    asset_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    """Ask the publishing agent (PUB-001) to publish an approved asset.

    The agent proposes ``cms.publish``; where policy or its manifest requires
    approval the action waits (approve it with ``POST /actions/{id}/approve``,
    then publish again). Nothing is published that every gate has not allowed.
    """
    content = ContentService(session, principal)
    asset = await content.get_asset(asset_id)
    outcome = await run_agent(
        session,
        principal,
        agent_id="PUB-001",
        brand_id=asset.brand_id,
        objective="Publish an approved content asset",
        inputs={"asset_ids": [str(asset_id)]},
    )
    refreshed = await content.get_asset(asset_id)
    return envelope(
        {"asset": serialize.content_asset(refreshed), "run": run_summary(outcome, "publishing")},
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
