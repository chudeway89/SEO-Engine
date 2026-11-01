"""EXE-001 — Execution Agent.

Turns recommendations into concrete actions and executes the ones a person has
approved.

It never decides strategy and never grants its own permission. Every action it
proposes goes through the policy engine, and every action type its manifest
lists in ``approval_required_for`` needs a human approval whatever policy says —
the stricter of the two always wins. It refuses to execute anything whose
approval has not been given; the decision service re-checks at the moment of
execution, and this agent reports the block rather than working around it.

Execution goes through the brand's connected CMS adapter and applies exactly
the change that was approved: the title an on-page finding proposed, the links a
cluster finding named. A recommendation without a concrete change, or a change
the platform has no safe executor for, is reported and left approved for a
person — never guessed at, and never marked executed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.integrations.cms.changes import (
    EXECUTABLE,
    ChangeNotSpecified,
    ChangeNotSupported,
    apply_change,
    missing_specification,
)
from seo_engine.schemas.agent import AgentContext, ProposedAction
from seo_engine.schemas.enums import (
    ActionStatus,
    ActionType,
    DataProvenance,
    EvidenceType,
    RecommendationStatus,
    RiskLevel,
    SynthesisMode,
)
from seo_engine.shared.errors import (
    ApprovalRequiredError,
    ConflictError,
    IntegrationError,
    IntegrationNotConnectedError,
    PolicyViolationError,
)

#: Actions already settled are reported, never re-run.
SETTLED = frozenset(
    {
        ActionStatus.EXECUTED.value,
        ActionStatus.REJECTED.value,
        ActionStatus.CANCELLED.value,
        ActionStatus.FAILED.value,
    }
)
DRAFT_ACTIONS = frozenset({ActionType.CMS_CREATE_DRAFT.value, ActionType.CONTENT_UPDATE.value})


class _CMSResolver:
    """The brand's connected CMS adapter, resolved at most once per run.

    Per-run state lives here, not on the agent: one agent instance serves every
    run, so nothing run-specific may be stored on ``self``.
    """

    def __init__(self, context: AgentContext, workspace: AgentWorkspace, brand_id: Any) -> None:
        self.context, self.workspace, self.brand_id = context, workspace, brand_id
        self._resolved = False
        self._adapter: Any = None

    async def get(self) -> Any:
        if self._resolved:
            return self._adapter
        self._resolved = True
        if not self.workspace.note_unavailable_tool("cms"):
            return None
        adapter = self.context.services.get("cms")
        if adapter is None:
            try:
                _, adapter = await self.context.service("integrations").cms_adapter(self.brand_id)
            except IntegrationNotConnectedError:
                self.workspace.limitation(
                    "No content management system is connected for this brand, so "
                    "approved changes could not be applied."
                )
                return None
        self._adapter = adapter
        return adapter


class ExecutionPlanInput(BaseModel):
    brand_id: UUID
    mission_id: UUID | None = None
    execute_approved: bool = True
    draft: dict[str, Any] | None = None


class ExecutionPlanOutput(BaseModel):
    brand_id: str
    actions_proposed: int = 0
    actions_awaiting_approval: int = 0
    actions_executed: int = 0
    actions_settled: int = 0
    not_executable: list[dict[str, str]] = Field(default_factory=list)
    blocked: list[dict[str, str]] = Field(default_factory=list)
    executed: list[dict[str, Any]] = Field(default_factory=list)
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

        output = ExecutionPlanOutput(brand_id=str(payload.brand_id))
        actions: list[Any] = []
        cms = _CMSResolver(context, workspace, payload.brand_id)

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
                    "change": spec.get("change"),
                },
                recommendation_id=recommendation.id,
                mission_id=payload.mission_id,
                executor_agent_id=self.manifest.id,
                risk=RiskLevel(recommendation.risk),
                risk_category=(spec.get("attributes") or {}).get("category", "general"),
                automation_policy=context.policy.automation_policy,
                correlation_id=context.correlation_id,
                approval_floor=self._floor(action_type),
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

            if action.status in SETTLED:
                output.actions_settled += 1
                continue
            if action.approval_required and action.approved_by is None:
                output.actions_awaiting_approval += 1
                continue
            if not payload.execute_approved:
                continue

            try:
                result = await self._execute(workspace, decisions, action, payload, cms)
            except (ApprovalRequiredError, PolicyViolationError, ConflictError) as exc:
                output.blocked.append({"action": action_type, "reason": exc.message})
                workspace.find(
                    key="execution.blocked",
                    title=f"Action blocked: {action_type}",
                    detail=exc.message,
                    severity="info",
                )
                continue
            if isinstance(result, str):
                output.not_executable.append(
                    {"action_id": str(action.id), "action": action_type, "reason": result}
                )
            elif result is not None:
                output.executed.append(result)

        output.actions_proposed = len(actions)
        output.actions_executed = len(output.executed)
        output.actions = [
            {
                "id": str(a.id),
                "type": a.action_type,
                "status": a.status,
                "approval_required": a.approval_required,
                "policy_reason": (a.policy_decision or {}).get("reason"),
            }
            for a in actions
        ]
        for item in output.not_executable:
            workspace.limitation(
                f"Approved {item['action']} was not executed: {item['reason']}. It remains "
                "approved for a person to apply."
            )

        workspace.observe(
            evidence_type=EvidenceType.SYSTEM,
            source="execution_agent",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Planned {len(actions)} action(s): {output.actions_executed} executed, "
                f"{output.actions_awaiting_approval} awaiting human approval, "
                f"{len(output.not_executable)} approved but not executable as specified, "
                f"{len(output.blocked)} blocked, {output.actions_settled} already settled."
            ),
            data={
                "proposed": len(actions),
                "executed": output.actions_executed,
                "awaiting_approval": output.actions_awaiting_approval,
                "not_executable": len(output.not_executable),
                "blocked": len(output.blocked),
            },
            provenance=DataProvenance.OBSERVED,
        )
        workspace.outputs["execution_plan"] = output.model_dump(mode="json")
        workspace.metrics["actions_proposed"] = float(len(actions))
        workspace.metrics["actions_executed"] = float(output.actions_executed)

        return (
            f"Planned {len(actions)} action(s). {output.actions_executed} were executed under "
            f"existing approval, {output.actions_awaiting_approval} await human approval, "
            f"{len(output.not_executable)} are approved but cannot be applied as specified, and "
            f"{len(output.blocked)} were blocked. Nothing was executed without the approval "
            "its policy and this agent's manifest required."
        )

    def _floor(self, action_type: str) -> str | None:
        """The manifest's approval requirement, enforced whatever policy allows."""
        if action_type in self.manifest.approval_required_for:
            return f"{self.manifest.id} declares {action_type} as requiring human approval"
        return None

    async def _execute(
        self,
        workspace: AgentWorkspace,
        decisions: Any,
        action: Any,
        payload: Any,
        resolver: _CMSResolver,
    ) -> dict[str, Any] | str | None:
        """Apply one approved action. Returns the result, a reason it cannot run, or None."""
        change = (action.payload or {}).get("change") or {}

        if action.action_type in DRAFT_ACTIONS:
            draft = payload.draft or {}
            if not str(draft.get("body_markdown") or "").strip():
                return (
                    "no written draft accompanies it; the content production mission writes "
                    "the draft, and an empty CMS draft is never created"
                )
            cms = await resolver.get()
            if cms is None:
                return None
            await decisions.mark_executing(action.id)
            try:
                response = await cms.create_draft(
                    title=draft.get("title") or action.payload.get("recommendation", "Untitled"),
                    body_markdown=draft["body_markdown"],
                    slug=draft.get("slug", "draft"),
                    metadata={"meta_description": draft.get("meta_description", "")},
                )
            except IntegrationError as exc:
                await decisions.mark_failed(action.id, exc.message)
                return None
            result = {
                "external_id": response.payload.get("id"),
                "status": response.payload.get("status"),
                "link": response.payload.get("link"),
                "notice": response.notice,
            }
            await decisions.mark_executed(action.id, result, mode=response.mode.value)
            return {"action_id": str(action.id), "action": action.action_type, **result}

        reason = missing_specification(action.action_type, action.target or {}, change)
        if reason is not None or action.action_type not in EXECUTABLE:
            return reason or f"no executor exists for {action.action_type}"

        cms = await resolver.get()
        if cms is None:
            return None
        await decisions.mark_executing(action.id)
        try:
            applied = await apply_change(
                cms, action_type=action.action_type, target=action.target or {}, change=change
            )
        except (ChangeNotSpecified, ChangeNotSupported) as exc:
            await decisions.mark_failed(action.id, str(exc), retryable=False)
            return str(exc)
        except IntegrationError as exc:
            await decisions.mark_failed(action.id, exc.message)
            workspace.limitation(
                f"{action.action_type} on {(action.target or {}).get('url')} failed in the CMS: "
                f"{exc.message}."
            )
            return None
        await decisions.mark_executed(action.id, applied.as_dict(), mode=applied.mode)
        workspace.observe(
            evidence_type=EvidenceType.API_DATA,
            source="cms",
            reference=str((action.target or {}).get("url") or action.id),
            observation=(
                f"Applied approved {action.action_type}: {len(applied.applied)} change(s) "
                f"written, {len(applied.skipped)} skipped"
                + (" in the development CMS adapter (no real site)." if applied.notice else ".")
            ),
            data=applied.as_dict(),
            provenance=(
                DataProvenance.SYNTHETIC_DEMO if applied.notice else DataProvenance.OBSERVED
            ),
        )
        if applied.notice:
            workspace.limitation(
                "The CMS is the development adapter: applied changes exist only in its "
                "in-memory store. Nothing reached a real website."
            )
        return {"action_id": str(action.id), "action": action.action_type, **applied.as_dict()}


AGENT = ExecutionAgent
