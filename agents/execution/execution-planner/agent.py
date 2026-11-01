"""EXE-001 — Execution Agent.

Turns approved recommendations into concrete actions and executes the ones that
are already approved.

It never decides strategy and never grants its own permission. Every action it
proposes goes through the policy engine, and it refuses to execute anything
whose approval requirement has not been satisfied — the domain service raises,
and this agent reports the block rather than working around it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.schemas.agent import AgentContext, ProposedAction
from seo_engine.schemas.enums import (
    ActionType,
    EvidenceType,
    IntegrationProvider,
    RecommendationStatus,
    RiskLevel,
    SynthesisMode,
)
from seo_engine.shared.errors import ApprovalRequiredError, PolicyViolationError


class ExecutionPlanInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    execute_approved: bool = True


class ExecutionPlanOutput(BaseModel):
    brand_id: str
    actions_proposed: int = 0
    actions_awaiting_approval: int = 0
    actions_executed: int = 0
    blocked: list[dict[str, str]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ExecutionPlanInput.model_validate(context.inputs)
        decisions = context.service("decisions")

        approved = await decisions.list_recommendations(
            payload.brand_id, status=RecommendationStatus.APPROVED.value, limit=25
        )
        proposed_only = await decisions.list_recommendations(
            payload.brand_id, status=RecommendationStatus.PROPOSED.value, limit=25
        )

        if not approved and not proposed_only:
            workspace.limitation("There are no recommendations to plan execution for.")
            return "No recommendations are available, so no execution plan was produced."

        actions: list[Any] = []
        awaiting = 0
        executed = 0
        blocked: list[dict[str, str]] = []

        for recommendation in [*approved, *proposed_only]:
            spec = recommendation.proposed_action or {}
            action_type = spec.get("action_type")
            if not action_type:
                continue

            action = await decisions.propose_action(
                brand_id=payload.brand_id,
                action_type=action_type,
                target=spec.get("target") or {},
                payload={
                    "recommendation": recommendation.title,
                    "reason": recommendation.reason,
                },
                recommendation_id=recommendation.id,
                mission_id=payload.mission_id,
                executor_agent_id=self.manifest.id,
                risk=RiskLevel(recommendation.risk),
                risk_category=(spec.get("attributes") or {}).get("category", "general"),
                automation_policy=context.policy.automation_policy,
                provider=IntegrationProvider.GENERIC_CMS.value
                if action_type.startswith("cms.")
                else None,
                correlation_id=context.correlation_id,
            )
            actions.append(action)
            workspace.actions.append(
                ProposedAction(
                    action_type=action_type,
                    target=action.target,
                    payload=action.payload,
                    risk=RiskLevel(action.risk),
                    idempotency_key=action.idempotency_key,
                )
            )

            if action.approval_required and action.approved_by is None:
                awaiting += 1
                continue

            if not payload.execute_approved:
                continue

            try:
                executed += await self._execute(context, workspace, decisions, action)
            except (ApprovalRequiredError, PolicyViolationError) as exc:
                blocked.append({"action": action_type, "reason": exc.message})
                workspace.find(
                    key="execution.blocked",
                    title=f"Action blocked: {action_type}",
                    detail=exc.message,
                    severity="info",
                )

        workspace.observe(
            evidence_type=EvidenceType.SYSTEM,
            source="execution_agent",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Planned {len(actions)} action(s): {executed} executed, {awaiting} "
                f"awaiting human approval, {len(blocked)} blocked by policy."
            ),
            data={
                "proposed": len(actions),
                "executed": executed,
                "awaiting_approval": awaiting,
                "blocked": len(blocked),
            },
        )

        output = ExecutionPlanOutput(
            brand_id=str(payload.brand_id),
            actions_proposed=len(actions),
            actions_awaiting_approval=awaiting,
            actions_executed=executed,
            blocked=blocked,
            actions=[
                {
                    "id": str(a.id),
                    "type": a.action_type,
                    "status": a.status,
                    "approval_required": a.approval_required,
                    "policy_reason": (a.policy_decision or {}).get("reason"),
                }
                for a in actions
            ],
        )
        workspace.outputs["execution_plan"] = output.model_dump(mode="json")
        workspace.metrics["actions_proposed"] = float(len(actions))
        workspace.metrics["actions_executed"] = float(executed)

        return (
            f"Planned {len(actions)} action(s). {executed} were executed under existing "
            f"approval, {awaiting} await human approval, and {len(blocked)} were blocked "
            "by policy. Nothing was executed without the approval its policy required."
        )

    async def _execute(
        self, context: AgentContext, workspace: AgentWorkspace, decisions: Any, action: Any
    ) -> int:
        """Execute one approved action through the integration layer."""
        if action.action_type not in {
            ActionType.CMS_CREATE_DRAFT.value,
            ActionType.CONTENT_UPDATE.value,
        }:
            # Everything else needs a connector this build does not implement;
            # say so rather than pretending it ran.
            workspace.limitation(
                f"No executor is implemented for {action.action_type}; the action "
                "remains approved and pending an implementation."
            )
            return 0

        if not workspace.note_unavailable_tool("cms"):
            return 0

        cms = context.services.get("cms")
        if cms is None:
            workspace.limitation(
                "No CMS adapter was provided to this run, so approved content actions "
                "could not be executed."
            )
            return 0

        await decisions.mark_executing(action.id)
        draft = context.inputs.get("draft") or {}
        response = await cms.create_draft(
            title=draft.get("title") or action.payload.get("recommendation", "Untitled"),
            body_markdown=draft.get("body_markdown", ""),
            slug=draft.get("slug", "draft"),
            metadata={"meta_description": draft.get("meta_description", "")},
        )
        await decisions.mark_executed(
            action.id,
            {
                "external_id": response.payload.get("id"),
                "status": response.payload.get("status"),
                "link": response.payload.get("link"),
                "notice": response.notice,
            },
            mode=response.mode.value,
        )
        return 1


AGENT = ExecutionAgent
