"""Agent registry and run inspection.

What is exposed about a run is the observable record: objective, summary,
evidence, limitations, confidence, security flags. The context channels are
listed with their labels and sizes, but external untrusted content is stored
by reference only and private model reasoning is never persisted at all
(Rule 8), so neither can be served from here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request
from seo_engine.agent_registry.registry import get_registry
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.models.agents import AgentMessage, AgentOutput, AgentRun
from seo_engine.domain.models.decision import Evidence
from seo_engine.domain.repositories import repository_for
from seo_engine.shared.errors import NotFoundError

router = APIRouter(prefix="/agents", tags=["agents"])

RunRepository = repository_for(AgentRun)
OutputRepository = repository_for(AgentOutput)
MessageRepository = repository_for(AgentMessage)
EvidenceRepository = repository_for(Evidence)


@router.get("")
async def list_agents(principal: PrincipalDep, request: Request) -> dict:
    registry = get_registry()
    manifests = [registry.manifest(agent_id) for agent_id in registry.ids()]
    return envelope(
        [
            {
                "id": m.id,
                "name": m.name,
                "version": m.version,
                "description": m.description,
                "capabilities": m.capabilities,
                "tools": m.tools,
                "memory_scopes": [s.value for s in m.memory_scopes],
                "risk_level": m.risk_level.value,
                "autonomous_actions": m.autonomous_actions,
                "approval_required_for": m.approval_required_for,
                "tags": m.tags,
            }
            for m in manifests
        ],
        request_id=request.state.request_id,
    )


@router.get("/runs")
async def list_runs(
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
    brand_id: uuid.UUID | None = Query(default=None),
    mission_id: uuid.UUID | None = Query(default=None),
    agent_id: str | None = Query(default=None),
) -> dict:
    criteria = []
    if brand_id is not None:
        criteria.append(AgentRun.brand_id == brand_id)
    if mission_id is not None:
        criteria.append(AgentRun.mission_id == mission_id)
    if agent_id is not None:
        criteria.append(AgentRun.agent_id == agent_id)

    rows = await RunRepository(session, principal.tenant_id).list(
        *criteria, limit=page.limit, offset=page.offset, order_by=AgentRun.created_at.desc()
    )
    return envelope(
        [serialize.agent_run(r) for r in rows],
        meta=page_meta(list(rows), limit=page.limit, offset=page.offset),
        request_id=request.state.request_id,
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    runs = RunRepository(session, principal.tenant_id)
    run = await runs.get_or_raise(run_id)

    outputs = await OutputRepository(session, principal.tenant_id).list(
        AgentOutput.agent_run_id == run.id
    )
    messages = await MessageRepository(session, principal.tenant_id).list(
        AgentMessage.agent_run_id == run.id, order_by=AgentMessage.sequence
    )
    evidence = await EvidenceRepository(session, principal.tenant_id).list(
        Evidence.agent_run_id == run.id, limit=200
    )

    return envelope(
        {
            "run": serialize.agent_run(run),
            "outputs": [
                {
                    "output_type": o.output_type,
                    "schema_name": o.schema_name,
                    "payload": o.payload,
                }
                for o in outputs
            ],
            "evidence": [serialize.evidence_row(e) for e in evidence],
            "context_channels": [
                {
                    "sequence": m.sequence,
                    "channel": m.channel,
                    "label": m.label,
                    "is_untrusted": m.is_untrusted,
                    # Untrusted external content is stored by reference, so
                    # the content here is already only a size marker for it.
                    "content": m.content,
                }
                for m in messages
            ],
        },
        request_id=request.state.request_id,
    )


@router.get("/{agent_id}/manifest")
async def get_manifest(agent_id: str, principal: PrincipalDep, request: Request) -> dict:
    registry = get_registry()
    if agent_id not in registry.ids():
        raise NotFoundError("no such agent", {"agent_id": agent_id})
    manifest = registry.manifest(agent_id)
    return envelope(manifest.model_dump(mode="json"), request_id=request.state.request_id)
