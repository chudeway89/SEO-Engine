"""CNT-009 — Content Quality Guardian Agent.

The evaluator scores a draft; this gate decides whether a person should be
asked to approve it at all. It blocks on what no score may average away: a
failed or missing evaluation of *this* version, an outline in place of prose,
substantial duplication of another asset or a live page, thinness against the
brief's own target, and scaled near-identical variants of one template.

A passing draft moves to ``in_review``. That is as far as an agent can take it:
the content service handed to agents refuses to approve content, so approval
stays a human decision. Every block is recorded as a repair item so the
remediation is tracked, not just reported.
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
from seo_engine.domain.services.content import EVALUATION_GATE, EVALUATION_QUALITY
from seo_engine.engines.content.quality import quality_gate
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.content import ContentEvaluation
from seo_engine.schemas.enums import ContentStatus, DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
QualityGateInput = _schemas.QualityGateInput
QualityGateOutput = _schemas.QualityGateOutput


class ContentQualityGateAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = QualityGateInput.model_validate(context.inputs)
        content = context.service("content")
        assets = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses={ContentStatus.DRAFT.value},
            limit=payload.max_assets,
        )
        if not assets:
            workspace.limitation("There are no drafts waiting at the quality gate.")
            return "No drafts were waiting at the quality gate."

        # What a draft must not duplicate: the brand's other assets and live pages.
        all_assets = await content.list_assets(payload.brand_id, limit=500)
        bodies: dict[str, str] = {}
        titles: dict[str, str] = {}
        for other in all_assets:
            latest = await content.latest_version(other.id)
            if latest is not None:
                bodies[f"content_asset:{other.id}"] = latest.body_markdown
                titles[str(other.id)] = other.title
        if payload.website_id is not None:
            for page in await context.service("websites").list_pages(payload.website_id, limit=500):
                if page.text_content:
                    bodies[page.url] = page.text_content

        results: list[dict[str, Any]] = []
        moved = 0
        for asset in assets:
            version = await content.latest_version(asset.id)
            brief = await brief_for_version(context, asset, version) if version else None
            if version is None or brief is None:
                workspace.limitation(
                    f"'{asset.title}' was not gated: it has no "
                    + ("version" if version is None else "recorded brief")
                    + "."
                )
                continue
            draft = content.draft_contract(version)
            record = await content.latest_evaluation(
                asset.id, evaluation_type=EVALUATION_QUALITY, version_id=version.id
            )
            gate = quality_gate(
                draft,
                brief,
                evaluation=evaluation_contract(record) if record else None,
                other_bodies={
                    ref: body for ref, body in bodies.items() if ref != f"content_asset:{asset.id}"
                },
                sibling_titles=[t for aid, t in titles.items() if aid != str(asset.id)],
            )
            stored = await content.record_evaluation(
                asset.id,
                ContentEvaluation(
                    overall_score=record.overall_score if record else 0.0,
                    passed=gate.passed,
                    blocking_failures=gate.blocking,
                    warnings=gate.warnings,
                    requires_human_review=True,
                ),
                version_id=version.id,
                evaluation_type=EVALUATION_GATE,
                evaluated_by_agent=self.manifest.id,
            )
            evidence = workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_quality_gate",
                reference=f"content_version:{version.id}",
                observation=(
                    f"'{asset.title}' v{version.version} "
                    + (
                        "passes the quality gate."
                        if gate.passed
                        else "is blocked: " + " ".join(gate.blocking)
                    )
                ),
                data={"gate_id": str(stored.id), **gate.as_dict()},
                provenance=DataProvenance.OBSERVED,
            )

            if gate.passed:
                await content.set_status(
                    asset.id, ContentStatus.IN_REVIEW, reason="passed the content quality gate"
                )
                moved += 1
            else:
                for block in gate.blocking:
                    await content.record_repair(
                        asset.id,
                        issue=block,
                        repair_type="outline_needs_prose"
                        if gate.checks.get("is_outline") and "outline" in block
                        else "quality_gate_block",
                        evaluation_id=stored.id,
                        performed_by_agent=self.manifest.id,
                    )
                workspace.find(
                    key="content_gate.blocked",
                    title=f"'{asset.title}' is blocked at the quality gate",
                    detail=" ".join(gate.blocking),
                    severity="high",
                    data=gate.as_dict(),
                    evidence=[evidence],
                )
            results.append(
                {
                    "asset_id": str(asset.id),
                    "version_id": str(version.id),
                    "passed": gate.passed,
                    "blocking": gate.blocking,
                    "warnings": gate.warnings,
                    "requires_human_review": True,
                }
            )

        passed = sum(1 for r in results if r["passed"])
        output = QualityGateOutput(
            brand_id=str(payload.brand_id),
            gated=len(results),
            passed=passed,
            moved_to_review=moved,
            results=results,
        )
        workspace.outputs["content_quality_gate"] = output.model_dump(mode="json")
        workspace.metrics["drafts_passed_gate"] = float(passed)

        return (
            f"Gated {len(results)} draft(s): {passed} passed and moved to human review, "
            f"{len(results) - passed} blocked with tracked repairs. No content was approved; "
            "approval is a human decision."
        )


AGENT = ContentQualityGateAgent
