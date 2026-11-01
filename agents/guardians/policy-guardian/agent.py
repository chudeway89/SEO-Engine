"""POL-001 — Policy Guardian Agent.

Holds drafts and actions to the brand's own rules.

**Content.** Each draft or in-review asset's current version is checked
(``check_compliance``) for the brand's prohibited claims, its voice profile's
forbidden terminology, statements resting on unverified sources, and absolute
outcome language in a regulated category. The result is recorded against the
version as a policy review; an in-review asset that fails goes back to draft.
A prohibition the brief quotes to the writer is not mistaken for the claim.

**Actions.** Pending and approved-but-unexecuted actions are re-evaluated by the
policy engine as policy stands now. An action approved under an older, looser
policy is reported if current policy would block it or demand approval. The
guardian reports; the execution gate re-checks approval at the moment of
execution, so a report here is an early warning, not the only line of defence.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, resolve_assets
from seo_engine.domain.services.content import EVALUATION_POLICY
from seo_engine.engines.content.compliance import check_compliance
from seo_engine.policies.engine import ActionRequest
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.content import ContentEvaluation
from seo_engine.schemas.enums import (
    ActionStatus,
    ContentStatus,
    DataProvenance,
    EvidenceType,
    RiskLevel,
    SynthesisMode,
)

_schemas = load_agent_module(__file__)
PolicyReviewInput = _schemas.PolicyReviewInput
PolicyReviewOutput = _schemas.PolicyReviewOutput

OPEN_ACTION_STATUSES = frozenset(
    {ActionStatus.PROPOSED.value, ActionStatus.PENDING_APPROVAL.value, ActionStatus.APPROVED.value}
)


class PolicyGuardianAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = PolicyReviewInput.model_validate(context.inputs)
        facts = await load_brand_facts(context, payload.brand_id)
        content = context.service("content")

        # --- content compliance ----------------------------------------------
        assets = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses={ContentStatus.DRAFT.value, ContentStatus.IN_REVIEW.value},
            limit=payload.max_assets,
        )
        content_results: list[dict[str, Any]] = []
        returned = 0
        for asset in assets:
            version = await content.latest_version(asset.id)
            if version is None:
                continue
            result = check_compliance(
                content.draft_contract(version),
                prohibited_claims=facts.prohibited_claims,
                forbidden_terms=facts.forbidden_terms,
                risk_category=asset.risk_category,
            )
            await content.record_evaluation(
                asset.id,
                ContentEvaluation(
                    overall_score=100.0 if result.compliant else 0.0,
                    passed=result.compliant,
                    blocking_failures=[f"{v['rule']}: {v['match']}" for v in result.violations],
                    warnings=result.warnings,
                    requires_human_review=True,
                ),
                version_id=version.id,
                evaluation_type=EVALUATION_POLICY,
                evaluated_by_agent=self.manifest.id,
            )
            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="policy_guardian",
                reference=f"content_version:{version.id}",
                observation=(
                    f"'{asset.title}' v{version.version} "
                    + (
                        "complies with the brand's content rules."
                        if result.compliant
                        else f"breaks {len(result.violations)} content rule(s): "
                        + "; ".join(f"{v['rule']} ('{v['match']}')" for v in result.violations[:4])
                    )
                ),
                data=result.as_dict(),
                provenance=DataProvenance.OBSERVED,
            )
            if not result.compliant:
                workspace.find(
                    key="policy.content_violation",
                    title=f"'{asset.title}' breaks the brand's content rules",
                    detail="; ".join(v["detail"] for v in result.violations[:4]),
                    severity="high",
                    data=result.as_dict(),
                    evidence=[evidence],
                )
                if asset.status == ContentStatus.IN_REVIEW.value:
                    await content.set_status(
                        asset.id,
                        ContentStatus.DRAFT,
                        reason="returned to draft by the policy guardian: "
                        + ", ".join(v["rule"] for v in result.violations),
                    )
                    returned += 1
            content_results.append(
                {
                    "asset_id": str(asset.id),
                    "version_id": str(version.id),
                    "compliant": result.compliant,
                    "violations": result.violations,
                }
            )

        # --- action policy drift -----------------------------------------------
        attention: list[dict[str, Any]] = []
        actions = [
            a
            for a in await context.service("decisions").list_actions(payload.brand_id, limit=200)
            if a.status in OPEN_ACTION_STATUSES
        ]
        engine = context.service("policies")
        if actions:
            workspace.tools_used.add("policy")
        for action in actions:
            decision = await engine.evaluate(
                ActionRequest(
                    action_type=action.action_type,
                    risk=RiskLevel(action.risk),
                    category=facts.risk_category,
                    brand_id=payload.brand_id,
                    agent_id=action.executor_agent_id,
                    automation_policy=context.policy.automation_policy,
                )
            )
            problem = None
            if not decision.allowed:
                problem = "current policy blocks this action outright"
            elif decision.requires_approval and not action.approval_required:
                problem = "current policy requires approval, but the action was created without it"
            if problem is None:
                continue
            attention.append(
                {
                    "action_id": str(action.id),
                    "action_type": action.action_type,
                    "status": action.status,
                    "problem": problem,
                    "policy_reason": decision.reason,
                }
            )
        if attention:
            drift_evidence = workspace.observe(
                evidence_type=EvidenceType.SYSTEM,
                source="policy_engine",
                reference=f"brand:{payload.brand_id}",
                observation=(f"{len(attention)} open action(s) no longer satisfy current policy."),
                data={"actions": attention},
                provenance=DataProvenance.OBSERVED,
            )
            for item in attention:
                workspace.find(
                    key="policy.action_drift",
                    title=f"{item['action_type']} ({item['status']}): {item['problem']}",
                    detail=item["policy_reason"],
                    severity="high",
                    data=item,
                    evidence=[drift_evidence],
                )

        if not assets and not actions:
            workspace.limitation("There were no drafts or open actions to review.")
        compliant = sum(1 for c in content_results if c["compliant"])
        output = PolicyReviewOutput(
            brand_id=str(payload.brand_id),
            drafts_checked=len(content_results),
            drafts_compliant=compliant,
            returned_to_draft=returned,
            actions_checked=len(actions),
            actions_needing_attention=attention,
            content=content_results,
        )
        workspace.outputs["policy_review"] = output.model_dump(mode="json")
        workspace.metrics["policy_violations"] = float(len(content_results) - compliant)

        return (
            f"Checked {len(content_results)} draft(s) against the brand's content rules "
            f"({compliant} compliant, {returned} returned to draft) and re-evaluated "
            f"{len(actions)} open action(s) against current policy ({len(attention)} need "
            "attention)."
        )


AGENT = PolicyGuardianAgent
