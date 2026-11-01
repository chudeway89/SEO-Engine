"""BRD-003 — Business Objective Agent.

A goal the platform cannot measure is a goal it cannot report progress on —
and reporting progress anyway would mean inventing a figure. For each stated
goal this agent names the metric that would measure it and the data source that
metric needs, then checks the source is actually connected and, for lead goals,
that at least one analytics event is identified as a lead.

It recommends the fix for each blocker (connect a provider, confirm a lead
event, set a target). It never sets a target or a baseline itself.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts
from seo_engine.engines.brand.objectives import assess_goal
from seo_engine.schemas.agent import AgentContext, ProposedRecommendation
from seo_engine.schemas.enums import (
    DataProvenance,
    EvidenceType,
    IntegrationProvider,
    RiskLevel,
    SynthesisMode,
)

_schemas = load_agent_module(__file__)
BusinessObjectiveInput = _schemas.BusinessObjectiveInput
BusinessObjectiveOutput = _schemas.BusinessObjectiveOutput


class BusinessObjectiveAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = BusinessObjectiveInput.model_validate(context.inputs)
        facts = await load_brand_facts(context, payload.brand_id)
        integrations = context.service("integrations")
        connected = await integrations.connected_providers(payload.brand_id)
        lead_events: list[str] = []
        if IntegrationProvider.GOOGLE_ANALYTICS_4.value in connected:
            lead_events = await integrations.lead_event_names(payload.brand_id)

        system_evidence = workspace.observe(
            evidence_type=EvidenceType.OBSERVATION,
            source="integration_registry",
            reference=f"brand:{payload.brand_id}",
            observation=(
                "Connected data sources: "
                + (", ".join(sorted(connected)) or "none")
                + ". Events identified as leads: "
                + (", ".join(lead_events) or "none")
                + "."
            ),
            data={"connected": sorted(connected), "lead_events": lead_events},
            provenance=DataProvenance.OBSERVED,
        )

        if not facts.goals:
            workspace.limitation("The brand profile records no business goals.")
            workspace.recommend(
                ProposedRecommendation(
                    type="brand.objective_define",
                    title="Record at least one measurable business goal",
                    problem="No business goal is recorded, so no mission has a target.",
                    opportunity="A stated goal lets the platform select work and measure it.",
                    reason="The brand graph's goal list is empty.",
                    effort=1.0,
                    risk=RiskLevel.LOW,
                    confidence=0.9,
                    expected_outcome="Missions run against a target that can be measured.",
                    evidence_ids=[system_evidence.id],
                )
            )
            workspace.outputs["business_objectives"] = BusinessObjectiveOutput(
                brand_id=str(payload.brand_id), connected_providers=sorted(connected)
            ).model_dump(mode="json")
            return "No business goals are recorded, so none could be assessed."

        assessments = []
        for goal in facts.goals:
            assessment = assess_goal(
                description=goal.description,
                goal_type=goal.goal_type,
                stated_metric=goal.target_metric,
                target_value=goal.target_value,
                timeframe=goal.timeframe,
                connected=connected,
                lead_events_confirmed=bool(lead_events),
                has_website=payload.website_id is not None,
            )
            assessments.append(assessment)
            goal_evidence = workspace.observe(
                evidence_type=EvidenceType.HUMAN_INPUT,
                source="brand_graph",
                reference=f"goal:{goal.id}",
                observation=(
                    f"Goal '{goal.description}' maps to {assessment.metric or 'no measurable metric'}"
                    + (
                        f", measured from {assessment.data_source}"
                        if assessment.data_source
                        else ""
                    )
                    + "."
                ),
                data=assessment.as_dict(),
                provenance=DataProvenance.USER_PROVIDED,
            )
            workspace.find(
                key="objective.measurable" if assessment.measurable else "objective.unmeasurable",
                title=(
                    f"'{goal.description}' is measurable as {assessment.metric}"
                    if assessment.measurable
                    else f"'{goal.description}' cannot be measured yet"
                ),
                detail=" ".join(assessment.blockers + assessment.specificity_gaps)
                or "The metric, its data source and a target are all in place.",
                severity="info" if assessment.measurable else "medium",
                data=assessment.as_dict(),
                evidence=[goal_evidence, system_evidence],
            )
            for blocker in assessment.blockers:
                workspace.recommend(
                    ProposedRecommendation(
                        type="brand.objective_measurement",
                        title=f"Make '{goal.description}' measurable",
                        problem=blocker,
                        opportunity=f"Progress on {assessment.metric or 'the goal'} could be reported.",
                        reason="Without the data source, progress cannot be observed or reported.",
                        business_impact=7.0,
                        seo_impact=2.0,
                        effort=2.0,
                        risk=RiskLevel.LOW,
                        confidence=0.85,
                        expected_outcome="The goal's metric is measured from a connected source.",
                        evidence_ids=[goal_evidence.id, system_evidence.id],
                    )
                )

        measurable = sum(1 for a in assessments if a.measurable)
        output = BusinessObjectiveOutput(
            brand_id=str(payload.brand_id),
            goals=len(assessments),
            measurable=measurable,
            connected_providers=sorted(connected),
            lead_events=lead_events,
            assessments=[a.as_dict() for a in assessments],
        )
        workspace.outputs["business_objectives"] = output.model_dump(mode="json")
        workspace.metrics["goals_measurable"] = float(measurable)

        return (
            f"Assessed {len(assessments)} business goal(s): {measurable} can be measured from "
            f"connected data, {len(assessments) - measurable} cannot yet. No target or baseline "
            "has been set or estimated."
        )


AGENT = BusinessObjectiveAgent
