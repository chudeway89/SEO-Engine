"""Mission endpoints.

``POST /missions`` plans a mission synchronously (classification and task-graph
persistence are fast) and returns the plan, including which stages were *not*
selected and why. ``POST /missions/{id}/run`` executes the graph in the
background through the configured workflow engine and returns 202 — a crawl can
take minutes and an HTTP request is not a durable execution context.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import MissionService
from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import P_MISSION_RUN, Principal
from seo_engine.schemas.enums import AutomationPolicy
from seo_engine.shared.db import session_scope
from seo_engine.workflows.mission import MissionWorkflow

log = get_logger(__name__)

router = APIRouter(tags=["missions"])


class MissionCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=2000)
    website_id: uuid.UUID | None = None
    target_value: float | None = None
    automation_policy: AutomationPolicy = AutomationPolicy.APPROVAL_REQUIRED


def _plan_payload(plan) -> dict:
    return {
        "mission_type": plan.mission_type,
        "target_metric": plan.target_metric,
        "summary": plan.summary,
        "stages": [
            {
                "stage": s.spec.stage,
                "agent_id": s.spec.agent_id,
                "objective": s.spec.objective,
                "included": s.included,
                "reason": s.reason,
                "depends_on": s.spec.depends_on,
                "after": s.spec.after,
            }
            for s in plan.stages
        ],
    }


class StrategyPreview(BaseModel):
    objective: str | None = Field(default=None, max_length=2000)
    website_id: uuid.UUID | None = None


@router.post("/brands/{brand_id}/strategy")
async def preview_strategy(
    brand_id: uuid.UUID,
    body: StrategyPreview,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    """Preview the plan for an objective through the strategy orchestrator (ORCH-001).

    Runs the agent through the Agent Runtime — so the preview is an audited run
    with its own evidence — and creates no mission and no task.
    """
    from seo_engine.agent_runtime.runner import AgentRunner, RunRequest
    from seo_engine.domain.services.integration import IntegrationService
    from seo_engine.workflows.services import build_services

    connected = await IntegrationService(session, principal).connected_providers(brand_id)
    inputs: dict = {"brand_id": str(brand_id)}
    if body.objective:
        inputs["objective"] = body.objective
    if body.website_id:
        inputs["website_id"] = str(body.website_id)
    outcome = await AgentRunner(session).run(
        RunRequest(
            agent_id="ORCH-001",
            objective="Preview the mission plan for an objective",
            principal=principal,
            brand_id=brand_id,
            inputs=inputs,
            services=build_services(session, principal),
            available_integrations=connected,
        )
    )
    result = outcome.result
    return envelope(
        {
            "agent_run_id": str(outcome.run.id),
            "summary": result.summary,
            "strategy": result.outputs.get("strategy", {}),
            "next_tasks": [t.model_dump(mode="json") for t in result.next_tasks],
            "recommendations": [r.model_dump(mode="json") for r in result.recommendations],
            "limitations": result.limitations,
        },
        request_id=request.state.request_id,
    )


@router.post("/brands/{brand_id}/missions", status_code=201)
async def create_mission(
    brand_id: uuid.UUID,
    body: MissionCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    workflow = MissionWorkflow(session, principal)
    mission, plan = await workflow.plan(
        brand_id,
        body.objective,
        website_id=body.website_id,
        automation_policy=body.automation_policy,
        target_value=body.target_value,
    )
    return envelope(
        {"mission": serialize.mission(mission), "plan": _plan_payload(plan)},
        request_id=request.state.request_id,
    )


async def _run_mission(principal: Principal, mission_id: uuid.UUID) -> None:
    """Background execution with its own transactional session."""
    try:
        async with session_scope() as session:
            workflow = MissionWorkflow(session, principal)
            mission = await workflow.missions.get(mission_id)
            await workflow.run(mission)
    except Exception:
        log.exception("background_mission_failed", mission_id=str(mission_id))


@router.post("/missions/{mission_id}/run", status_code=202)
async def run_mission(
    mission_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
    background: BackgroundTasks,
) -> dict:
    principal.require(P_MISSION_RUN)
    service = MissionService(session, principal)
    mission = await service.get(mission_id)
    await service.assert_runnable(mission)

    background.add_task(_run_mission, principal, mission.id)
    return envelope(
        {
            "status": "accepted",
            "mission_id": str(mission.id),
            "poll": f"/api/v1/missions/{mission.id}",
        },
        request_id=request.state.request_id,
    )


@router.get("/brands/{brand_id}/missions")
async def list_missions(
    brand_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    page: PageDep,
    request: Request,
) -> dict:
    rows = await MissionService(session, principal).list_missions(brand_id, limit=page.limit)
    return envelope(
        [serialize.mission(m) for m in rows],
        meta=page_meta(rows, limit=page.limit, offset=0),
        request_id=request.state.request_id,
    )


@router.get("/missions/{mission_id}")
async def get_mission(
    mission_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    service = MissionService(session, principal)
    summary = await service.summary(mission_id)
    return envelope(
        {
            "mission": serialize.mission(summary["mission"]),
            "baseline": summary["baseline"],
            "target": summary["target"],
            "tasks": summary["tasks"],
            "graph": summary["graph"],
            "progress": [serialize.mission_progress(p) for p in summary["progress"]],
            "metrics": [serialize.mission_metric(m) for m in summary["metrics"]],
        },
        request_id=request.state.request_id,
    )


@router.get("/missions/{mission_id}/graph")
async def mission_graph(
    mission_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    graph = await MissionService(session, principal).task_graph(mission_id)
    return envelope(graph, request_id=request.state.request_id)


@router.get("/missions/{mission_id}/progress")
async def mission_progress(
    mission_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    service = MissionService(session, principal)
    await service.get(mission_id)
    rows = await service.progress_for(mission_id)
    return envelope(
        [serialize.mission_progress(p) for p in rows], request_id=request.state.request_id
    )
