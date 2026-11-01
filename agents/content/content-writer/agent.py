"""CNT-004 — Content Writer Agent.

Writes the first version of each briefed piece as an internal draft.

The brief has already decided everything that matters — topic, keywords,
sections, questions, sources, approved and prohibited claims. When a language
model is configured, ``generate_draft`` asks it for prose inside those
constraints. When none is, the model gateway refuses to improvise and the
engine returns a structured outline built from the brief, carrying a notice
that it is not prose. The writer never invents article text it cannot ground.

Each draft is an immutable new version on a content asset, created through the
content service as the declared autonomous action ``content.create`` — an
internal record no visitor can see. Publication is a separate, human-approved
step that this agent cannot take.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts
from seo_engine.engines.content.generation import generate_draft
from seo_engine.engines.content.quality import is_outline
from seo_engine.schemas.agent import AgentContext, AgentResult, ProposedAction
from seo_engine.schemas.enums import (
    ActionType,
    DataProvenance,
    EvidenceType,
    RiskLevel,
    SynthesisMode,
)

_schemas = load_agent_module(__file__)
ContentWriterInput = _schemas.ContentWriterInput
ContentWriterOutput = _schemas.ContentWriterOutput


class ContentWriterAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def execute(self, context: AgentContext) -> AgentResult:
        result = await super().execute(context)
        # Report what actually happened: if any draft's prose came from a model,
        # this run was hybrid, whatever the class default says.
        drafts = result.outputs.get("content_writer", {}).get("drafts", [])
        if any(d.get("synthesis_mode") != SynthesisMode.DETERMINISTIC.value for d in drafts):
            result.synthesis_mode = SynthesisMode.HYBRID
        return result

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentWriterInput.model_validate(context.inputs)
        content = context.service("content")

        if payload.brief_ids:
            records = [await content.get_brief(b) for b in payload.brief_ids]
        else:
            records = await content.list_briefs(payload.brand_id, status="draft")
        records = [r for r in records if r.status == "draft"][: payload.max_drafts]
        if not records:
            workspace.limitation(
                "There are no open briefs to write. The brief agent produces them; it must "
                "run first."
            )
            return "No open briefs were available, so no draft was written."

        facts = await load_brand_facts(context, payload.brand_id)
        drafts: list[dict[str, Any]] = []
        outlines = 0
        for record in records:
            brief = content.brief_contract(record)
            draft = await generate_draft(brief, brand_voice=facts.voice)
            outline = is_outline(draft)
            outlines += int(outline)

            asset = await content.create_asset(
                payload.brand_id,
                title=draft.title,
                asset_type=brief.content_type,
                slug=draft.slug,
                url=brief.target_url,
                website_id=payload.website_id,
                risk_category=brief.risk_category,
                primary_keyword=brief.primary_keyword,
            )
            version = await content.add_version(
                asset,
                draft,
                change_summary=(
                    "Structured outline from the brief (no language model configured)"
                    if outline
                    else "First draft written within the brief's constraints"
                ),
                created_by_agent=self.manifest.id,
                brief_id=record.id,
            )
            await content.link_brief_to_asset(record.id, asset.id)

            workspace.actions.append(
                ProposedAction(
                    action_type=ActionType.CONTENT_CREATE.value,
                    target={"asset_id": str(asset.id), "version": version.version},
                    payload={"title": draft.title, "outline": outline},
                    risk=RiskLevel.LOW,
                )
            )
            workspace.observe(
                evidence_type=EvidenceType.SYSTEM,
                source="content_service",
                reference=f"content_asset:{asset.id}",
                observation=(
                    f"Created version {version.version} of '{draft.title}' "
                    + ("as a structured outline" if outline else "as written prose")
                    + f" ({version.word_count} words) from brief {record.id}."
                ),
                data={
                    "asset_id": str(asset.id),
                    "version_id": str(version.id),
                    "synthesis_mode": draft.synthesis_mode,
                },
                provenance=DataProvenance.OBSERVED,
            )
            drafts.append(
                {
                    "asset_id": str(asset.id),
                    "version_id": str(version.id),
                    "brief_id": str(record.id),
                    "title": draft.title,
                    "is_outline": outline,
                    "synthesis_mode": draft.synthesis_mode,
                    "word_count": version.word_count,
                }
            )

        if outlines:
            workspace.limitation(
                f"{outlines} of {len(drafts)} draft(s) are structured outlines: no language "
                "model is configured, and no article text has been generated. A writer must "
                "supply the prose before the piece can pass review."
            )

        output = ContentWriterOutput(
            brand_id=str(payload.brand_id),
            drafts_written=len(drafts),
            outlines=outlines,
            drafts=drafts,
        )
        workspace.outputs["content_writer"] = output.model_dump(mode="json")
        workspace.metrics["drafts_written"] = float(len(drafts))

        return (
            f"Created {len(drafts)} internal draft(s)"
            + (f", {outlines} of them structured outlines rather than prose" if outlines else "")
            + ". Nothing is visible on the live site."
        )


AGENT = ContentWriterAgent
