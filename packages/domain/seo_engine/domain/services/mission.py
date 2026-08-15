"""Mission and task services.

A mission is the platform's core object: a persistent objective the system works
against over time. Tasks are the temporary units of work it decomposes into.

The task graph is a real dependency graph — tasks become READY only when
everything they depend on has completed, so a stage that needs the crawl cannot
run before it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from seo_engine.domain.models.mission import (
    Mission,
    MissionMetric,
    MissionProgress,
    MissionTask,
    Task,
    TaskDependency,
)
from seo_engine.domain.repositories import repository_for
from seo_engine.events.bus import emit
from seo_engine.observability.audit import record_audit
from seo_engine.permissions.rbac import (
    P_MISSION_READ,
    P_MISSION_RUN,
    P_MISSION_WRITE,
    Principal,
)
from seo_engine.schemas.enums import (
    TERMINAL_TASK_STATUSES,
    AutomationPolicy,
    DataProvenance,
    MissionStatus,
    TaskPriority,
    TaskStatus,
)
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import ConflictError, ValidationError
from seo_engine.shared.ids import new_ref, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MissionRepository = repository_for(Mission)
TaskRepository = repository_for(Task)
DependencyRepository = repository_for(TaskDependency)
MissionTaskRepository = repository_for(MissionTask)
MetricRepository = repository_for(MissionMetric)
ProgressRepository = repository_for(MissionProgress)


class MissionService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.missions = MissionRepository(session, principal.tenant_id)
        self.tasks = TaskRepository(session, principal.tenant_id)
        self.dependencies = DependencyRepository(session, principal.tenant_id)
        self.mission_tasks = MissionTaskRepository(session, principal.tenant_id)
        self.metrics = MetricRepository(session, principal.tenant_id)
        self.progress = ProgressRepository(session, principal.tenant_id)

    # -- missions ---------------------------------------------------------
    async def create(
        self,
        brand_id: uuid.UUID,
        *,
        objective: str,
        mission_type: str = "generic",
        target_metric: str | None = None,
        baseline: float | None = None,
        baseline_provenance: DataProvenance | str = DataProvenance.UNKNOWN,
        baseline_source: str | None = None,
        target_value: float | None = None,
        deadline: datetime | None = None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        project_id: uuid.UUID | None = None,
    ) -> Mission:
        self.principal.require(P_MISSION_WRITE)
        if not objective.strip():
            raise ValidationError("a mission needs an objective", {})

        mission = self.missions.add(
            Mission(
                brand_id=brand_id,
                project_id=project_id,
                objective=objective.strip(),
                mission_type=mission_type,
                target_metric=target_metric,
                baseline=baseline,
                baseline_provenance=DataProvenance(baseline_provenance).value,
                baseline_source=baseline_source,
                target_value=target_value,
                deadline=deadline,
                automation_policy=AutomationPolicy(automation_policy).value,
                status=MissionStatus.CREATED,
                correlation_id=new_ref("corr"),
                created_by=self.principal.user_id,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.MISSION_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="mission",
            aggregate_id=str(mission.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            correlation_id=mission.correlation_id,
            payload={
                "objective": mission.objective,
                "target_metric": target_metric,
                "baseline": baseline,
                "baseline_provenance": mission.baseline_provenance,
            },
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="mission.create",
            resource_type="mission",
            resource_id=str(mission.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=brand_id,
            after_state={"objective": mission.objective},
        )
        return mission

    async def get(self, mission_id: uuid.UUID) -> Mission:
        self.principal.require(P_MISSION_READ)
        return await self.missions.get_or_raise(mission_id)

    async def list(self, brand_id: uuid.UUID, *, limit: int = 50) -> list[Mission]:
        self.principal.require(P_MISSION_READ)
        return list(
            await self.missions.list(
                Mission.brand_id == brand_id, limit=limit, order_by=Mission.created_at.desc()
            )
        )

    async def set_status(
        self, mission_id: uuid.UUID, status: MissionStatus | str, *, plan_summary: str = ""
    ) -> Mission:
        mission = await self.missions.get_or_raise(mission_id)
        mission.status = MissionStatus(status).value
        if plan_summary:
            mission.plan_summary = plan_summary
        if mission.status == MissionStatus.ACTIVE and mission.started_at is None:
            mission.started_at = utcnow()
        if mission.status in {MissionStatus.ACHIEVED, MissionStatus.FAILED}:
            mission.completed_at = utcnow()
        await self.session.flush()

        if mission.status == MissionStatus.ACHIEVED:
            await emit(
                self.session,
                EventType.MISSION_COMPLETED,
                tenant_id=self.principal.tenant_id,
                brand_id=mission.brand_id,
                aggregate_type="mission",
                aggregate_id=str(mission.id),
                correlation_id=mission.correlation_id,
                payload={"objective": mission.objective},
            )
        return mission

    # -- task graph -------------------------------------------------------
    async def add_task(
        self,
        mission: Mission,
        *,
        agent_id: str,
        task_type: str,
        objective: str,
        stage: str,
        sequence: int,
        inputs: dict[str, Any] | None = None,
        depends_on: list[Task] | None = None,
        priority: TaskPriority | str = TaskPriority.NORMAL,
        required_capabilities: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        required: bool = True,
        selection_reason: str = "",
    ) -> Task:
        task = self.tasks.add(
            Task(
                brand_id=mission.brand_id,
                mission_id=mission.id,
                agent_id=agent_id,
                task_type=task_type,
                objective=objective,
                status=TaskStatus.PENDING,
                priority=TaskPriority(priority).value,
                sequence=sequence,
                input_json=inputs or {},
                required_capabilities=required_capabilities or [],
                allowed_tools=allowed_tools or [],
                approval_policy=mission.automation_policy,
                correlation_id=mission.correlation_id,
            )
        )
        await self.session.flush()

        for upstream in depends_on or []:
            self.dependencies.add(TaskDependency(task_id=task.id, depends_on_task_id=upstream.id))
        self.mission_tasks.add(
            MissionTask(
                mission_id=mission.id,
                task_id=task.id,
                stage=stage,
                sequence=sequence,
                required=required,
                selection_reason=selection_reason,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.TASK_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=mission.brand_id,
            aggregate_type="task",
            aggregate_id=str(task.id),
            correlation_id=mission.correlation_id,
            payload={"agent_id": agent_id, "stage": stage, "objective": objective},
        )
        return task

    async def tasks_for(self, mission_id: uuid.UUID) -> list[Task]:
        self.principal.require(P_MISSION_READ)
        return list(await self.tasks.list(Task.mission_id == mission_id, order_by=Task.sequence))

    async def task_graph(self, mission_id: uuid.UUID) -> dict[str, Any]:
        """The graph as the UI renders it: nodes, edges and stages."""
        tasks = await self.tasks_for(mission_id)
        links = await self.mission_tasks.list(MissionTask.mission_id == mission_id)
        stage_by_task = {link.task_id: link for link in links}

        edges = await self.session.execute(
            select(TaskDependency).where(
                TaskDependency.tenant_id == self.principal.tenant_id,
                TaskDependency.task_id.in_([t.id for t in tasks] or [uuid.uuid4()]),
            )
        )
        return {
            "nodes": [
                {
                    "task_id": str(task.id),
                    "agent_id": task.agent_id,
                    "type": task.task_type,
                    "objective": task.objective,
                    "status": task.status,
                    "stage": stage_by_task[task.id].stage if task.id in stage_by_task else None,
                    "sequence": task.sequence,
                    "required": stage_by_task[task.id].required
                    if task.id in stage_by_task
                    else True,
                    "selection_reason": stage_by_task[task.id].selection_reason
                    if task.id in stage_by_task
                    else "",
                    "attempts": task.attempts,
                    "error": task.error_message,
                }
                for task in tasks
            ],
            "edges": [
                {"from": str(edge.depends_on_task_id), "to": str(edge.task_id)}
                for edge in edges.scalars()
            ],
        }

    async def stage_map(self, mission_id: uuid.UUID) -> dict[uuid.UUID, str]:
        """task_id → stage, for a workflow that needs to know which stage it is running."""
        links = await self.mission_tasks.list(MissionTask.mission_id == mission_id)
        return {link.task_id: link.stage for link in links}

    async def ready_tasks(self, mission_id: uuid.UUID) -> list[Task]:
        """Tasks whose dependencies have all completed."""
        tasks = await self.tasks_for(mission_id)
        by_id = {task.id: task for task in tasks}

        edges = await self.session.execute(
            select(TaskDependency).where(
                TaskDependency.tenant_id == self.principal.tenant_id,
                TaskDependency.task_id.in_(list(by_id) or [uuid.uuid4()]),
            )
        )
        blockers: dict[uuid.UUID, list[uuid.UUID]] = {}
        for edge in edges.scalars():
            blockers.setdefault(edge.task_id, []).append(edge.depends_on_task_id)

        ready: list[Task] = []
        for task in tasks:
            if task.status not in {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RETRY}:
                continue
            upstream = blockers.get(task.id, [])
            if all(
                by_id.get(dep) is not None and by_id[dep].status == TaskStatus.COMPLETED
                for dep in upstream
            ):
                ready.append(task)
        ready.sort(key=lambda t: t.sequence)
        return ready

    async def start_task(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        task.attempts += 1
        await self.session.flush()
        return task

    async def complete_task(self, task: Task, output: dict[str, Any]) -> Task:
        task.status = TaskStatus.COMPLETED
        task.output_json = output
        task.completed_at = utcnow()
        await self.session.flush()

        await emit(
            self.session,
            EventType.TASK_COMPLETED,
            tenant_id=self.principal.tenant_id,
            brand_id=task.brand_id,
            aggregate_type="task",
            aggregate_id=str(task.id),
            correlation_id=task.correlation_id,
            payload={"agent_id": task.agent_id},
        )
        return task

    async def fail_task(self, task: Task, error: str) -> Task:
        retryable = task.attempts < task.max_attempts
        task.status = TaskStatus.RETRY if retryable else TaskStatus.FAILED
        task.error_message = error[:4000]
        if not retryable:
            task.completed_at = utcnow()
        await self.session.flush()

        await emit(
            self.session,
            EventType.TASK_FAILED,
            tenant_id=self.principal.tenant_id,
            brand_id=task.brand_id,
            aggregate_type="task",
            aggregate_id=str(task.id),
            correlation_id=task.correlation_id,
            payload={"error": error[:500], "will_retry": retryable},
        )
        return task

    async def block_task(self, task: Task, reason: str) -> Task:
        task.status = TaskStatus.BLOCKED
        task.error_message = reason[:4000]
        await self.session.flush()
        return task

    # -- progress and metrics ---------------------------------------------
    async def record_progress(
        self,
        mission_id: uuid.UUID,
        *,
        stage: str,
        status: str,
        detail: str = "",
        payload: dict[str, Any] | None = None,
    ) -> MissionProgress:
        tasks = await self.tasks_for(mission_id)
        done = sum(1 for t in tasks if t.status in TERMINAL_TASK_STATUSES)
        percent = round(100.0 * done / len(tasks), 1) if tasks else 0.0

        record = self.progress.add(
            MissionProgress(
                mission_id=mission_id,
                stage=stage,
                status=status,
                detail=detail,
                percent_complete=percent,
                payload=payload or {},
            )
        )
        await self.session.flush()

        mission = await self.missions.get_or_raise(mission_id)
        await emit(
            self.session,
            EventType.MISSION_PROGRESSED,
            tenant_id=self.principal.tenant_id,
            brand_id=mission.brand_id,
            aggregate_type="mission",
            aggregate_id=str(mission_id),
            correlation_id=mission.correlation_id,
            payload={"stage": stage, "status": status, "percent_complete": percent},
        )
        return record

    async def record_metric(
        self,
        mission_id: uuid.UUID,
        *,
        metric: str,
        value: float | None,
        provenance: DataProvenance | str = DataProvenance.UNKNOWN,
        source: str | None = None,
        unit: str | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> MissionMetric:
        record = self.metrics.add(
            MissionMetric(
                mission_id=mission_id,
                metric=metric,
                value=value,
                unit=unit,
                provenance=DataProvenance(provenance).value,
                source=source,
                window_start=window_start,
                window_end=window_end,
                observed_at=utcnow(),
            )
        )
        await self.session.flush()
        return record

    async def metrics_for(self, mission_id: uuid.UUID) -> list[MissionMetric]:
        return list(
            await self.metrics.list(
                MissionMetric.mission_id == mission_id,
                order_by=MissionMetric.observed_at.desc(),
            )
        )

    async def progress_for(self, mission_id: uuid.UUID) -> list[MissionProgress]:
        return list(
            await self.progress.list(
                MissionProgress.mission_id == mission_id,
                order_by=MissionProgress.created_at,
            )
        )

    async def summary(self, mission_id: uuid.UUID) -> dict[str, Any]:
        """Everything the mission screen needs, in one call."""
        mission = await self.get(mission_id)
        tasks = await self.tasks_for(mission_id)
        done = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)

        return {
            "mission": mission,
            "objective": mission.objective,
            "status": mission.status,
            "baseline": {
                "value": mission.baseline,
                "provenance": mission.baseline_provenance,
                "source": mission.baseline_source,
                "note": (
                    "No baseline could be measured, so progress against a target "
                    "cannot be computed."
                    if mission.baseline is None
                    else None
                ),
            },
            "target": {"metric": mission.target_metric, "value": mission.target_value},
            "tasks": {
                "total": len(tasks),
                "completed": done,
                "failed": failed,
                "percent_complete": round(100.0 * done / len(tasks), 1) if tasks else 0.0,
            },
            "graph": await self.task_graph(mission_id),
            "progress": await self.progress_for(mission_id),
            "metrics": await self.metrics_for(mission_id),
        }

    async def assert_runnable(self, mission: Mission) -> None:
        self.principal.require(P_MISSION_RUN)
        if mission.status in {MissionStatus.ACHIEVED, MissionStatus.CANCELLED}:
            raise ConflictError("that mission is already closed", {"status": mission.status})


__all__ = ["MissionService"]
