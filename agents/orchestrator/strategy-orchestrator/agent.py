"""ORCH-001 — Brand and Strategy Orchestrator.

The orchestrator as an auditable agent run. Given an objective (or the brand's
highest-priority goal), it classifies the mission, selects the stages that
mission needs, records the reason every other stage is not run, and states what
the brand would have to connect to unlock them.

It delegates and never executes (Build Specification §29): its only outputs are
the plan, ``next_tasks`` for each selected stage, and readiness
recommendations. It calls no tool and does no other agent's analysis; the same
``Orchestrator`` the mission workflow uses makes the selection, so the plan an
operator previews here is the plan a mission would run.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.orchestration.orchestrator import Orchestrator
from seo_engine.schemas.agent import AgentContext, NextTask, ProposedRecommendation
from seo_engine.schemas.enums import DataProvenance, EvidenceType, RiskLevel, SynthesisMode

_schemas = load_agent_module(__file__)
StrategyInput = _schemas.StrategyInput
StrategyOutput = _schemas.StrategyOutput


class StrategyOrchestratorAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = StrategyInput.model_validate(context.inputs)
        brands = context.service("brands")
        profile = await brands.profile(payload.brand_id)

        objective = (payload.objective or "").strip()
        if not objective:
            goals = sorted(profile["goals"], key=lambda g: g.priority)
            if not goals:
                workspace.limitation(
                    "No objective was given and the brand records no goals, so there is "
                    "nothing to plan for."
                )
                return "No plan was produced: there is no objective and no recorded goal."
            objective = goals[0].description
            workspace.limitation(
                f"No objective was given; planning for the brand's top goal: '{objective}'."
            )

        websites = await context.service("websites").list_websites(payload.brand_id)
        has_website = payload.website_id is not None or bool(websites)
        connected = await context.service("integrations").connected_providers(payload.brand_id)
        competitors = profile["competitors"]

        readiness = {
            "has_website": has_website,
            "connected_providers": sorted(connected),
            "competitors_recorded": len(competitors),
            "goals_recorded": len(profile["goals"]),
        }
        readiness_evidence = workspace.observe(
            evidence_type=EvidenceType.OBSERVATION,
            source="brand_readiness",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Website connected: {'yes' if has_website else 'no'}. Data sources: "
                + (", ".join(sorted(connected)) or "none")
                + f". Competitors recorded: {len(competitors)}."
            ),
            data=readiness,
            provenance=DataProvenance.OBSERVED,
        )

        plan = Orchestrator().plan(
            objective,
            has_website=has_website,
            connected_integrations=connected,
            has_competitors=bool(competitors),
        )

        agent_by_stage = {s.spec.stage: s.spec.agent_id for s in plan.included}
        for stage in plan.included:
            spec = stage.spec
            workspace.next_tasks.append(
                NextTask(
                    agent_id=spec.agent_id,
                    objective=spec.objective,
                    task_type=spec.task_type,
                    inputs={"brand_id": str(payload.brand_id), "stage": spec.stage},
                    depends_on=[agent_by_stage[d] for d in spec.depends_on if d in agent_by_stage],
                    priority=spec.priority.value,
                )
            )

        for stage in plan.excluded:
            workspace.find(
                key="strategy.stage_excluded",
                title=f"{stage.spec.stage.replace('_', ' ').capitalize()} is not run",
                detail=stage.reason,
                data={"stage": stage.spec.stage, "agent_id": stage.spec.agent_id},
                evidence=[readiness_evidence],
            )
            unlock = stage.spec.requires_integration
            if unlock and unlock not in connected:
                workspace.recommend(
                    ProposedRecommendation(
                        type="integration.connect",
                        title=f"Connect {unlock} to enable {stage.spec.stage.replace('_', ' ')}",
                        problem=stage.reason,
                        opportunity=f"The {stage.spec.agent_id} stage could run on measured data.",
                        reason="The stage needs this provider and the provider is not connected.",
                        business_impact=6.0,
                        seo_impact=5.0,
                        effort=2.0,
                        risk=RiskLevel.LOW,
                        confidence=0.9,
                        expected_outcome=f"{stage.spec.stage.replace('_', ' ').capitalize()} runs in future missions.",
                        evidence_ids=[readiness_evidence.id],
                    )
                )

        output = StrategyOutput(
            brand_id=str(payload.brand_id),
            objective=objective,
            mission_type=plan.mission_type,
            target_metric=plan.target_metric,
            stages=[
                {
                    "stage": s.spec.stage,
                    "agent_id": s.spec.agent_id,
                    "depends_on": s.spec.depends_on,
                    "reason": s.reason,
                }
                for s in plan.included
            ],
            excluded=[
                {"stage": s.spec.stage, "agent_id": s.spec.agent_id, "reason": s.reason}
                for s in plan.excluded
            ],
            readiness=readiness,
            summary=plan.summary,
        )
        workspace.outputs["strategy"] = output.model_dump(mode="json")
        workspace.metrics["stages_selected"] = float(len(plan.included))
        if plan.target_metric is None:
            workspace.limitation(
                f"A '{plan.mission_type}' mission has no single measurable target metric, so "
                "its progress is reported per stage rather than against a number."
            )

        return plan.summary


AGENT = StrategyOrchestratorAgent
