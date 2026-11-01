"""Behavioural tests for the brand, research, SEO, competitor, orchestration and
quality agents.

Every agent runs through the real Agent Runtime against the in-process demo
site and the real database. The assertions are the behaviours the rules demand:
proposals never mutate the brand graph, synthetic data stays labelled and never
becomes a recommendation, a source is verified only by a fetch, an unconnected
provider produces a limitation rather than a figure, and every opportunity seed
cites evidence that exists.
"""

from __future__ import annotations

import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from seo_engine.domain.seed.demo import DEMO_OBJECTIVE, build_demo_brand
from seo_engine.domain.services import BrandService
from seo_engine.domain.services.decision import DecisionService
from seo_engine.domain.services.search import SearchService
from seo_engine.evidence.collector import EvidenceCollector
from seo_engine.orchestration.orchestrator import Orchestrator
from seo_engine.schemas.agent import ProposedRecommendation
from seo_engine.schemas.enums import DataProvenance, EvidenceType, RiskLevel
from seo_engine.workflows.mission import MissionWorkflow
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.agents import AgentHarness
from tests.fixtures.fake_site import build_web_client

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module", autouse=True)
def _registry() -> None:
    set_registry(AgentRegistry(find_repo_root() / "agents").load(force=True))


@pytest.fixture
async def harness(session: AsyncSession, tenant_ctx):
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)
    async with build_web_client() as client:
        yield AgentHarness(
            session=session,
            principal=principal,
            brand_id=scenario.brand.id,
            website_id=scenario.website.id,
            client=client,
        )


@pytest.fixture
async def bare_harness(session: AsyncSession, tenant_ctx):
    """The demo brand with no integrations connected at all."""
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal, connect_integrations=False)
    async with build_web_client() as client:
        yield AgentHarness(
            session=session,
            principal=principal,
            brand_id=scenario.brand.id,
            website_id=scenario.website.id,
            client=client,
        )


def _seeds_cite_produced_evidence(outcome) -> None:
    produced = {e.id for e in outcome.result.evidence}
    for seed in outcome.result.outputs.get("opportunity_seeds", []):
        assert seed["evidence_refs"], f"seed {seed['title']} cites no evidence"
        assert set(seed["evidence_refs"]) <= produced, f"seed {seed['title']} cites unknown refs"


# --- orchestration --------------------------------------------------------------
async def test_the_strategy_orchestrator_delegates_and_names_what_to_connect(
    bare_harness: AgentHarness,
) -> None:
    outcome = await bare_harness.run("ORCH-001", {"objective": DEMO_OBJECTIVE})
    result = outcome.result
    strategy = result.outputs["strategy"]

    assert strategy["mission_type"] == "qualified_leads"
    assert result.next_tasks, "the orchestrator delegates through next tasks"
    assert {t.agent_id for t in result.next_tasks} >= {"BRD-001", "SEO-001", "DEC-001"}
    assert result.actions == [] and result.outputs["tools_used"] == []

    excluded = {e["stage"]: e["reason"] for e in strategy["excluded"]}
    assert {"gsc_analysis", "ga4_analysis", "serp_research"} <= set(excluded)
    connect = {r.title for r in result.recommendations if r.type == "integration.connect"}
    assert any("google_analytics_4" in title for title in connect)
    assert all(r.evidence_ids for r in result.recommendations)


async def test_ordering_dependencies_do_not_exclude_a_stage(bare_harness: AgentHarness) -> None:
    """Search intent benefits from SERP data but runs without it."""
    plan = Orchestrator().plan(DEMO_OBJECTIVE, has_website=True, connected_integrations=set())
    included = {s.spec.stage for s in plan.included}
    excluded = {s.spec.stage: s.reason for s in plan.excluded}

    assert "serp_research" in excluded and "not connected" in excluded["serp_research"]
    assert "competitor_discovery" in excluded, "a hard dependent of an excluded stage is excluded"
    assert {"search_intent", "question_research", "competitive_gap"} <= included


# --- brand ------------------------------------------------------------------------
async def test_the_brand_profile_agent_proposes_without_changing_the_brand_graph(
    harness: AgentHarness,
) -> None:
    await harness.crawl()
    brands = BrandService(harness.session, harness.principal)
    before = await brands.profile(harness.brand_id)

    outcome = await harness.run("BRD-002")
    profile = outcome.result.outputs["brand_profile"]

    assert profile["brand_graph_changed"] is False
    assert profile["pages_compared"] > 5
    assert profile["covered"], "the demo services appear on the demo site"
    after = await brands.profile(harness.brand_id)
    assert len(after["services"]) == len(before["services"])
    assert len(after["locations"]) == len(before["locations"])
    assert all(r.evidence_ids for r in outcome.result.recommendations)


async def test_goals_without_their_data_source_are_reported_unmeasurable(
    bare_harness: AgentHarness,
) -> None:
    outcome = await bare_harness.run("BRD-003")
    objectives = outcome.result.outputs["business_objectives"]

    assert objectives["goals"] == 2 and objectives["measurable"] == 0
    leads = next(a for a in objectives["assessments"] if a["metric"] == "qualified_organic_leads")
    assert any("not connected" in blocker for blocker in leads["blockers"])
    visibility = next(a for a in objectives["assessments"] if a["goal_type"] == "visibility")
    assert visibility["metric"] == "organic_impressions", "the declared goal type wins"
    assert outcome.result.recommendations, "each blocker carries the fix"


# --- research -------------------------------------------------------------------
async def test_search_research_describes_measured_demand_with_its_provenance(
    harness: AgentHarness,
) -> None:
    await harness.run("ANA-001", {"days": 28})
    outcome = await harness.run("RES-001")
    research = outcome.result.outputs["search_research"]

    assert research["measured"] is True
    assert research["provenance"] == DataProvenance.SYNTHETIC_DEMO.value
    assert research["landscape"]["impressions"] > 0
    assert any("not been estimated" in lim for lim in outcome.result.limitations)
    assert any("synthetic" in lim for lim in outcome.result.limitations)


async def test_search_research_without_search_console_estimates_nothing(
    bare_harness: AgentHarness,
) -> None:
    outcome = await bare_harness.run("RES-001")
    assert outcome.result.outputs["search_research"]["measured"] is False
    assert outcome.result.outputs["search_research"]["landscape"] == {}
    assert any("gsc" in lim for lim in outcome.result.limitations)


async def test_serp_research_labels_synthetic_pages_everywhere(harness: AgentHarness) -> None:
    outcome = await harness.run("RES-002", {"queries": ["dna testing", "how much is a dna test"]})
    serp = outcome.result.outputs["serp_research"]

    assert serp["synthetic"] is True
    serp_evidence = [e for e in outcome.result.evidence if e.type is EvidenceType.SERP_RESULT]
    assert serp_evidence
    assert all(e.provenance is DataProvenance.SYNTHETIC_DEMO for e in serp_evidence)
    assert any("synthetic" in lim for lim in outcome.result.limitations)

    stored = await SearchService(harness.session, harness.principal).latest_snapshots(
        harness.brand_id
    )
    assert {s.query for s in stored} == {"dna testing", "how much is a dna test"}
    assert all(s.provenance is DataProvenance.SYNTHETIC_DEMO for s in stored)


async def test_serp_research_without_the_integration_observes_nothing(
    bare_harness: AgentHarness,
) -> None:
    outcome = await bare_harness.run("RES-002", {"queries": ["dna testing"]})
    assert "serp_research" not in outcome.result.outputs
    assert any("serp" in lim for lim in outcome.result.limitations)
    stored = await SearchService(bare_harness.session, bare_harness.principal).latest_snapshots(
        bare_harness.brand_id
    )
    assert stored == []


async def test_questions_keep_their_sources_and_weakest_provenance(harness: AgentHarness) -> None:
    await harness.crawl()
    await harness.run("RES-002", {"queries": ["how much does a dna test cost"]})
    outcome = await harness.run("RES-005")
    questions = outcome.result.outputs["question_research"]["questions"]

    paa = [q for q in questions if "serp_people_also_ask" in q["sources"]]
    assert paa and all(q["provenance"] == DataProvenance.SYNTHETIC_DEMO.value for q in paa)
    vocab = [q for q in questions if q["sources"] == ["brand_audience_vocabulary"]]
    assert vocab and all(q["provenance"] == DataProvenance.USER_PROVIDED.value for q in vocab)
    _seeds_cite_produced_evidence(outcome)


async def test_a_source_is_verified_only_when_a_fetch_succeeded(harness: AgentHarness) -> None:
    brands = BrandService(harness.session, harness.principal)
    claim = await brands.add_claim(
        harness.brand_id,
        claim="Rival publishes its DNA testing prices.",
        source="https://rival.test/guides/dna-testing-cost",
        risk="low",
    )
    await brands.approve_claim(claim.id)
    await harness.crawl()

    outcome = await harness.run("RES-006", {"max_fetch": 5})
    evidence = outcome.result.outputs["source_evidence"]
    sources = {s["url"]: s for s in evidence["sources"]}

    # A claim's named URL that answers 200 is verified...
    cited = sources["https://rival.test/guides/dna-testing-cost"]
    assert cited["verified"] is True
    assert cited["supports_claim"] == "Rival publishes its DNA testing prices."
    # ...a URL the brand links to that answers 404 is not, however it was found...
    assert sources["https://rival.test/compare"]["verified"] is False
    # ...and neither is authoritative: a reserved test domain is always tier 6.
    assert {s["tier"] for s in sources.values()} == {"tier_6_unverified"}

    ukas = next(c for c in evidence["claims"] if "UKAS" in c["claim"])
    assert ukas["status"] == "source_named_unverified", "a named certificate is not a fetch"
    assert any("verified source" in lim for lim in outcome.result.limitations)


# --- SEO ----------------------------------------------------------------------------
async def test_the_seo_analysis_agents_hand_over_evidenced_seeds(harness: AgentHarness) -> None:
    await harness.crawl()
    await harness.research_keywords()

    on_page = await harness.run("SEO-002")
    assert on_page.result.outputs["on_page"]["pages_assessed"] > 0
    _seeds_cite_produced_evidence(on_page)

    intent = await harness.run("SEO-004")
    assert intent.result.outputs["search_intent"]["pairs_assessed"] > 0
    _seeds_cite_produced_evidence(intent)

    architecture = await harness.run("SEO-005")
    assert architecture.result.outputs["keyword_architecture"]["clusters_analysed"] > 0
    _seeds_cite_produced_evidence(architecture)

    for outcome in (on_page, intent, architecture):
        assert outcome.result.actions == [], "analysis agents change nothing"


async def test_indexability_reports_the_sitemap_contradiction_and_not_the_unreached(
    harness: AgentHarness,
) -> None:
    await harness.crawl()
    outcome = await harness.run("SEO-012")
    report = outcome.result.outputs["indexability"]

    issues = {(i["issue"], i["url"]) for i in report["issues"]}
    assert ("sitemap_lists_non_indexable_url", "https://acme.test/noindex-page") in issues
    assert report["gsc_compared"] is True
    _seeds_cite_produced_evidence(outcome)


async def test_on_page_needs_a_mapped_keyword_and_says_so(harness: AgentHarness) -> None:
    await harness.crawl()
    outcome = await harness.run("SEO-002")
    assert "on_page" not in outcome.result.outputs
    assert any("keyword research" in lim.lower() for lim in outcome.result.limitations)


# --- competitors ----------------------------------------------------------------
async def test_synthetic_serp_domains_are_never_proposed_as_competitors(
    harness: AgentHarness,
) -> None:
    await harness.run("RES-002", {"queries": ["dna testing", "paternity test", "nipt test"]})
    outcome = await harness.run("CMP-001", {"minimum_appearances": 1})
    discovery = outcome.result.outputs["competitor_discovery"]

    assert discovery["synthetic"] is True
    assert discovery["candidates"], "the synthetic pages do contain recurring domains"
    assert all(c["domain"].endswith(".example") for c in discovery["candidates"])
    assert outcome.result.recommendations == [], "a synthetic domain is not a real company"
    assert discovery["brand_graph_changed"] is False


async def test_a_visibility_only_gap_on_synthetic_serps_is_not_an_opportunity(
    harness: AgentHarness,
) -> None:
    await harness.run("RES-002", {"queries": ["dna testing"]})
    outcome = await harness.run("CMP-003", {"keyword_gaps": [], "discovered_competitors": []})
    gaps = outcome.result.outputs["competitive_gap"]
    assert gaps["synthetic_serp"] is True
    assert outcome.result.outputs["opportunity_seeds"] == []


async def test_coverage_gaps_become_evidenced_seeds(harness: AgentHarness) -> None:
    outcome = await harness.run(
        "CMP-003",
        {"keyword_gaps": [{"keyword": "nipt cost", "competitor_domains": ["rival.test"]}]},
    )
    seeds = outcome.result.outputs["opportunity_seeds"]
    assert [s["opportunity_type"] for s in seeds] == ["competitor_gap"]
    _seeds_cite_produced_evidence(outcome)


# --- quality ---------------------------------------------------------------------
async def test_the_quality_guardian_flags_recommendations_on_synthetic_ground(
    harness: AgentHarness,
) -> None:
    collector = EvidenceCollector(
        harness.session, harness.principal.tenant_id, brand_id=harness.brand_id
    )
    synthetic = collector.observe(
        evidence_type=EvidenceType.GSC,
        source="google_search_console",
        observation="Synthetic impressions",
        provenance=DataProvenance.SYNTHETIC_DEMO,
    )
    await collector.persist()
    decisions = DecisionService(harness.session, harness.principal)
    await decisions.create_recommendation(
        harness.brand_id,
        ProposedRecommendation(
            type="ctr_improvement",
            title="Rewrite the title on the pricing page",
            problem="Low CTR",
            opportunity="More clicks",
            reason="Synthetic impressions say so",
            risk=RiskLevel.LOW,
            confidence=0.7,
            expected_outcome="Higher CTR",
            evidence_ids=[synthetic.id, "ev_missing"],
        ),
    )

    outcome = await harness.run("QUAL-001")
    audit = outcome.result.outputs["quality_audit"]
    assert audit["by_rule"]["synthetic_only_basis"] == 1
    assert audit["by_rule"]["dangling_evidence"] == 1
    assert audit["quality_score"] < 100


async def test_a_full_mission_feeds_every_seed_into_the_decision_chain(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)
    async with build_web_client() as client:
        harness = AgentHarness(session, principal, scenario.brand.id, scenario.website.id, client)
        workflow = MissionWorkflow(
            session,
            principal,
            extra_services={"crawler_factory": harness.crawler_factory},
            options={"max_pages": 30, "max_depth": 3},
        )
        mission, plan = await workflow.plan(
            scenario.brand.id, DEMO_OBJECTIVE, website_id=scenario.website.id
        )
        report = await workflow.run(mission, plan)

    assert report.failed_stages == []
    sources = report.outputs["opportunity_detection"]["opportunity_detection"]["by_source"]
    assert {"SEO-002", "SEO-012"} <= set(sources), "analysis seeds reached opportunity detection"
    quality = report.outputs["quality_review"]["quality_audit"]
    assert quality["audited"] > 0
    assert quality["by_rule"].get("dangling_evidence", 0) == 0, (
        "every recommendation's evidence must resolve after a full mission"
    )

    # A concrete change detected upstream travels with the recommendation, so the
    # executor can apply exactly what was approved.
    recommendations = await DecisionService(session, principal).list_recommendations(
        scenario.brand.id
    )
    carried = [
        r.proposed_action["change"]
        for r in recommendations
        if (r.proposed_action or {}).get("change")
    ]
    assert carried, "no recommendation carried its concrete change"
    assert all(c.get("title") or c.get("from_urls") for c in carried)

    # Nothing executes in a mission: every planned action awaits a person.
    plan = report.outputs["execution_plan"]["execution_plan"]
    assert plan["actions_executed"] == 0
    assert plan["actions_awaiting_approval"] == plan["actions_proposed"]


async def test_the_audit_reports_search_console_availability_truthfully(
    harness: AgentHarness, bare_harness: AgentHarness
) -> None:
    connected = await harness.crawl()
    assert not any(
        "Search Console was unavailable" in lim for lim in connected.result.limitations
    ), "a connected Search Console must not be reported as unavailable"

    absent = await bare_harness.crawl()
    assert any(
        "Search Console was unavailable" in lim and "not connected" in lim
        for lim in absent.result.limitations
    )
