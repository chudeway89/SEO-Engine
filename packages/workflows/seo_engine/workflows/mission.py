"""The mission workflow.

A mission is planned once and then executed stage by stage:

    plan → persist task graph → for each ready task: run the agent through the
    Agent Runtime → record its output → hand the relevant parts downstream →
    measure → close.

Three properties matter more than the mechanics:

* **Every step goes through the Agent Runtime.** The workflow decides *what*
  runs and *in what order*; it never performs an agent's work itself, never
  calls a tool, and never writes an agent's findings on its behalf.
* **A failed stage does not become a silent gap.** It is retried up to the
  task's attempt limit, then recorded as failed, and every stage that depended
  on it is blocked with that dependency named. Downstream agents therefore see
  the input as absent — which they report — rather than as empty.
* **The baseline is measured or it does not exist.** If no analytics provider
  returned a figure, the mission carries no baseline and says so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from seo_engine.agent_runtime.runner import AgentRunner, RunRequest
from seo_engine.domain.models.mission import Mission, Task
from seo_engine.domain.services import BrandService
from seo_engine.domain.services.integration import IntegrationService
from seo_engine.domain.services.mission import MissionService
from seo_engine.domain.services.website import WebsiteService
from seo_engine.observability.logging import get_logger, log_context
from seo_engine.orchestration.orchestrator import (
    STAGE_SPECS,
    MissionPlan,
    Orchestrator,
    build_task_graph,
)
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import (
    AutomationPolicy,
    DataProvenance,
    MissionStatus,
    TaskStatus,
)
from seo_engine.shared.errors import SEOEngineError
from seo_engine.workflows.services import build_services
from seo_engine.workflows.steps import measured_baseline, stage_inputs
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


@dataclass(slots=True)
class StepResult:
    stage: str
    agent_id: str
    task_id: str
    status: str
    summary: str = ""
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    security_flags: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(slots=True)
class MissionRunReport:
    mission_id: str
    objective: str
    mission_type: str
    status: str
    steps: list[StepResult] = field(default_factory=list)
    excluded_stages: list[dict[str, str]] = field(default_factory=list)
    baseline: dict[str, Any] | None = None
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan_summary: str = ""

    @property
    def completed_stages(self) -> list[str]:
        return [s.stage for s in self.steps if s.succeeded]

    @property
    def failed_stages(self) -> list[str]:
        return [s.stage for s in self.steps if not s.succeeded]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "objective": self.objective,
            "mission_type": self.mission_type,
            "status": self.status,
            "plan_summary": self.plan_summary,
            "baseline": self.baseline,
            "excluded_stages": self.excluded_stages,
            "steps": [
                {
                    "stage": s.stage,
                    "agent_id": s.agent_id,
                    "task_id": s.task_id,
                    "status": s.status,
                    "summary": s.summary,
                    "confidence": s.confidence,
                    "evidence": len(s.evidence_refs),
                    "limitations": s.limitations,
                    "security_flags": s.security_flags,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


class MissionWorkflow:
    """Plans and executes one mission. Engine-agnostic by design."""

    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        runner: AgentRunner | None = None,
        extra_services: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.runner = runner or AgentRunner(session)
        self.extra_services = extra_services or {}
        self.options = options or {}
        self.missions = MissionService(session, principal)

    # -- planning ---------------------------------------------------------
    async def plan(
        self,
        brand_id: uuid.UUID,
        objective: str,
        *,
        website_id: uuid.UUID | None = None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        project_id: uuid.UUID | None = None,
        target_value: float | None = None,
    ) -> tuple[Mission, MissionPlan]:
        """Classify the objective, select the stages, and persist the task graph."""
        brands = BrandService(self.session, self.principal)
        websites = WebsiteService(self.session, self.principal)
        integrations = IntegrationService(self.session, self.principal)

        resolved_website_id = website_id
        if resolved_website_id is None:
            existing = await websites.list_websites(brand_id)
            resolved_website_id = existing[0].id if existing else None

        competitors = await brands.list_competitors(brand_id)
        connected = await integrations.connected_providers(brand_id)

        plan = Orchestrator().plan(
            objective,
            has_website=resolved_website_id is not None,
            connected_integrations=connected,
            has_competitors=bool(competitors),
        )

        mission = await self.missions.create(
            brand_id,
            objective=objective,
            mission_type=plan.mission_type,
            target_metric=plan.target_metric,
            target_value=target_value,
            automation_policy=automation_policy,
            project_id=project_id,
        )
        mission.plan_summary = plan.summary
        mission.strategy = {
            "website_id": str(resolved_website_id) if resolved_website_id else None,
            "stages": [s.spec.stage for s in plan.included],
            "excluded": [{"stage": s.spec.stage, "reason": s.reason} for s in plan.excluded],
        }
        await build_task_graph(
            self.missions,
            mission,
            plan,
            inputs={
                "brand_id": str(brand_id),
                **({"website_id": str(resolved_website_id)} if resolved_website_id else {}),
            },
        )
        await self.session.flush()

        log.info(
            "mission_planned",
            mission_id=str(mission.id),
            mission_type=plan.mission_type,
            stages=len(plan.included),
            excluded=len(plan.excluded),
        )
        return mission, plan

    # -- execution --------------------------------------------------------
    async def run(
        self,
        mission: Mission,
        plan: MissionPlan | None = None,
        *,
        commit_each_step: bool = False,
    ) -> MissionRunReport:
        """Execute every ready task until the graph is exhausted."""
        await self.missions.assert_runnable(mission)
        await self.missions.set_status(mission.id, MissionStatus.ACTIVE)

        report = MissionRunReport(
            mission_id=str(mission.id),
            objective=mission.objective,
            mission_type=mission.mission_type,
            status=MissionStatus.ACTIVE.value,
            plan_summary=mission.plan_summary or (plan.summary if plan else ""),
            excluded_stages=(
                [{"stage": s.spec.stage, "reason": s.reason} for s in plan.excluded] if plan else []
            ),
        )

        website_id = mission_website_id(mission)
        stage_by_task = await self.missions.stage_map(mission.id)

        with log_context(mission_id=str(mission.id), correlation_id=mission.correlation_id):
            while True:
                ready = await self.missions.ready_tasks(mission.id)
                if not ready:
                    break

                progressed = False
                for task in ready:
                    stage = stage_by_task.get(task.id, task.task_type)
                    step = await self.execute_stage(mission, task, stage, report, website_id)
                    report.steps.append(step)
                    progressed = True
                    if commit_each_step:
                        await self.session.commit()
                if not progressed:  # pragma: no cover - defensive
                    break

            await self.block_unreachable_tasks(mission, stage_by_task, report)
            report.baseline = await self.record_baseline(mission, report)
            report.status = await self.close(mission, report)

        if commit_each_step:
            await self.session.commit()
        return report

    # ------------------------------------------------------------------
    async def execute_stage(
        self,
        mission: Mission,
        task: Task,
        stage: str,
        report: MissionRunReport,
        website_id: uuid.UUID | None,
    ) -> StepResult:
        await self.missions.start_task(task)
        await self.missions.record_progress(
            mission.id, stage=stage, status="running", detail=task.objective
        )

        inputs = stage_inputs(
            stage,
            brand_id=mission.brand_id,
            mission_id=mission.id,
            website_id=website_id,
            outputs=report.outputs,
            options=self.options,
        )
        inherited = [ref for step in report.steps for ref in step.evidence_refs]
        integrations = IntegrationService(self.session, self.principal)
        connected = await integrations.connected_providers(mission.brand_id)

        request = RunRequest(
            agent_id=task.agent_id,
            objective=task.objective,
            principal=self.principal,
            task_id=task.id,
            brand_id=mission.brand_id,
            project_id=mission.project_id,
            mission_id=mission.id,
            workflow_id=f"mission-{mission.id}",
            correlation_id=mission.correlation_id,
            inputs=inputs,
            services=build_services(self.session, self.principal, extra=self.extra_services),
            available_integrations=connected,
            automation_policy=mission.automation_policy,
            inherited_evidence_refs=inherited[-40:],
        )

        try:
            outcome = await self.runner.run(request)
        except Exception as exc:
            code = exc.code if isinstance(exc, SEOEngineError) else type(exc).__name__
            await self.missions.fail_task(task, f"{code}: {exc}")
            await self.missions.record_progress(
                mission.id, stage=stage, status="failed", detail=str(exc)[:500]
            )
            log.error("mission_stage_failed", stage=stage, agent_id=task.agent_id, error_code=code)
            return StepResult(
                stage=stage,
                agent_id=task.agent_id,
                task_id=str(task.id),
                status=TaskStatus.FAILED.value,
                error=str(exc)[:1000],
                error_code=code,
            )

        result = outcome.result
        report.outputs[stage] = dict(result.outputs)
        await self.missions.complete_task(
            task,
            {
                "summary": result.summary,
                "confidence": result.confidence,
                "evidence": len(result.evidence),
                "limitations": result.limitations,
            },
        )
        await self.missions.record_progress(
            mission.id,
            stage=stage,
            status="completed",
            detail=result.summary[:2000],
            payload={"confidence": result.confidence, "agent_id": task.agent_id},
        )
        for name, value in result.metrics.items():
            await self.missions.record_metric(
                mission.id,
                metric=name,
                value=value,
                provenance=DataProvenance.OBSERVED,
                source=f"agent:{task.agent_id}",
            )

        return StepResult(
            stage=stage,
            agent_id=task.agent_id,
            task_id=str(task.id),
            status=result.status,
            summary=result.summary,
            confidence=result.confidence,
            evidence_refs=list(outcome.evidence_refs),
            limitations=list(result.limitations),
            security_flags=list(result.security_flags),
        )

    async def block_unreachable_tasks(
        self,
        mission: Mission,
        stage_by_task: dict[uuid.UUID, str],
        report: MissionRunReport,
    ) -> None:
        """Any task still pending has an upstream dependency that never completed."""
        failed = {s.stage for s in report.steps if not s.succeeded}
        for task in await self.missions.tasks_for(mission.id):
            if task.status not in {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RETRY}:
                continue
            stage = stage_by_task.get(task.id, task.task_type)
            spec = STAGE_SPECS.get(stage)
            blockers = sorted(set(spec.depends_on) & failed) if spec else []
            reason = (
                f"Blocked because {', '.join(blockers)} did not complete."
                if blockers
                else "Blocked because an upstream task did not complete."
            )
            await self.missions.block_task(task, reason)
            await self.missions.record_progress(
                mission.id, stage=stage, status="blocked", detail=reason
            )
            report.steps.append(
                StepResult(
                    stage=stage,
                    agent_id=task.agent_id,
                    task_id=str(task.id),
                    status=TaskStatus.BLOCKED.value,
                    error=reason,
                    error_code="dependency_not_met",
                )
            )

    async def record_baseline(
        self, mission: Mission, report: MissionRunReport
    ) -> dict[str, Any] | None:
        baseline = measured_baseline(report.outputs)
        if baseline is None:
            await self.missions.record_progress(
                mission.id,
                stage="measurement",
                status="unavailable",
                detail=(
                    "No connected analytics provider returned a figure, so this mission "
                    "has no baseline. Progress against a target cannot be reported, and "
                    "no baseline has been estimated."
                ),
            )
            return None

        mission.baseline = float(baseline["value"])
        mission.baseline_provenance = DataProvenance(baseline["provenance"]).value
        mission.baseline_source = baseline.get("source")
        if not mission.target_metric:
            mission.target_metric = baseline["metric"]
        await self.missions.record_metric(
            mission.id,
            metric=baseline["metric"],
            value=float(baseline["value"]),
            provenance=baseline["provenance"],
            source=baseline.get("source"),
        )
        await self.session.flush()
        return baseline

    async def close(self, mission: Mission, report: MissionRunReport) -> str:
        """A mission is never marked achieved by the workflow itself.

        Achievement is a measured outcome over time, not the completion of a
        plan. The workflow reports that the planned work ran; whether the
        objective was met is decided by the measurement loop against the target
        metric.
        """
        if report.failed_stages and not report.completed_stages:
            status = MissionStatus.FAILED
            summary = "Every planned stage failed; no findings were produced."
        elif report.failed_stages:
            status = MissionStatus.MONITORING
            summary = (
                f"{len(report.completed_stages)} stage(s) completed and "
                f"{len(report.failed_stages)} did not: "
                + ", ".join(report.failed_stages)
                + ". The findings below cover the stages that ran."
            )
        else:
            status = MissionStatus.MONITORING
            summary = (
                f"All {len(report.completed_stages)} planned stage(s) completed. "
                "The mission now measures its target metric over time."
            )

        await self.missions.record_progress(
            mission.id, stage="mission", status=status.value, detail=summary
        )
        await self.missions.set_status(mission.id, status)
        return status.value


def mission_website_id(mission: Mission) -> uuid.UUID | None:
    """The website the mission was planned against, if any."""
    raw = (mission.strategy or {}).get("website_id")
    return uuid.UUID(str(raw)) if raw else None


__all__ = ["MissionRunReport", "MissionWorkflow", "StepResult", "mission_website_id"]
