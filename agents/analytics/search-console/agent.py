"""ANA-001 — Search Console Analytics Agent.

Syncs Search Console and finds queries sitting just below where clicks begin.

If Search Console is not connected the agent completes with no findings and a
plain statement of that fact. It never substitutes an estimate for a
measurement, because a fabricated position would then drive real prioritisation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode

#: Positions in this band are close enough that improvement is realistic.
RECOVERABLE_MIN = 4.0
RECOVERABLE_MAX = 20.0
MIN_IMPRESSIONS = 50


class SearchConsoleInput(BaseModel):
    brand_id: UUID
    website_id: UUID | None = None
    days: int = 28


class SearchConsoleOutput(BaseModel):
    brand_id: str
    connected: bool = False
    mode: str | None = None
    provenance: str = DataProvenance.UNKNOWN.value
    rows_synced: int = 0
    total_clicks: int = 0
    total_impressions: int = 0
    recoverable_queries: list[dict[str, Any]] = Field(default_factory=list)


class SearchConsoleAnalyticsAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = SearchConsoleInput.model_validate(context.inputs)

        if not workspace.note_unavailable_tool("gsc"):
            workspace.outputs["search_console"] = SearchConsoleOutput(
                brand_id=str(payload.brand_id), connected=False
            ).model_dump(mode="json")
            return (
                "Search Console is not connected for this brand, so no search "
                "performance data is available. Nothing has been estimated in its "
                "place, and no query-level opportunities are claimed."
            )

        integrations = context.service("integrations")
        summary = await integrations.sync_search_console(
            payload.brand_id, website_id=payload.website_id, days=payload.days
        )
        queries = await integrations.top_queries(payload.brand_id, limit=200)

        if summary.get("synthetic"):
            workspace.limitation(
                "Search Console is connected through the development adapter, so every "
                "figure below is synthetic demonstration data, not a measurement of "
                "this website."
            )

        total_clicks = sum(clicks for _, _, clicks, _ in queries)
        total_impressions = sum(impressions for _, impressions, _, _ in queries)

        sync_evidence = workspace.observe(
            evidence_type=EvidenceType.GSC,
            source="google_search_console",
            reference=summary.get("site_url", ""),
            observation=(
                f"Synced {summary['rows']} performance row(s) over {payload.days} days: "
                f"{total_impressions} impression(s) and {total_clicks} click(s) across "
                f"{len(queries)} quer(y/ies)."
            ),
            data={k: v for k, v in summary.items() if k != "window"},
            provenance=DataProvenance(summary["provenance"]),
        )

        recoverable = [
            {
                "query": query,
                "impressions": impressions,
                "clicks": clicks,
                "position": round(position, 2),
            }
            for query, impressions, clicks, position in queries
            if RECOVERABLE_MIN <= position <= RECOVERABLE_MAX and impressions >= MIN_IMPRESSIONS
        ]
        recoverable.sort(key=lambda item: -item["impressions"])

        if recoverable:
            evidence = workspace.observe(
                evidence_type=EvidenceType.GSC,
                source="google_search_console",
                reference=summary.get("site_url", ""),
                observation=(
                    f"{len(recoverable)} quer(y/ies) average a position between "
                    f"{RECOVERABLE_MIN:.0f} and {RECOVERABLE_MAX:.0f} with at least "
                    f"{MIN_IMPRESSIONS} impressions, which is close enough to the "
                    "visible results that improvement is realistic."
                ),
                data={"queries": recoverable[:20]},
                provenance=DataProvenance(summary["provenance"]),
            )
            workspace.find(
                key="gsc.recoverable_positions",
                title=f"{len(recoverable)} quer(y/ies) are within reach of the first page",
                detail=(
                    "These already earn impressions, so the demand is measured rather "
                    "than assumed. They are the cheapest available gains."
                ),
                severity="medium",
                data={"top": recoverable[:10]},
                evidence=[evidence],
            )
        else:
            workspace.limitation(
                "No query sits in the recoverable position band with meaningful "
                "impressions, so no position-based opportunity is claimed."
            )

        output = SearchConsoleOutput(
            brand_id=str(payload.brand_id),
            connected=True,
            mode=summary.get("mode"),
            provenance=summary["provenance"],
            rows_synced=summary["rows"],
            total_clicks=total_clicks,
            total_impressions=total_impressions,
            recoverable_queries=recoverable[:50],
        )
        workspace.outputs["search_console"] = output.model_dump(mode="json")
        workspace.outputs["observed_queries"] = [
            {"query": q, "impressions": i, "clicks": c, "position": p}
            for q, i, c, p in queries[:200]
        ]
        workspace.metrics["gsc_rows"] = float(summary["rows"])
        workspace.metrics["recoverable_queries"] = float(len(recoverable))
        _ = sync_evidence

        return (
            f"Search Console reports {total_impressions} impression(s) and "
            f"{total_clicks} click(s) across {len(queries)} quer(y/ies) over "
            f"{payload.days} days. {len(recoverable)} quer(y/ies) sit in the "
            "recoverable position band."
            + (
                " These figures come from the development adapter and are synthetic."
                if summary.get("synthetic")
                else ""
            )
        )


AGENT = SearchConsoleAnalyticsAgent
