"""CNT-004 — Content Writer Agent.

Writes the first version of each briefed piece as an internal draft.

The brief has already decided everything that matters — topic, keywords,
sections, questions, sources, approved and prohibited claims. When a language
model is connected — any model, through any supported protocol —
``generate_draft`` asks it for prose inside those constraints. When none is,
or the connected one fails, the engine returns a structured outline built from
the brief, carrying a notice that it is not prose, and the run says why. The
writer never invents article text it cannot ground.

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
from seo_engine.engines.content.generation import generate_draft, slugify
from seo_engine.engines.content.quality import is_outline
from seo_engine.schemas.agent import AgentContext, AgentResult, ProposedAction
from seo_engine.schemas.enums import (
    ActionType,
    ContentStatus,
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

    @staticmethod
    async def _not_writable(content: Any, asset: Any) -> str | None:
        """Why the writer must leave an existing asset alone, if it must.

        It may write into a new asset, or replace an outline with prose (so a
        model connected later upgrades earlier outlines). It never overwrites
        prose a person or a model already wrote, and never touches a published
        page: changes to a live page go through the content update agent
        (CNT-006), with approval.
        """
        if asset.status == ContentStatus.PUBLISHED.value:
            return (
                "it is already published; changes to a live page go through the content "
                "update agent (CNT-006), with approval"
            )
        current = await content.latest_version(asset.id)
        if current is not None and not is_outline(content.draft_contract(current)):
            return (
                f"version {current.version} is already written prose; the writer only "
                "replaces outlines"
            )
        return None

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentWriterInput.model_validate(context.inputs)
        content = context.service("content")

        if payload.brief_ids:
            records = [await content.get_brief(b) for b in payload.brief_ids]
        else:
            records = await content.list_briefs(payload.brand_id, status="draft")
        # A brief named explicitly may already be in production with an outline:
        # writing it again (with a model connected since) upgrades that outline.
        writable = {"draft", "in_production"} if payload.brief_ids else {"draft"}
        records = [r for r in records if r.status in writable][: payload.max_drafts]
        if not records:
            workspace.limitation(
                "There are no open briefs to write. The brief agent produces them; it must "
                "run first."
            )
            return "No open briefs were available, so no draft was written."

        facts = await load_brand_facts(context, payload.brand_id)
        drafts: list[dict[str, Any]] = []
        outlines = 0
        notes: list[str] = []
        skipped: list[dict[str, Any]] = []
        for record in records:
            brief = content.brief_contract(record)
            # The asset's identity comes from the brief, never from a model's
            # wording of the title, so changing models (or adding one later)
            # upgrades the same piece instead of duplicating it.
            slug = slugify(brief.title)
            asset = await content.create_asset(
                payload.brand_id,
                title=brief.title,
                asset_type=brief.content_type,
                slug=slug,
                url=brief.target_url,
                website_id=payload.website_id,
                risk_category=brief.risk_category,
                primary_keyword=brief.primary_keyword,
            )
            reason = await self._not_writable(content, asset)
            if reason:
                skipped.append(
                    {"brief_id": str(record.id), "asset_id": str(asset.id), "reason": reason}
                )
                workspace.limitation(f"'{brief.title}' was not written: {reason}")
                continue

            # Whatever model is connected — or none — the draft comes back; a
            # model that failed or was cut off is reported in ``notes``.
            draft = await generate_draft(
                brief,
                gateway=context.services.get("model_gateway"),
                brand_voice=facts.voice,
                notes=notes,
            )
            draft = draft.model_copy(update={"slug": slug})
            outline = is_outline(draft)
            if outline and asset.current_version:
                # Still no model to write it: an identical outline is not a new version.
                skipped.append(
                    {
                        "brief_id": str(record.id),
                        "asset_id": str(asset.id),
                        "reason": "no model wrote a new draft; the existing outline is unchanged",
                    }
                )
                continue
            outlines += int(outline)
            version = await content.add_version(
                asset,
                draft,
                change_summary=(
                    "Structured outline from the brief (no model wrote it)"
                    if outline
                    else "Draft written by a model within the brief's constraints"
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

        for note in notes:
            workspace.limitation(note)
        if outlines:
            workspace.limitation(
                f"{outlines} of {len(drafts)} draft(s) are structured outlines: no model "
                "wrote them, and no article text has been generated. A writer must supply "
                "the prose before the piece can pass review."
            )

        output = ContentWriterOutput(
            brand_id=str(payload.brand_id),
            drafts_written=len(drafts),
            outlines=outlines,
            drafts=drafts,
            skipped=skipped,
        )
        workspace.outputs["content_writer"] = output.model_dump(mode="json")
        workspace.metrics["drafts_written"] = float(len(drafts))

        return (
            f"Created {len(drafts)} internal draft(s)"
            + (f", {outlines} of them structured outlines rather than prose" if outlines else "")
            + (f"; left {len(skipped)} existing piece(s) untouched" if skipped else "")
            + ". Nothing is visible on the live site."
        )


AGENT = ContentWriterAgent
