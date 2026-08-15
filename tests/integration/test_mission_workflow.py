"""The canonical mission, end to end.

    BRAND → WEBSITE → CRAWL → OBSERVE → RESEARCH → ANALYSE → OPPORTUNITY →
    PRIORITISE → RECOMMEND → APPROVE → ACT → MEASURE → LEARN → MEMORY

This runs the real orchestrator, the real Agent Runtime, the real crawler
against an in-process website, the real deterministic engines and the real
database. Nothing in the path is mocked except the network itself.

What is asserted is not "it ran" but the behaviour the specification demands:
stages are *selected*, every recommendation carries evidence, health-category
content needs approval, an unconnected provider produces a stated limitation
rather than a number, and the mission is never declared achieved just because
its plan finished.
"""

from __future__ import annotations

import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from seo_engine.domain.seed.demo import DEMO_OBJECTIVE, build_demo_brand
from seo_engine.domain.services.decision import DecisionService
from seo_engine.domain.services.mission import MissionService
from seo_engine.engines.crawler.crawler import WebsiteCrawler
from seo_engine.schemas.enums import DataProvenance, MissionStatus, TaskStatus
from seo_engine.workflows.engine import LocalWorkflowEngine
from seo_engine.workflows.mission import MissionWorkflow
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.fake_site import build_web_client

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module", autouse=True)
def _registry() -> None:
    set_registry(AgentRegistry(find_repo_root() / "agents").load(force=True))


@pytest.fixture
async def web_services():
    """Services that make the crawler reach the in-process web instead of the internet."""
    async with build_web_client() as client:

        def crawler_factory(config):
            return WebsiteCrawler(config, client=client)

        yield {"crawler_factory": crawler_factory}


async def _run_mission(session: AsyncSession, principal, web_services, **kwargs):
    scenario = await build_demo_brand(session, principal)
    workflow = MissionWorkflow(
        session,
        principal,
        extra_services=web_services,
        options={"max_pages": 30, "max_depth": 3, **kwargs},
    )
    mission, plan = await workflow.plan(
        scenario.brand.id, DEMO_OBJECTIVE, website_id=scenario.website.id
    )
    report = await workflow.run(mission, plan)
    return scenario, mission, plan, report


# --- planning ---------------------------------------------------------------
async def test_the_objective_selects_the_stages_it_needs(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)
    workflow = MissionWorkflow(session, principal, extra_services=web_services)

    mission, plan = await workflow.plan(
        scenario.brand.id, DEMO_OBJECTIVE, website_id=scenario.website.id
    )

    assert plan.mission_type == "qualified_leads"
    assert plan.target_metric == "qualified_organic_leads"
    stages = [s.spec.stage for s in plan.included]
    assert stages[0] == "brand_understanding"
    assert "ga4_analysis" in stages, "a lead mission needs the conversion baseline"
    assert stages[-1] == "execution_plan"

    graph = await MissionService(session, principal).task_graph(mission.id)
    assert len(graph["nodes"]) == len(plan.included)
    assert graph["edges"], "the plan must be a dependency graph, not a list"
    assert all(node["selection_reason"] for node in graph["nodes"])


async def test_a_stage_whose_provider_is_absent_is_excluded_with_a_reason(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal, connect_integrations=False)
    workflow = MissionWorkflow(session, principal)

    _, plan = await workflow.plan(scenario.brand.id, DEMO_OBJECTIVE, website_id=scenario.website.id)

    excluded = {s.spec.stage: s.reason for s in plan.excluded}
    assert "gsc_analysis" in excluded and "ga4_analysis" in excluded
    assert "not connected" in excluded["ga4_analysis"]
    assert "nothing has been estimated" in excluded["ga4_analysis"]


# --- execution --------------------------------------------------------------
async def test_the_mission_runs_end_to_end(session: AsyncSession, tenant_ctx, web_services) -> None:
    _, _, principal = tenant_ctx
    _, mission, plan, report = await _run_mission(session, principal, web_services)

    assert report.failed_stages == [], f"stages failed: {report.failed_stages}"
    assert report.completed_stages == [s.spec.stage for s in plan.included]

    # Every stage produced a human-readable observation, and no stage returned
    # an empty summary.
    assert all(step.summary for step in report.steps)

    tasks = await MissionService(session, principal).tasks_for(mission.id)
    assert {t.status for t in tasks} == {TaskStatus.COMPLETED}


async def test_the_crawl_stage_observed_the_real_site(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    _, _, principal = tenant_ctx
    _, _, _, report = await _run_mission(session, principal, web_services)

    audit = report.outputs["website_audit"]["technical_audit"]
    assert audit["pages_crawled"] > 5
    assert audit["issues_total"] > 0
    assert 0 <= audit["overall_health"] <= 100

    # The fake site contains a page whose copy tries to issue instructions.
    audit_step = next(s for s in report.steps if s.stage == "website_audit")
    assert any(
        flag.get("type") == "prompt_injection_attempt" for flag in audit_step.security_flags
    ), "crawled copy attempting instruction must be reported, not obeyed"


async def test_measured_demand_is_attributed_to_the_provider_that_measured_it(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    _, _, principal = tenant_ctx
    _, _, _, report = await _run_mission(session, principal, web_services)

    research = report.outputs["keyword_research"]["keyword_research"]
    assert research["keywords_total"] > 0
    assert research["measured_demand_available"] is True
    assert "google_search_console" in research["sources_used"]
    assert any("demand" in k["measured_dimensions"] for k in research["top_keywords"])


async def test_without_a_provider_no_keyword_carries_a_demand_figure(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    """Rule 14: with nothing connected, demand is absent — never estimated."""
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal, connect_integrations=False)
    workflow = MissionWorkflow(
        session, principal, extra_services=web_services, options={"max_pages": 12, "max_depth": 2}
    )
    mission, plan = await workflow.plan(
        scenario.brand.id, DEMO_OBJECTIVE, website_id=scenario.website.id
    )
    report = await workflow.run(mission, plan)

    research = report.outputs["keyword_research"]["keyword_research"]
    assert research["keywords_total"] > 0
    assert research["measured_demand_available"] is False
    assert research["sources_used"] == ["brand_graph"]
    for keyword in research["top_keywords"]:
        assert "demand" not in keyword["measured_dimensions"]

    step = next(s for s in report.steps if s.stage == "keyword_research")
    assert any("no keyword carries a volume" in limitation for limitation in step.limitations)

    # And with no analytics provider, the mission simply has no baseline.
    assert report.baseline is None


async def test_every_recommendation_cites_evidence(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    """Rule 7: a recommendation without evidence is a hypothesis, and is labelled."""
    _, _, principal = tenant_ctx
    scenario, _, _, _ = await _run_mission(session, principal, web_services)

    decisions = DecisionService(session, principal)
    recommendations = await decisions.list_recommendations(scenario.brand.id)
    assert recommendations, "the mission produced no recommendation at all"

    for recommendation in recommendations:
        assert recommendation.evidence_refs, f"{recommendation.title} cites no evidence"
        assert recommendation.reason
        assert recommendation.expected_outcome


async def test_health_content_requires_human_approval(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    """The demo brand is health-category: nothing publishes itself."""
    _, _, principal = tenant_ctx
    scenario, _, _, _ = await _run_mission(session, principal, web_services)

    decisions = DecisionService(session, principal)
    recommendations = await decisions.list_recommendations(scenario.brand.id)
    content = [r for r in recommendations if "content" in r.recommendation_type]
    assert content, "expected at least one content recommendation to check"
    assert all(r.approval_required for r in content)
    assert all(r.approval_reason for r in content)

    actions = await decisions.list_actions(scenario.brand.id)
    assert all(a.status != "executed" for a in actions), "nothing may execute unapproved"


async def test_the_baseline_is_measured_and_labelled(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    """The development adapter supplies the baseline, and says that it did."""
    _, _, principal = tenant_ctx
    _, mission, _, report = await _run_mission(session, principal, web_services)

    assert report.baseline is not None
    assert report.baseline["metric"] == "qualified_organic_leads"
    assert report.baseline["provenance"] == DataProvenance.SYNTHETIC_DEMO.value

    refreshed = await MissionService(session, principal).get(mission.id)
    assert refreshed.baseline == report.baseline["value"]
    assert refreshed.baseline_provenance == DataProvenance.SYNTHETIC_DEMO.value

    analytics_step = next(s for s in report.steps if s.stage == "ga4_analysis")
    assert any("synthetic" in limitation.lower() for limitation in analytics_step.limitations)


async def test_a_finished_plan_does_not_mean_an_achieved_mission(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    """Achievement is measured over time, never inferred from completion."""
    _, _, principal = tenant_ctx
    _, mission, _, report = await _run_mission(session, principal, web_services)

    assert report.status == MissionStatus.MONITORING.value
    refreshed = await MissionService(session, principal).get(mission.id)
    assert refreshed.status != MissionStatus.ACHIEVED.value


async def test_progress_is_recorded_stage_by_stage(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    _, _, principal = tenant_ctx
    _, mission, plan, _ = await _run_mission(session, principal, web_services)

    missions = MissionService(session, principal)
    progress = await missions.progress_for(mission.id)
    stages = {row.stage for row in progress}
    assert stages >= {s.spec.stage for s in plan.included}
    assert progress[-1].percent_complete == 100.0

    summary = await missions.summary(mission.id)
    assert summary["tasks"]["completed"] == len(plan.included)
    assert summary["metrics"], "measured agent metrics must be recorded against the mission"


# --- the engine -------------------------------------------------------------
async def test_the_local_engine_plans_and_runs_in_one_call(
    session: AsyncSession, tenant_ctx, web_services
) -> None:
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)

    handle = await LocalWorkflowEngine().start_mission(
        session,
        principal,
        brand_id=scenario.brand.id,
        objective=DEMO_OBJECTIVE,
        website_id=scenario.website.id,
        options={"max_pages": 15, "max_depth": 2},
        extra_services=web_services,
    )

    assert handle.engine == "local"
    assert handle.report is not None
    assert handle.report.failed_stages == []
    assert handle.workflow_id == f"mission-{handle.mission_id}"
