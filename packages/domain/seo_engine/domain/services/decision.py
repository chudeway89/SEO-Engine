"""Opportunity, recommendation, action and outcome services.

This is where the decision stack becomes durable:

    opportunity → recommendation → approval → action → execution → outcome

Every transition is policy-evaluated, audited and event-emitted. An action can
never move to EXECUTING without an approval record when policy demanded one —
that is enforced here, not in the API layer, so no caller can route around it.
"""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.domain.models.decision import (
    Action,
    ActionApproval,
    ActionOutcome,
    Opportunity,
    Recommendation,
)
from seo_engine.domain.repositories import repository_for
from seo_engine.engines.opportunities.detection import (
    PRIORITY_FORMULA,
    DetectedOpportunity,
    prioritise,
)
from seo_engine.events.bus import emit
from seo_engine.observability.audit import record_audit
from seo_engine.observability.metrics import counter
from seo_engine.permissions.rbac import (
    P_ACTION_APPROVE,
    P_ACTION_EXECUTE,
    P_ACTION_READ,
    P_RECOMMENDATION_DECIDE,
    P_RECOMMENDATION_READ,
    Principal,
)
from seo_engine.policies.engine import ActionRequest, PolicyDecision, PolicyEngine
from seo_engine.schemas.agent import ProposedRecommendation
from seo_engine.schemas.enums import (
    ActionStatus,
    AutomationPolicy,
    DataProvenance,
    OpportunityStatus,
    RecommendationStatus,
    RiskCategory,
    RiskLevel,
)
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import (
    ApprovalRequiredError,
    ConflictError,
    PolicyViolationError,
    ValidationError,
)
from seo_engine.shared.ids import utcnow
from seo_engine.shared.security import new_idempotency_key
from sqlalchemy.ext.asyncio import AsyncSession

OpportunityRepository = repository_for(Opportunity)
RecommendationRepository = repository_for(Recommendation)
ActionRepository = repository_for(Action)
ApprovalRepository = repository_for(ActionApproval)
OutcomeRepository = repository_for(ActionOutcome)


class DecisionService:
    """Owns the opportunity → recommendation → action → outcome chain."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.opportunities = OpportunityRepository(session, principal.tenant_id)
        self.recommendations = RecommendationRepository(session, principal.tenant_id)
        self.actions = ActionRepository(session, principal.tenant_id)
        self.approvals = ApprovalRepository(session, principal.tenant_id)
        self.outcomes = OutcomeRepository(session, principal.tenant_id)
        self.policies = PolicyEngine(session, principal.tenant_id)

    # -- opportunities ---------------------------------------------------
    async def record_opportunities(
        self,
        brand_id: uuid.UUID,
        detected: list[DetectedOpportunity],
        *,
        website_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
        agent_id: str | None = None,
    ) -> list[Opportunity]:
        stored: list[Opportunity] = []
        for item in detected:
            prioritise(item)
            existing = await self.opportunities.find_one(
                Opportunity.brand_id == brand_id,
                Opportunity.opportunity_type == item.opportunity_type.value,
                Opportunity.title == item.title,
                Opportunity.status.in_([OpportunityStatus.DETECTED, OpportunityStatus.PRIORITISED]),
            )
            if existing is not None:
                # Re-detection refreshes the score rather than duplicating.
                existing.priority_score = item.priority_score
                existing.priority_breakdown = item.priority_breakdown
                existing.evidence_refs = item.evidence_refs
                existing.data = item.data
                stored.append(existing)
                continue

            record = self.opportunities.add(
                Opportunity(
                    brand_id=brand_id,
                    website_id=website_id,
                    mission_id=mission_id,
                    opportunity_type=item.opportunity_type.value,
                    title=item.title,
                    description=item.description,
                    target_entity_type=item.target_entity_type,
                    target_entity_id=item.target_entity_id,
                    target_url=item.target_url,
                    business_impact=item.business_impact,
                    seo_impact=item.seo_impact,
                    confidence=item.confidence,
                    effort=item.effort,
                    strategic_fit=item.strategic_fit,
                    risk=item.risk.value,
                    priority_score=item.priority_score,
                    priority_breakdown=item.priority_breakdown,
                    status=OpportunityStatus.PRIORITISED,
                    evidence_refs=item.evidence_refs,
                    detected_by_agent=agent_id,
                    data=item.data,
                )
            )
            stored.append(record)
        await self.session.flush()

        for record in stored:
            await emit(
                self.session,
                EventType.OPPORTUNITY_DETECTED,
                tenant_id=self.principal.tenant_id,
                brand_id=brand_id,
                aggregate_type="opportunity",
                aggregate_id=str(record.id),
                actor_type="agent" if agent_id else "system",
                actor_id=agent_id,
                payload={
                    "type": record.opportunity_type,
                    "priority_score": record.priority_score,
                    "evidence_count": len(record.evidence_refs),
                },
            )
        counter("opportunities_detected_total", value=len(stored))
        return stored

    async def list_opportunities(
        self,
        brand_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Opportunity]:
        self.principal.require(P_RECOMMENDATION_READ)
        criteria: list[Any] = [Opportunity.brand_id == brand_id]
        if status:
            criteria.append(Opportunity.status == status)
        return list(
            await self.opportunities.list(
                *criteria,
                limit=limit,
                offset=offset,
                order_by=Opportunity.priority_score.desc(),
            )
        )

    # -- recommendations --------------------------------------------------
    async def create_recommendation(
        self,
        brand_id: uuid.UUID,
        proposed: ProposedRecommendation,
        *,
        opportunity_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        risk_category: RiskCategory | str = RiskCategory.GENERAL,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
    ) -> Recommendation:
        """Persist a recommendation and pre-compute its approval requirement.

        The policy engine is consulted *now*, not at execution time, so the user
        can see up front what will need their sign-off.
        """
        if not proposed.evidence_ids and not proposed.is_hypothesis:
            # Belt and braces: the schema enforces this too.
            raise ValidationError(
                "a recommendation must cite evidence or be marked as a hypothesis",
                {"title": proposed.title},
            )

        decision: PolicyDecision | None = None
        if proposed.proposed_action:
            decision = await self.policies.evaluate(
                ActionRequest(
                    action_type=proposed.proposed_action.get("action_type", "unknown"),
                    risk=RiskLevel(proposed.risk),
                    category=risk_category,
                    brand_id=brand_id,
                    agent_id=agent_id,
                    automation_policy=automation_policy,
                    attributes=proposed.proposed_action.get("attributes", {}),
                )
            )

        impact = 0.6 * proposed.business_impact + 0.4 * proposed.seo_impact
        raw = (impact * proposed.confidence * proposed.strategic_fit) / max(proposed.effort, 0.5)
        priority = round(min(100.0, (raw / 20.0) * 100.0), 2)

        record = self.recommendations.add(
            Recommendation(
                brand_id=brand_id,
                opportunity_id=opportunity_id,
                mission_id=mission_id,
                agent_id=agent_id,
                recommendation_type=proposed.type,
                title=proposed.title,
                problem=proposed.problem,
                opportunity_statement=proposed.opportunity,
                reason=proposed.reason,
                expected_outcome=proposed.expected_outcome,
                business_impact=proposed.business_impact,
                seo_impact=proposed.seo_impact,
                effort=proposed.effort,
                risk=RiskLevel(proposed.risk).value,
                confidence=proposed.confidence,
                strategic_fit=proposed.strategic_fit,
                priority_score=priority,
                priority_breakdown={
                    "impact": round(impact, 3),
                    "confidence": proposed.confidence,
                    "strategic_fit": proposed.strategic_fit,
                    "effort": proposed.effort,
                    "formula": PRIORITY_FORMULA,
                },
                is_hypothesis=proposed.is_hypothesis,
                evidence_refs=proposed.evidence_ids,
                dependencies=proposed.dependencies,
                proposed_action=proposed.proposed_action or {},
                target_entity_type=proposed.target_entity_type,
                target_entity_id=proposed.target_entity_id,
                approval_required=decision.requires_approval if decision else True,
                approval_reason=decision.reason if decision else "no action proposed yet",
                status=RecommendationStatus.PROPOSED,
            )
        )
        await self.session.flush()

        if opportunity_id:
            opportunity = await self.opportunities.get(opportunity_id)
            if opportunity is not None:
                opportunity.status = OpportunityStatus.RECOMMENDED

        await emit(
            self.session,
            EventType.RECOMMENDATION_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="recommendation",
            aggregate_id=str(record.id),
            actor_type="agent" if agent_id else "user",
            actor_id=agent_id or str(self.principal.user_id),
            payload={
                "type": record.recommendation_type,
                "priority_score": priority,
                "is_hypothesis": record.is_hypothesis,
                "approval_required": record.approval_required,
            },
        )
        counter("recommendations_created_total", type=record.recommendation_type)
        return record

    async def list_recommendations(
        self,
        brand_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Recommendation]:
        self.principal.require(P_RECOMMENDATION_READ)
        criteria: list[Any] = [Recommendation.brand_id == brand_id]
        if status:
            criteria.append(Recommendation.status == status)
        return list(
            await self.recommendations.list(
                *criteria,
                limit=limit,
                offset=offset,
                order_by=Recommendation.priority_score.desc(),
            )
        )

    async def approve_recommendation(
        self, recommendation_id: uuid.UUID, *, note: str = ""
    ) -> Recommendation:
        self.principal.require(P_RECOMMENDATION_DECIDE)
        record = await self.recommendations.get_or_raise(recommendation_id)
        if record.status in {RecommendationStatus.APPROVED, RecommendationStatus.IMPLEMENTED}:
            raise ConflictError(
                "that recommendation has already been decided", {"status": record.status}
            )

        record.status = RecommendationStatus.APPROVED
        record.decided_by = self.principal.user_id
        record.decided_at = utcnow()
        record.decision_note = note
        await self.session.flush()

        await emit(
            self.session,
            EventType.RECOMMENDATION_APPROVED,
            tenant_id=self.principal.tenant_id,
            brand_id=record.brand_id,
            aggregate_type="recommendation",
            aggregate_id=str(record.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"note": note},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="recommendation.approve",
            resource_type="recommendation",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=record.brand_id,
            reason=note or "approved by user",
            evidence_refs=record.evidence_refs,
        )
        counter("recommendations_approved_total")
        return record

    async def reject_recommendation(
        self, recommendation_id: uuid.UUID, *, note: str = ""
    ) -> Recommendation:
        self.principal.require(P_RECOMMENDATION_DECIDE)
        record = await self.recommendations.get_or_raise(recommendation_id)
        record.status = RecommendationStatus.REJECTED
        record.decided_by = self.principal.user_id
        record.decided_at = utcnow()
        record.decision_note = note
        await self.session.flush()

        await emit(
            self.session,
            EventType.RECOMMENDATION_REJECTED,
            tenant_id=self.principal.tenant_id,
            brand_id=record.brand_id,
            aggregate_type="recommendation",
            aggregate_id=str(record.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"note": note},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="recommendation.reject",
            resource_type="recommendation",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=record.brand_id,
            reason=note or "rejected by user",
        )
        return record

    async def defer_recommendation(
        self, recommendation_id: uuid.UUID, *, until: Any = None, note: str = ""
    ) -> Recommendation:
        self.principal.require(P_RECOMMENDATION_DECIDE)
        record = await self.recommendations.get_or_raise(recommendation_id)
        record.status = RecommendationStatus.DEFERRED
        record.deferred_until = until
        record.decided_by = self.principal.user_id
        record.decided_at = utcnow()
        record.decision_note = note
        await self.session.flush()
        return record

    # -- actions ----------------------------------------------------------
    async def propose_action(
        self,
        *,
        brand_id: uuid.UUID,
        action_type: str,
        target: dict[str, Any],
        payload: dict[str, Any],
        recommendation_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
        executor_agent_id: str | None = None,
        risk: RiskLevel | str = RiskLevel.LOW,
        risk_category: RiskCategory | str = RiskCategory.GENERAL,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
        provider: str | None = None,
        attributes: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Action:
        """Create an action in PROPOSED, then move it to the status policy dictates."""
        decision = await self.policies.evaluate(
            ActionRequest(
                action_type=action_type,
                risk=RiskLevel(risk),
                category=risk_category,
                brand_id=brand_id,
                agent_id=executor_agent_id,
                automation_policy=automation_policy,
                attributes=attributes or {},
            )
        )
        if not decision.allowed:
            raise PolicyViolationError(
                "policy blocks this action outright", {"reason": decision.reason}
            )

        idempotency_key = new_idempotency_key(
            str(self.principal.tenant_id),
            str(brand_id),
            action_type,
            str(target.get("url") or target.get("id") or ""),
            str(recommendation_id or ""),
        )
        existing = await self.actions.find_one(Action.idempotency_key == idempotency_key)
        if existing is not None:
            # A retry of the same proposal is not a second action.
            return existing

        record = self.actions.add(
            Action(
                brand_id=brand_id,
                mission_id=mission_id,
                recommendation_id=recommendation_id,
                executor_agent_id=executor_agent_id,
                action_type=action_type,
                target=target,
                payload=payload,
                risk=RiskLevel(risk).value,
                approval_required=decision.requires_approval,
                policy_decision=decision.to_dict(),
                status=(
                    ActionStatus.PENDING_APPROVAL
                    if decision.requires_approval
                    else ActionStatus.APPROVED
                ),
                provider=provider,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.ACTION_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="action",
            aggregate_id=str(record.id),
            actor_type="agent" if executor_agent_id else "user",
            actor_id=executor_agent_id or str(self.principal.user_id),
            correlation_id=correlation_id,
            payload={
                "action_type": action_type,
                "requires_approval": decision.requires_approval,
                "policy_reason": decision.reason,
            },
        )
        if decision.requires_approval:
            counter("actions_pending_approval_total", action_type=action_type)
        return record

    async def approve_action(self, action_id: uuid.UUID, *, note: str = "") -> Action:
        self.principal.require(P_ACTION_APPROVE)
        record = await self.actions.get_or_raise(action_id)
        if record.status not in {ActionStatus.PENDING_APPROVAL, ActionStatus.PROPOSED}:
            raise ConflictError("that action is not awaiting approval", {"status": record.status})

        record.status = ActionStatus.APPROVED
        record.approved_by = self.principal.user_id
        record.approved_at = utcnow()
        self.approvals.add(
            ActionApproval(
                action_id=record.id,
                decision="approved",
                decided_by=self.principal.user_id,
                decided_by_role=self.principal.role.value,
                note=note,
                policy_snapshot=record.policy_decision,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.ACTION_APPROVED,
            tenant_id=self.principal.tenant_id,
            brand_id=record.brand_id,
            aggregate_type="action",
            aggregate_id=str(record.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"note": note},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="action.approve",
            resource_type="action",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=record.brand_id,
            reason=note or "approved by user",
            policy_ref=", ".join(record.policy_decision.get("policies", [])) or None,
        )
        return record

    async def reject_action(self, action_id: uuid.UUID, *, note: str = "") -> Action:
        self.principal.require(P_ACTION_APPROVE)
        record = await self.actions.get_or_raise(action_id)
        record.status = ActionStatus.REJECTED
        self.approvals.add(
            ActionApproval(
                action_id=record.id,
                decision="rejected",
                decided_by=self.principal.user_id,
                decided_by_role=self.principal.role.value,
                note=note,
                policy_snapshot=record.policy_decision,
            )
        )
        await self.session.flush()
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="action.reject",
            resource_type="action",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=record.brand_id,
            reason=note or "rejected by user",
        )
        return record

    async def assert_executable(self, action: Action) -> None:
        """The gate no caller can route around.

        An action that policy said needs approval must have an approval record
        naming a human. This is checked immediately before execution, not when
        the action was created, so a later policy change cannot be outrun.
        """
        if action.status == ActionStatus.EXECUTED:
            raise ConflictError("that action has already been executed", {})
        if action.status in {ActionStatus.REJECTED, ActionStatus.CANCELLED}:
            raise PolicyViolationError(
                "that action was rejected and cannot be executed", {"status": action.status}
            )
        if action.approval_required:
            approval = await self.approvals.find_one(
                ActionApproval.action_id == action.id, ActionApproval.decision == "approved"
            )
            if approval is None or action.approved_by is None:
                raise ApprovalRequiredError(
                    "this action requires human approval before it can be executed",
                    {
                        "action_id": str(action.id),
                        "action_type": action.action_type,
                        "policy_reason": action.policy_decision.get("reason"),
                    },
                )
        if action.status not in {ActionStatus.APPROVED, ActionStatus.RETRY}:
            raise ConflictError(
                "that action is not in an executable state", {"status": action.status}
            )

    async def mark_executing(self, action_id: uuid.UUID) -> Action:
        self.principal.require(P_ACTION_EXECUTE)
        record = await self.actions.get_or_raise(action_id)
        await self.assert_executable(record)
        record.status = ActionStatus.EXECUTING
        record.attempts += 1
        await self.session.flush()
        return record

    async def mark_executed(
        self, action_id: uuid.UUID, result: dict[str, Any], *, mode: str | None = None
    ) -> Action:
        record = await self.actions.get_or_raise(action_id)
        record.status = ActionStatus.EXECUTED
        record.result = result
        record.integration_mode = mode
        record.executed_at = utcnow()
        await self.session.flush()

        if record.recommendation_id:
            recommendation = await self.recommendations.get(record.recommendation_id)
            if recommendation is not None:
                recommendation.status = RecommendationStatus.IMPLEMENTED

        await emit(
            self.session,
            EventType.ACTION_EXECUTED,
            tenant_id=self.principal.tenant_id,
            brand_id=record.brand_id,
            aggregate_type="action",
            aggregate_id=str(record.id),
            actor_type="agent",
            actor_id=record.executor_agent_id,
            correlation_id=record.correlation_id,
            payload={"action_type": record.action_type, "mode": mode, "result": result},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="action.execute",
            resource_type="action",
            resource_id=str(record.id),
            actor_type="agent",
            actor_id=record.executor_agent_id,
            brand_id=record.brand_id,
            reason="approved action executed",
            tool=record.provider,
            after_state=result,
        )
        counter("actions_executed_total", action_type=record.action_type)
        return record

    async def mark_failed(
        self, action_id: uuid.UUID, error: str, *, retryable: bool = True
    ) -> Action:
        record = await self.actions.get_or_raise(action_id)
        record.status = ActionStatus.RETRY if retryable else ActionStatus.FAILED
        record.error_message = error[:4000]
        await self.session.flush()

        await emit(
            self.session,
            EventType.ACTION_FAILED,
            tenant_id=self.principal.tenant_id,
            brand_id=record.brand_id,
            aggregate_type="action",
            aggregate_id=str(record.id),
            payload={"error": error[:500], "retryable": retryable},
        )
        counter("actions_failed_total", action_type=record.action_type)
        return record

    async def list_actions(
        self, brand_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[Action]:
        self.principal.require(P_ACTION_READ)
        criteria: list[Any] = [Action.brand_id == brand_id]
        if status:
            criteria.append(Action.status == status)
        return list(
            await self.actions.list(*criteria, limit=limit, order_by=Action.created_at.desc())
        )

    # -- outcomes ----------------------------------------------------------
    async def record_outcome(
        self,
        action_id: uuid.UUID,
        *,
        metric: str,
        baseline: float | None,
        result: float | None,
        window_days: int = 28,
        provenance: DataProvenance | str = DataProvenance.UNKNOWN,
        source: str | None = None,
        confidence: float = 0.5,
        detail: str = "",
        window_start: Any = None,
        window_end: Any = None,
    ) -> ActionOutcome:
        """Record what actually happened after an action.

        A measurement with no data source is stored as *pending* with a null
        result rather than as a zero, so an unmeasured action never looks like a
        failed one.
        """
        action = await self.actions.get_or_raise(action_id)

        delta = None
        delta_percent = None
        status = "pending"
        if result is not None and baseline is not None:
            delta = round(result - baseline, 4)
            delta_percent = round(100.0 * delta / baseline, 2) if baseline else None
            status = "measured"
        elif result is not None:
            status = "measured"

        record = self.outcomes.add(
            ActionOutcome(
                action_id=action.id,
                mission_id=action.mission_id,
                brand_id=action.brand_id,
                metric=metric,
                baseline=baseline,
                result=result,
                delta=delta,
                delta_percent=delta_percent,
                measurement_window_days=window_days,
                window_start=window_start,
                window_end=window_end,
                provenance=DataProvenance(provenance).value,
                source=source,
                confidence=confidence,
                status=status,
                detail=detail
                or (
                    "No measurement source was available for this metric, so the "
                    "outcome is recorded as pending rather than as no change."
                    if result is None
                    else ""
                ),
                observed_at=utcnow() if result is not None else None,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.OUTCOME_RECORDED,
            tenant_id=self.principal.tenant_id,
            brand_id=action.brand_id,
            aggregate_type="action_outcome",
            aggregate_id=str(record.id),
            payload={
                "metric": metric,
                "baseline": baseline,
                "result": result,
                "delta": delta,
                "status": status,
                "provenance": record.provenance,
            },
        )
        return record

    async def list_outcomes(self, brand_id: uuid.UUID, *, limit: int = 100) -> list[ActionOutcome]:
        return list(
            await self.outcomes.list(
                ActionOutcome.brand_id == brand_id,
                limit=limit,
                order_by=ActionOutcome.created_at.desc(),
            )
        )


__all__ = ["DecisionService"]
