"""ANA-002 — GA4 Analytics Agent.

Syncs Analytics and establishes the organic lead baseline the mission measures
itself against.

When no baseline can be measured it says so and leaves the mission without one.
A mission that starts from an invented baseline would report invented progress.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import DataProvenance, EvidenceType, SynthesisMode


class AnalyticsInput(BaseModel):
    brand_id: UUID
    days: int = 28


class AnalyticsOutput(BaseModel):
    brand_id: str
    connected: bool = False
    mode: str | None = None
    provenance: str = DataProvenance.UNKNOWN.value
    traffic_rows: int = 0
    conversion_rows: int = 0
    organic_lead_baseline: float | None = None
    baseline_provenance: str = DataProvenance.UNKNOWN.value
    baseline_source: str | None = None
    lead_events: list[str] = Field(default_factory=list)


class GA4AnalyticsAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = AnalyticsInput.model_validate(context.inputs)

        if not workspace.note_unavailable_tool("ga4"):
            workspace.outputs["analytics"] = AnalyticsOutput(
                brand_id=str(payload.brand_id), connected=False
            ).model_dump(mode="json")
            workspace.limitation(
                "No conversion baseline could be established, so progress against a "
                "lead target cannot be measured."
            )
            return (
                "Google Analytics 4 is not connected for this brand, so no traffic or "
                "conversion data is available and no lead baseline exists. Nothing has "
                "been estimated in its place."
            )

        integrations = context.service("integrations")
        summary = await integrations.sync_analytics(payload.brand_id, days=payload.days)
        baseline, provenance, source = await integrations.organic_conversion_baseline(
            payload.brand_id
        )

        if summary.get("synthetic"):
            workspace.limitation(
                "Analytics is connected through the development adapter, so every "
                "figure below is synthetic demonstration data, not a measurement of "
                "this business."
            )

        sync_evidence = workspace.observe(
            evidence_type=EvidenceType.GA4,
            source="google_analytics_4",
            reference=f"property:{summary.get('property_id')}",
            observation=(
                f"Synced {summary['traffic_rows']} traffic row(s) and "
                f"{summary['conversion_rows']} conversion row(s) over {payload.days} days."
            ),
            data={k: v for k, v in summary.items() if k != "window"},
            provenance=DataProvenance(summary["provenance"]),
        )

        if baseline is None:
            workspace.limitation(
                "No organic conversion events are recorded, so there is no qualified "
                "lead baseline. The mission will run without one rather than against "
                "an assumed figure."
            )
        else:
            workspace.observe(
                evidence_type=EvidenceType.GA4,
                source=source,
                reference=f"property:{summary.get('property_id')}",
                observation=(
                    f"Organic qualified-lead events over the last {payload.days} days "
                    f"total {baseline:.0f}. This is the mission baseline."
                ),
                data={"baseline": baseline, "window_days": payload.days},
                provenance=provenance,
            )
            workspace.find(
                key="ga4.lead_baseline",
                title=f"Organic qualified-lead baseline: {baseline:.0f}",
                detail=(
                    "Measured from conversion events on organic sessions that the "
                    "customer has flagged as qualified leads."
                ),
                data={"baseline": baseline, "provenance": provenance.value},
                evidence=[sync_evidence],
            )

        output = AnalyticsOutput(
            brand_id=str(payload.brand_id),
            connected=True,
            mode=summary.get("mode"),
            provenance=summary["provenance"],
            traffic_rows=summary["traffic_rows"],
            conversion_rows=summary["conversion_rows"],
            organic_lead_baseline=baseline,
            baseline_provenance=provenance.value,
            baseline_source=source,
        )
        workspace.outputs["analytics"] = output.model_dump(mode="json")
        workspace.metrics["ga4_traffic_rows"] = float(summary["traffic_rows"])
        if baseline is not None:
            workspace.metrics["organic_lead_baseline"] = float(baseline)

        return (
            f"Analytics synced {summary['traffic_rows']} traffic row(s) and "
            f"{summary['conversion_rows']} conversion row(s). "
            + (
                f"The organic qualified-lead baseline is {baseline:.0f} over {payload.days} days."
                if baseline is not None
                else "No qualified-lead baseline could be measured."
            )
            + (" These figures are synthetic development data." if summary.get("synthetic") else "")
        )


AGENT = GA4AnalyticsAgent
