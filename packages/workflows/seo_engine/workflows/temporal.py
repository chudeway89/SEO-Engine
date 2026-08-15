"""Temporal orchestration of the mission workflow.

Temporal owns *durability and retry*; it does not own the mission logic. The
workflow definition below contains no SEO reasoning at all — it calls activities,
and every activity opens its own database session and delegates to the same
:class:`~seo_engine.workflows.mission.MissionWorkflow` code the local engine
uses. That split is deliberate: the behaviour under test locally is the
behaviour that runs in production, and Temporal's determinism constraints never
reach into domain code.

The principal is passed by identity, never by trusting the payload: the activity
re-derives the caller's permissions from the tenant and role it is given, so a
tampered workflow argument cannot escalate what an agent may do.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import AutomationPolicy, Role
from seo_engine.shared.config import Settings, get_settings
from seo_engine.shared.errors import ConfigurationError
from seo_engine.workflows.engine import MissionRunHandle
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

log = get_logger(__name__)

#: The queue both the engine and the worker use.  Kept in configuration so a
#: deployment can isolate tenants onto separate queues without a code change.
DEFAULT_TASK_QUEUE = "seo-engine"


# ---------------------------------------------------------------------------
# Serialisable payloads
# ---------------------------------------------------------------------------
@dataclass
class PrincipalPayload:
    user_id: str
    tenant_id: str
    email: str
    role: str

    def to_principal(self) -> Principal:
        return Principal.build(
            user_id=uuid.UUID(self.user_id),
            tenant_id=uuid.UUID(self.tenant_id),
            email=self.email,
            role=Role(self.role),
        )

    @classmethod
    def of(cls, principal: Principal) -> PrincipalPayload:
        return cls(
            user_id=str(principal.user_id),
            tenant_id=str(principal.tenant_id),
            email=principal.email,
            role=principal.role.value,
        )


@dataclass
class MissionRequest:
    principal: PrincipalPayload
    brand_id: str
    objective: str
    website_id: str | None = None
    automation_policy: str = AutomationPolicy.APPROVAL_REQUIRED.value
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanResult:
    mission_id: str
    mission_type: str
    plan_summary: str
    stages: list[str] = field(default_factory=list)


@dataclass
class StageRequest:
    principal: PrincipalPayload
    mission_id: str
    task_id: str
    stage: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReadyRequest:
    principal: PrincipalPayload
    mission_id: str


@dataclass
class ReadyTask:
    task_id: str
    stage: str
    agent_id: str


# ---------------------------------------------------------------------------
# Activities — these are where the real work happens
# ---------------------------------------------------------------------------
@activity.defn(name="seo_engine.plan_mission")
async def plan_mission(request: MissionRequest) -> PlanResult:
    from seo_engine.shared.db import session_scope
    from seo_engine.workflows.mission import MissionWorkflow

    principal = request.principal.to_principal()
    async with session_scope() as session:
        flow = MissionWorkflow(session, principal, options=request.options)
        mission, plan = await flow.plan(
            uuid.UUID(request.brand_id),
            request.objective,
            website_id=uuid.UUID(request.website_id) if request.website_id else None,
            automation_policy=request.automation_policy,
        )
        return PlanResult(
            mission_id=str(mission.id),
            mission_type=plan.mission_type,
            plan_summary=plan.summary,
            stages=[s.spec.stage for s in plan.included],
        )


@activity.defn(name="seo_engine.next_ready_tasks")
async def next_ready_tasks(request: ReadyRequest) -> list[ReadyTask]:
    from seo_engine.domain.services.mission import MissionService
    from seo_engine.shared.db import session_scope

    principal = request.principal.to_principal()
    mission_id = uuid.UUID(request.mission_id)
    async with session_scope() as session:
        missions = MissionService(session, principal)
        stages = await missions.stage_map(mission_id)
        return [
            ReadyTask(
                task_id=str(task.id),
                stage=stages.get(task.id, task.task_type),
                agent_id=task.agent_id,
            )
            for task in await missions.ready_tasks(mission_id)
        ]


@activity.defn(name="seo_engine.run_stage")
async def run_stage(request: StageRequest) -> dict[str, Any]:
    """Run exactly one stage. Its own transaction, so a failure loses only it."""
    from seo_engine.domain.services.mission import MissionService
    from seo_engine.shared.db import session_scope
    from seo_engine.workflows.mission import MissionRunReport, MissionWorkflow

    principal = request.principal.to_principal()
    mission_id = uuid.UUID(request.mission_id)
    async with session_scope() as session:
        flow = MissionWorkflow(session, principal, options=request.options)
        missions = MissionService(session, principal)
        mission = await missions.get(mission_id)
        tasks = {t.id: t for t in await missions.tasks_for(mission_id)}
        task = tasks[uuid.UUID(request.task_id)]

        report = MissionRunReport(
            mission_id=str(mission.id),
            objective=mission.objective,
            mission_type=mission.mission_type,
            status=mission.status,
        )
        report.outputs = await _load_prior_outputs(missions, mission_id)
        step = await flow.execute_stage(
            mission,
            task,
            request.stage,
            report,
            _website_id(mission),
        )
        return {
            "stage": step.stage,
            "agent_id": step.agent_id,
            "task_id": step.task_id,
            "status": step.status,
            "summary": step.summary,
            "confidence": step.confidence,
            "evidence_refs": step.evidence_refs,
            "limitations": step.limitations,
            "error": step.error,
        }


@activity.defn(name="seo_engine.finalise_mission")
async def finalise_mission(request: ReadyRequest) -> dict[str, Any]:
    from seo_engine.domain.services.mission import MissionService
    from seo_engine.shared.db import session_scope
    from seo_engine.workflows.mission import MissionRunReport, MissionWorkflow

    principal = request.principal.to_principal()
    mission_id = uuid.UUID(request.mission_id)
    async with session_scope() as session:
        flow = MissionWorkflow(session, principal)
        missions = MissionService(session, principal)
        mission = await missions.get(mission_id)
        report = MissionRunReport(
            mission_id=str(mission.id),
            objective=mission.objective,
            mission_type=mission.mission_type,
            status=mission.status,
            plan_summary=mission.plan_summary,
        )
        report.outputs = await _load_prior_outputs(missions, mission_id)
        await flow.block_unreachable_tasks(mission, await missions.stage_map(mission_id), report)
        report.baseline = await flow.record_baseline(mission, report)
        report.status = await flow.close(mission, report)
        return report.as_dict()


async def _load_prior_outputs(missions: Any, mission_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Rebuild what upstream stages produced, from the persisted agent outputs.

    Under Temporal each activity is a separate process, so stage-to-stage state
    is read back from the database rather than held in memory. The agent runs
    are the record; nothing is reconstructed or guessed.
    """
    from seo_engine.domain.models.agents import AgentOutput, AgentRun
    from seo_engine.domain.repositories import repository_for

    runs_repo = repository_for(AgentRun)(missions.session, missions.principal.tenant_id)
    outputs_repo = repository_for(AgentOutput)(missions.session, missions.principal.tenant_id)
    stages = await missions.stage_map(mission_id)
    tasks = {t.id: t for t in await missions.tasks_for(mission_id)}

    collected: dict[str, dict[str, Any]] = {}
    for run in await runs_repo.list(
        AgentRun.mission_id == mission_id, order_by=AgentRun.started_at
    ):
        task = tasks.get(run.task_id)
        stage = stages.get(run.task_id) or (task.task_type if task else run.agent_id)
        rows = await outputs_repo.list(AgentOutput.agent_run_id == run.id)
        for row in rows:
            payload = row.payload or {}
            if isinstance(payload.get("outputs"), dict):
                collected[stage] = payload["outputs"]
    return collected


def _website_id(mission: Any) -> uuid.UUID | None:
    from seo_engine.workflows.mission import mission_website_id

    return mission_website_id(mission)


# ---------------------------------------------------------------------------
# Workflow definition — deterministic, no I/O, no domain logic
# ---------------------------------------------------------------------------
@workflow.defn(name="SEOEngineMission")
class MissionTemporalWorkflow:
    @workflow.run
    async def run(self, request: MissionRequest) -> dict[str, Any]:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=5),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(minutes=5),
            maximum_attempts=3,
        )
        plan = await workflow.execute_activity(
            plan_mission,
            request,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry,
        )
        ready_request = ReadyRequest(principal=request.principal, mission_id=plan.mission_id)

        steps: list[dict[str, Any]] = []
        while True:
            ready = await workflow.execute_activity(
                next_ready_tasks,
                ready_request,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry,
            )
            if not ready:
                break
            for task in ready:
                steps.append(
                    await workflow.execute_activity(
                        run_stage,
                        StageRequest(
                            principal=request.principal,
                            mission_id=plan.mission_id,
                            task_id=task.task_id,
                            stage=task.stage,
                            options=request.options,
                        ),
                        # A crawl or a provider sync is slow; the timeout is
                        # generous, and the activity's own limits bound it.
                        start_to_close_timeout=timedelta(minutes=30),
                        retry_policy=retry,
                    )
                )

        report = await workflow.execute_activity(
            finalise_mission,
            ready_request,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry,
        )
        report["steps"] = steps
        return report


ACTIVITIES = [plan_mission, next_ready_tasks, run_stage, finalise_mission]
WORKFLOWS = [MissionTemporalWorkflow]


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------
class TemporalWorkflowEngine:
    """Dispatches missions to a Temporal server.

    If the server cannot be reached, this raises. It does not fall back to local
    execution: a caller that configured Temporal has asked for durable
    orchestration, and quietly giving them something else would be a lie about
    the guarantee they are relying on.
    """

    name = "temporal"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def _client(self) -> Any:
        from temporalio.client import Client

        try:
            return await Client.connect(
                self.settings.temporal_address,
                namespace=self.settings.temporal_namespace,
            )
        except Exception as exc:
            raise ConfigurationError(
                "the workflow engine is configured as 'temporal' but the Temporal "
                f"server at {self.settings.temporal_address} could not be reached: {exc}. "
                "Start Temporal, or set WORKFLOW_ENGINE=local.",
                {"address": self.settings.temporal_address},
            ) from exc

    async def start_mission(
        self,
        session: Any,
        principal: Principal,
        *,
        brand_id: uuid.UUID,
        objective: str,
        website_id: uuid.UUID | None = None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        options: dict[str, Any] | None = None,
        extra_services: dict[str, Any] | None = None,
        wait: bool = False,
    ) -> MissionRunHandle:
        if extra_services:
            raise ConfigurationError(
                "the Temporal engine runs activities in a worker process and cannot "
                "receive in-memory service overrides; configure the worker instead",
                {"keys": sorted(extra_services)},
            )

        client = await self._client()
        request = MissionRequest(
            principal=PrincipalPayload.of(principal),
            brand_id=str(brand_id),
            objective=objective,
            website_id=str(website_id) if website_id else None,
            automation_policy=AutomationPolicy(automation_policy).value,
            options=options or {},
        )
        workflow_id = f"mission-{principal.tenant_id}-{uuid.uuid4()}"
        handle = await client.start_workflow(
            MissionTemporalWorkflow.run,
            request,
            id=workflow_id,
            task_queue=self.settings.temporal_task_queue or DEFAULT_TASK_QUEUE,
        )
        log.info("temporal_mission_started", workflow_id=workflow_id)

        mission_id: uuid.UUID | None = None
        if wait:
            result = await handle.result()
            mission_id = uuid.UUID(result["mission_id"])
        return MissionRunHandle(
            mission_id=mission_id or uuid.UUID(int=0),
            workflow_id=workflow_id,
            engine=self.name,
        )


async def run_worker(settings: Settings | None = None) -> None:  # pragma: no cover - long running
    """Entry point for the Temporal worker process."""
    from temporalio.worker import Worker

    settings = settings or get_settings()
    engine = TemporalWorkflowEngine(settings)
    client = await engine._client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue or DEFAULT_TASK_QUEUE,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
    )
    log.info("temporal_worker_started", task_queue=settings.temporal_task_queue)
    await worker.run()


__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "MissionRequest",
    "MissionTemporalWorkflow",
    "PrincipalPayload",
    "TemporalWorkflowEngine",
    "run_worker",
]
