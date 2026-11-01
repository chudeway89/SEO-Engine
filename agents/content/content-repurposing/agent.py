"""CNT-008 — Content Repurposing Agent.

Derives platform assets from a canonical piece with ``repurpose``: each
derivative carries its own platform, audience, objective, format, tone and call
to action, and names its canonical source so the original stays identifiable.

Only a piece that has passed the quality gate (in review, approved or published)
is repurposed: derivatives of an unreviewed draft would spread whatever the gate
would have caught. A structured outline is never repurposed — its derivatives
would be outlines too. Every derivative is stored as a draft; publishing one is a
separate, approved action.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, resolve_assets
from seo_engine.engines.content.generation import available_platforms, repurpose
from seo_engine.engines.content.quality import is_outline
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import ContentStatus, DataProvenance, EvidenceType, SynthesisMode

_schemas = load_agent_module(__file__)
ContentRepurposingInput = _schemas.ContentRepurposingInput
ContentRepurposingOutput = _schemas.ContentRepurposingOutput

ELIGIBLE = frozenset(
    {ContentStatus.IN_REVIEW.value, ContentStatus.APPROVED.value, ContentStatus.PUBLISHED.value}
)


class ContentRepurposingAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = ContentRepurposingInput.model_validate(context.inputs)
        supported = set(available_platforms())
        platforms = [p for p in payload.platforms if p in supported]
        unknown = sorted(set(payload.platforms) - supported)
        if unknown:
            workspace.limitation(f"Unsupported platform(s) ignored: {', '.join(unknown)}.")
        if not platforms:
            return "No supported platform was requested, so nothing was repurposed."

        content = context.service("content")
        assets = await resolve_assets(
            context,
            payload.brand_id,
            payload.asset_ids,
            statuses=set(ELIGIBLE),
            limit=payload.max_assets,
        )
        facts = await load_brand_facts(context, payload.brand_id)
        audience = facts.audiences[0] if facts.audiences else "The brand's audience"

        items: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        used = 0
        for asset in assets:
            if asset.status not in ELIGIBLE:
                skipped.append(
                    {"asset_id": str(asset.id), "reason": f"status is {asset.status}, not reviewed"}
                )
                continue
            version = await content.latest_version(asset.id)
            if version is None:
                continue
            draft = content.draft_contract(version)
            if is_outline(draft):
                skipped.append({"asset_id": str(asset.id), "reason": "it is an outline, not prose"})
                continue
            derivatives = repurpose(
                draft,
                platforms=platforms,
                audience=audience,
                canonical_url=asset.url,
                canonical_asset_id=str(asset.id),
            )
            saved = await content.save_representations(asset.id, derivatives)
            used += 1
            workspace.observe(
                evidence_type=EvidenceType.CONTENT,
                source="content_repurposing",
                reference=f"content_asset:{asset.id}",
                observation=(
                    f"Derived {len(saved)} draft asset(s) from '{asset.title}' "
                    f"v{version.version} for {', '.join(platforms)}."
                ),
                data={"platforms": platforms, "canonical_url": asset.url},
                provenance=DataProvenance.OBSERVED,
            )
            items += [
                {
                    "asset_id": str(asset.id),
                    "representation_id": str(row.id),
                    "platform": row.platform,
                    "status": row.status,
                    "canonical_source_url": row.canonical_source_url,
                }
                for row in saved
            ]

        if not assets:
            workspace.limitation(
                "No content has passed the quality gate yet, so there is no canonical piece "
                "to repurpose."
            )
        for item in skipped:
            workspace.limitation(f"Asset {item['asset_id']} was not repurposed: {item['reason']}.")

        output = ContentRepurposingOutput(
            brand_id=str(payload.brand_id),
            sources_used=used,
            derivatives=len(items),
            skipped=skipped,
            items=items,
        )
        workspace.outputs["content_repurposing"] = output.model_dump(mode="json")
        workspace.metrics["derivatives"] = float(len(items))

        return (
            f"Derived {len(items)} draft asset(s) from {used} reviewed piece(s)"
            + (f"; {len(skipped)} piece(s) skipped with stated reasons" if skipped else "")
            + ". Each names its canonical source."
        )


AGENT = ContentRepurposingAgent
