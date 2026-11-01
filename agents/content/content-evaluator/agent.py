"""CNT-007 — Content Evaluator Agent.

Scores the current version of each draft against the brief it was written to,
with the deterministic evaluator (``evaluate_content``): twelve criteria, a pass
mark, and four blocking criteria — accuracy, risk, brand alignment and search
intent — that fail the draft whatever its average.

Every evaluation is recorded against the version it judged. A later edit makes
a new version, so an old pass can never be mistaken for approval of new text.
A draft with no recorded brief is skipped with the reason: without the brief
there is nothing to evaluate it against.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import brief_for_version, load_brand_facts, resolve_assets
from seo_engine.domain.services.content import EVALUATION_QUALITY
from seo_engine.engines.content.evaluation import evaluate_content
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import ContentStatus, DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
ContentEvaluatorInput = _schemas.ContentEvaluatorInput
ContentEvaluatorOutput = _schemas.ContentEvaluatorOutput


class ContentEvaluatorAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentEvaluatorInput.model_validate(context.inputs)
        content = context.service("content")
        assets = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses={ContentStatus.DRAFT.value, ContentStatus.IN_REVIEW.value},
            limit=payload.max_assets,
        )
        if not assets:
            workspace.limitation("There are no drafts to evaluate.")
            return "No drafts were available to evaluate."

        facts = await load_brand_facts(context, payload.brand_id)
        evaluations: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for asset in assets:
            version = await content.latest_version(asset.id)
            if version is None:
                skipped.append({"asset_id": str(asset.id), "reason": "the asset has no version"})
                continue
            brief = await brief_for_version(context, asset, version)
            if brief is None:
                skipped.append(
                    {"asset_id": str(asset.id), "reason": "no brief is recorded for this draft"}
                )
                continue

            draft = content.draft_contract(version)
            evaluation = evaluate_content(
                draft,
                brief,
                brand_voice=facts.voice,
                existing_hashes=await content.content_hashes(
                    payload.brand_id, exclude_asset_id=asset.id
                ),
            )
            record = await content.record_evaluation(
                asset.id,
                evaluation,
                version_id=version.id,
                evaluation_type=EVALUATION_QUALITY,
                evaluated_by_agent=self.manifest.id,
            )
            failed = [c for c in evaluation.criteria if not c.passed]
            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_evaluator",
                reference=f"content_version:{version.id}",
                observation=(
                    f"'{asset.title}' v{version.version} scores {evaluation.overall_score:.0f}/100 "
                    + ("and passes" if evaluation.passed else "and fails")
                    + (
                        f"; blocking: {', '.join(evaluation.blocking_failures)}"
                        if evaluation.blocking_failures
                        else ""
                    )
                    + "."
                ),
                data={
                    "evaluation_id": str(record.id),
                    "criteria": {c.criterion: c.score for c in evaluation.criteria},
                },
                # A measurement of the text itself, so observed.
                provenance=DataProvenance.OBSERVED,
            )
            if failed:
                workspace.find(
                    key="content_evaluation.failed_criteria",
                    title=f"'{asset.title}' fails {len(failed)} criterion/criteria",
                    detail="; ".join(f"{c.criterion}: {c.detail}" for c in failed[:6]),
                    severity="high" if evaluation.blocking_failures else "medium",
                    data={"failed": [c.model_dump(mode="json") for c in failed]},
                    evidence=[evidence],
                )
            evaluations.append(
                {
                    "asset_id": str(asset.id),
                    "version_id": str(version.id),
                    "evaluation_id": str(record.id),
                    "score": evaluation.overall_score,
                    "passed": evaluation.passed,
                    "blocking_failures": evaluation.blocking_failures,
                    "requires_human_review": evaluation.requires_human_review,
                }
            )

        for item in skipped:
            workspace.limitation(f"Asset {item['asset_id']} was not evaluated: {item['reason']}.")

        passed = sum(1 for e in evaluations if e["passed"])
        output = ContentEvaluatorOutput(
            brand_id=str(payload.brand_id),
            evaluated=len(evaluations),
            passed=passed,
            skipped=skipped,
            evaluations=evaluations,
        )
        workspace.outputs["content_evaluation"] = output.model_dump(mode="json")
        workspace.metrics["drafts_evaluated"] = float(len(evaluations))
        workspace.metrics["drafts_passed_evaluation"] = float(passed)

        return (
            f"Evaluated {len(evaluations)} draft(s) against their briefs: {passed} passed, "
            f"{len(evaluations) - passed} failed."
            + (f" {len(skipped)} skipped with stated reasons." if skipped else "")
        )


AGENT = ContentEvaluatorAgent
