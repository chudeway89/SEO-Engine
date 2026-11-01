"""CNT-005 — Content Optimisation Agent.

The evaluator says which criteria scored low; this agent says what to change.
For each draft with an evaluation of its current version, every weak,
non-blocking criterion becomes a concrete edit against the draft and its brief
(``optimisation_edits``) — which heading, which question, which link, which
schema type, which over-used term.

Edits are recorded as tracked repairs. The agent never rewrites the draft
itself: the evaluated version must stay exactly the text that was evaluated,
and applying an edit makes a new version that is evaluated afresh.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import (
    brief_for_version,
    evaluation_contract,
    resolve_assets,
)
from seo_engine.domain.services.content import EVALUATION_QUALITY
from seo_engine.engines.content.optimisation import optimisation_edits
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import ContentStatus, DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
ContentOptimisationInput = _schemas.ContentOptimisationInput
ContentOptimisationOutput = _schemas.ContentOptimisationOutput


class ContentOptimisationAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentOptimisationInput.model_validate(context.inputs)
        content = context.service("content")
        assets = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses={ContentStatus.DRAFT.value, ContentStatus.IN_REVIEW.value},
            limit=payload.max_assets,
        )
        if not assets:
            workspace.limitation("There are no drafts to optimise.")
            return "No drafts were available to optimise."

        proposed: list[dict[str, Any]] = []
        reviewed = 0
        for asset in assets:
            version = await content.latest_version(asset.id)
            if version is None:
                continue
            record = await content.latest_evaluation(
                asset.id, evaluation_type=EVALUATION_QUALITY, version_id=version.id
            )
            brief = await brief_for_version(context, asset, version)
            if record is None or brief is None:
                workspace.limitation(
                    f"'{asset.title}' has no "
                    + ("evaluation of its current version" if record is None else "recorded brief")
                    + ", so no optimisation was proposed for it."
                )
                continue
            reviewed += 1
            edits = optimisation_edits(
                content.draft_contract(version), brief, evaluation_contract(record)
            )
            if not edits:
                continue
            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_optimisation",
                reference=f"content_version:{version.id}",
                observation=(
                    f"'{asset.title}' v{version.version}: {len(edits)} edit(s) proposed from "
                    f"evaluation {record.id}."
                ),
                data={"edits": [e.as_dict() for e in edits]},
                provenance=DataProvenance.OBSERVED,
            )
            for edit in edits:
                await content.record_repair(
                    asset.id,
                    issue=edit.reason,
                    repair_type=edit.edit_type,
                    detail=edit.proposal,
                    evaluation_id=record.id,
                    performed_by_agent=self.manifest.id,
                )
                proposed.append({"asset_id": str(asset.id), **edit.as_dict()})
            workspace.find(
                key="content_optimisation.edits",
                title=f"{len(edits)} edit(s) proposed for '{asset.title}'",
                detail="; ".join(e.proposal for e in edits[:5]),
                data={"edits": [e.as_dict() for e in edits]},
                evidence=[evidence],
            )

        output = ContentOptimisationOutput(
            brand_id=str(payload.brand_id),
            assets_reviewed=reviewed,
            edits_proposed=len(proposed),
            edits=proposed,
        )
        workspace.outputs["content_optimisation"] = output.model_dump(mode="json")
        workspace.metrics["optimisation_edits"] = float(len(proposed))

        return (
            f"Reviewed the evaluations of {reviewed} draft(s) and proposed {len(proposed)} "
            "specific edit(s) as tracked repairs. No draft was changed."
        )


AGENT = ContentOptimisationAgent
