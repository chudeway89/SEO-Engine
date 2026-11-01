"""PUB-001 — Publishing Agent.

The last step of the content loop, and the most guarded. An asset is published
only when every one of these holds for its *current* version:

1. a person approved the asset (the agent-scoped content service cannot);
2. the version passed the quality gate (CNT-009);
3. the version passed the policy review (POL-001);
4. the version is prose, not a structured outline;
5. the ``cms.publish`` action the policy engine created for it carries the
   approval that policy requires — checked again by the decision service at the
   moment of execution, so no caller can route around it.

Publication goes through the brand's connected CMS adapter. With the
development adapter nothing reaches a real site, and the record says so: the
action is marked executed in ``development_adapter`` mode, never as a live
publication.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, resolve_assets
from seo_engine.domain.services.content import EVALUATION_GATE, EVALUATION_POLICY
from seo_engine.engines.content.quality import is_outline
from seo_engine.schemas.agent import AgentContext, ProposedAction
from seo_engine.schemas.enums import (
    HIGH_RISK_CATEGORIES,
    ActionType,
    ContentStatus,
    DataProvenance,
    EvidenceType,
    IntegrationMode,
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

_schemas = load_agent_module(__file__)
PublishingInput = _schemas.PublishingInput
PublishingOutput = _schemas.PublishingOutput


class PublishingAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = PublishingInput.model_validate(context.inputs)
        content = context.service("content")
        decisions = context.service("decisions")
        facts = await load_brand_facts(context, payload.brand_id)
        regulated = facts.risk_category in HIGH_RISK_CATEGORIES

        candidates = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses={ContentStatus.APPROVED.value, ContentStatus.IN_REVIEW.value},
            limit=payload.max_assets,
        )
        output = PublishingOutput(brand_id=str(payload.brand_id), considered=len(candidates))
        if not candidates:
            workspace.limitation(
                "No content is in review or approved, so there is nothing to publish."
            )
            workspace.outputs["publishing"] = output.model_dump(mode="json")
            return "No content was ready to publish."

        cms: Any = None
        cms_mode: str | None = None
        for asset in candidates:
            if asset.status != ContentStatus.APPROVED.value:
                output.awaiting_editorial_approval += 1
                continue

            version = await content.latest_version(asset.id)
            blocks = await self._gates(content, asset, version)
            if blocks:
                output.blocked.append(
                    {"asset_id": str(asset.id), "title": asset.title, "reasons": blocks}
                )
                continue

            risk = RiskLevel.HIGH if regulated else RiskLevel.MEDIUM
            try:
                action = await decisions.propose_action(
                    brand_id=payload.brand_id,
                    action_type=ActionType.CMS_PUBLISH.value,
                    target={"id": str(asset.id), "url": asset.url or asset.slug},
                    payload={"title": asset.title, "version": version.version},
                    mission_id=payload.mission_id,
                    executor_agent_id=self.manifest.id,
                    risk=risk,
                    risk_category=facts.risk_category,
                    automation_policy=context.policy.automation_policy,
                    correlation_id=context.correlation_id,
                    # Publishing is never autonomous, whatever policy allows.
                    approval_floor=(
                        f"{self.manifest.id} declares cms.publish as requiring human approval"
                        if ActionType.CMS_PUBLISH.value in self.manifest.approval_required_for
                        else None
                    ),
                )
            except PolicyViolationError as exc:
                output.blocked.append(
                    {"asset_id": str(asset.id), "title": asset.title, "reasons": [exc.message]}
                )
                continue
            workspace.actions.append(
                ProposedAction(
                    action_type=ActionType.CMS_PUBLISH.value,
                    target=action.target,
                    payload=action.payload,
                    risk=risk,
                    idempotency_key=action.idempotency_key,
                )
            )
            if action.approval_required and action.approved_by is None:
                output.awaiting_action_approval.append(
                    {
                        "asset_id": str(asset.id),
                        "action_id": str(action.id),
                        "policy_reason": (action.policy_decision or {}).get("reason"),
                    }
                )
                continue
            if not payload.publish:
                continue

            if cms is None:
                if not workspace.note_unavailable_tool("cms"):
                    break
                cms, cms_mode = await self._cms(context, payload.brand_id)
                if cms is None:
                    workspace.limitation(
                        "No content management system is connected for this brand, so "
                        "approved content could not be published. Nothing was published."
                    )
                    break
            published = await self._publish(
                context, decisions, content, cms, action, asset, version
            )
            if published is None:
                output.failed.append({"asset_id": str(asset.id), "action_id": str(action.id)})
            else:
                output.published.append(published)

        for item in output.blocked:
            workspace.find(
                key="publishing.blocked",
                title=f"'{item['title']}' cannot be published",
                detail="; ".join(item["reasons"]),
                severity="high",
                data=item,
            )
        if cms_mode == IntegrationMode.DEVELOPMENT_ADAPTER.value and output.published:
            workspace.limitation(
                "The CMS is the development adapter: published items exist only in its "
                "in-memory store. Nothing reached a real website."
            )
        workspace.observe(
            evidence_type=EvidenceType.SYSTEM,
            source="publishing_agent",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Considered {output.considered} asset(s): {len(output.published)} published, "
                f"{output.awaiting_editorial_approval} awaiting editorial approval, "
                f"{len(output.awaiting_action_approval)} awaiting action approval, "
                f"{len(output.blocked)} blocked by a gate, {len(output.failed)} failed."
            ),
            data=output.model_dump(mode="json"),
            provenance=DataProvenance.OBSERVED,
        )
        workspace.outputs["publishing"] = output.model_dump(mode="json")
        workspace.metrics["content_published"] = float(len(output.published))

        return (
            f"Published {len(output.published)} piece(s)"
            + (
                f" through the {cms_mode.replace('_', ' ')}"
                if cms_mode and output.published
                else ""
            )
            + f". {output.awaiting_editorial_approval} await editorial approval, "
            f"{len(output.awaiting_action_approval)} await approval of the publish action, and "
            f"{len(output.blocked)} are blocked by a gate. Nothing was published without every "
            "approval its policy required."
        )

    async def _gates(self, content: Any, asset: Any, version: Any) -> list[str]:
        if version is None:
            return ["the asset has no version"]
        blocks: list[str] = []
        if is_outline(content.draft_contract(version)):
            blocks.append("the current version is an outline, not prose")
        gate = await content.latest_evaluation(
            asset.id, evaluation_type=EVALUATION_GATE, version_id=version.id
        )
        if gate is None or not gate.passed:
            blocks.append("the current version has not passed the quality gate")
        policy = await content.latest_evaluation(
            asset.id, evaluation_type=EVALUATION_POLICY, version_id=version.id
        )
        if policy is None or not policy.passed:
            blocks.append("the current version has not passed the policy review")
        return blocks

    async def _cms(self, context: AgentContext, brand_id: Any) -> tuple[Any, str | None]:
        explicit = context.services.get("cms")
        if explicit is not None:
            return explicit, explicit.mode.value
        try:
            _connection, adapter = await context.service("integrations").cms_adapter(brand_id)
        except IntegrationNotConnectedError:
            return None, None
        return adapter, adapter.mode.value

    async def _publish(
        self,
        context: AgentContext,
        decisions: Any,
        content: Any,
        cms: Any,
        action: Any,
        asset: Any,
        version: Any,
    ) -> dict[str, Any] | None:
        try:
            await decisions.mark_executing(action.id)
        except (ApprovalRequiredError, PolicyViolationError, ConflictError):
            # The decision service is the final gate; its refusal stands.
            return None
        try:
            draft = await cms.create_draft(
                title=version.title,
                body_markdown=version.body_markdown,
                slug=asset.slug or "untitled",
                metadata={"meta_description": version.meta_description},
            )
            external_id = str(draft.payload.get("id"))
            response = await cms.publish(external_id=external_id)
        except IntegrationError as exc:
            await decisions.mark_failed(action.id, exc.message)
            return None
        link = response.payload.get("link")
        await decisions.mark_executed(
            action.id,
            {
                "external_id": external_id,
                "status": response.payload.get("status"),
                "link": link,
                "notice": response.notice,
            },
            mode=response.mode.value,
        )
        await content.mark_published(
            asset.id,
            url=link,
            external_ref={
                "id": external_id,
                "mode": response.mode.value,
                "version": version.version,
            },
        )
        return {
            "asset_id": str(asset.id),
            "action_id": str(action.id),
            "external_id": external_id,
            "link": link,
            "mode": response.mode.value,
        }


AGENT = PublishingAgent
