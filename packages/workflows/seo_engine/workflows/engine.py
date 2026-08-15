"""Workflow engines.

The mission logic in :mod:`seo_engine.workflows.mission` is engine-agnostic.
This module decides *where* it runs:

``local``
    In-process, driven by the persisted task graph. Durable in the sense that
    matters: every task's state lives in PostgreSQL, so an interrupted mission
    resumes from the tasks that have not completed rather than from the start.
    This is the default and is what the test suite exercises.

``temporal``
    Delegates to a real Temporal server (see :mod:`seo_engine.workflows.temporal`).
    Selected by configuration. If the server is unreachable the engine raises —
    it never silently falls back to local execution, because a caller that asked
    for durable orchestration must not be told it got it when it did not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import AutomationPolicy
from seo_engine.shared.config import Settings, get_settings
from seo_engine.workflows.mission import MissionRunReport, MissionWorkflow
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


@dataclass(slots=True)
class MissionRunHandle:
    """What a caller gets back when a mission is dispatched."""

    mission_id: uuid.UUID
    workflow_id: str
    engine: str
    #: Present only when the engine ran the mission inline.
    report: MissionRunReport | None = None


class WorkflowEngine(Protocol):
    name: str

    async def start_mission(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        brand_id: uuid.UUID,
        objective: str,
        website_id: uuid.UUID | None = None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        options: dict[str, Any] | None = None,
        extra_services: dict[str, Any] | None = None,
        wait: bool = True,
    ) -> MissionRunHandle: ...


class LocalWorkflowEngine:
    """Runs the mission in this process, against the persisted task graph."""

    name = "local"

    async def start_mission(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        brand_id: uuid.UUID,
        objective: str,
        website_id: uuid.UUID | None = None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        options: dict[str, Any] | None = None,
        extra_services: dict[str, Any] | None = None,
        wait: bool = True,
    ) -> MissionRunHandle:
        workflow = MissionWorkflow(
            session,
            principal,
            extra_services=extra_services,
            options=options,
        )
        mission, plan = await workflow.plan(
            brand_id,
            objective,
            website_id=website_id,
            automation_policy=automation_policy,
        )
        report = await workflow.run(mission, plan) if wait else None
        return MissionRunHandle(
            mission_id=mission.id,
            workflow_id=f"mission-{mission.id}",
            engine=self.name,
            report=report,
        )

    async def resume_mission(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        mission_id: uuid.UUID,
        options: dict[str, Any] | None = None,
        extra_services: dict[str, Any] | None = None,
    ) -> MissionRunReport:
        """Continue a mission whose task graph already exists.

        Tasks that completed stay completed; only what is still ready runs. This
        is how an interrupted run recovers without repeating a crawl.
        """
        workflow = MissionWorkflow(
            session, principal, extra_services=extra_services, options=options
        )
        mission = await workflow.missions.get(mission_id)
        return await workflow.run(mission)


def engine_for(settings: Settings | None = None) -> WorkflowEngine:
    """The engine named by configuration."""
    settings = settings or get_settings()
    if settings.workflow_engine == "temporal":
        from seo_engine.workflows.temporal import TemporalWorkflowEngine

        return TemporalWorkflowEngine(settings)
    return LocalWorkflowEngine()


__all__ = ["LocalWorkflowEngine", "MissionRunHandle", "WorkflowEngine", "engine_for"]
