"""Unit tests for the deterministic engines behind the research, architecture,
brand, competitive, content-production and guardian agents.

Each test asserts a behaviour the specification requires, not merely that a
function returns: a bounded crawl's unreached URLs are unverified rather than
broken, a synthetic SERP keeps its label through every figure, a prohibition
quoted to the writer is not mistaken for the claim, and so on.
"""

from __future__ import annotations

from seo_engine.engines.brand.objectives import assess_goal, metric_for_goal
from seo_engine.engines.brand.profile import DeclaredItem, compare_profile
from seo_engine.engines.competitors.gap import competitive_gaps
from seo_engine.engines.content.compliance import check_compliance
from seo_engine.engines.content.generation import build_outline
from seo_engine.engines.content.optimisation import optimisation_edits
from seo_engine.engines.content.quality import quality_gate
from seo_engine.engines.content.strategy import build_roadmap
from seo_engine.engines.keywords.architecture import (
    MappedKeyword,
    cluster_structures,
    find_cannibalisation,
)
from seo_engine.engines.keywords.intent_fit import PageType, assess_fit, classify_page_type
from seo_engine.engines.quality.audit import (
    EvidenceFacts,
    RecommendationFacts,
    audit_recommendations,
)
from seo_engine.engines.research.demand import VISIBILITY_LIMITATION, demand_landscape
from seo_engine.engines.research.questions import gather_questions, map_to_pages
from seo_engine.engines.research.serp import summarise_serps
from seo_engine.engines.research.sources import build_source, claim_coverage, tier_for_url
from seo_engine.engines.seo.indexability import IndexState, classify_state, reconcile
from seo_engine.engines.seo.onpage import alignment_report, assess_alignment, propose_title
from seo_engine.engines.seo.pages import PageFacts
from seo_engine.schemas.content import (
    ContentBrief,
    ContentDraft,
    ContentEvaluation,
    ContentSection,
    EvaluationCriterionResult,
    InternalLinkTarget,
)
from seo_engine.schemas.enums import (
    ContentDecision,
    DataProvenance,
    RiskCategory,
    SourceTier,
)
from seo_engine.schemas.search import IntentDistribution, SERPResultItem, SERPSnapshot
from seo_engine.shared.ids import utcnow


def _page(url: str, **kwargs) -> PageFacts:
    kwargs.setdefault("indexability", "indexable")
    return PageFacts(url=url, **kwargs)


def _snapshot(query: str, domains: list[str], *, synthetic: bool = False, features=None):
    return SERPSnapshot(
        query=query,
        observed_at=utcnow(),
        provider="test",
        provenance=DataProvenance.SYNTHETIC_DEMO if synthetic else DataProvenance.OBSERVED,
        features=features or [],
        results=[
            SERPResultItem(position=i + 1, url=f"https://{d}/p", domain=d, result_type="organic")
            for i, d in enumerate(domains)
        ],
    )


# --- on-page alignment ------------------------------------------------------
def test_a_page_that_never_names_its_keyword_is_misaligned() -> None:
    page = _page(
        "https://acme.test/services/dna",
        title="Welcome",
        h1="Our work",
        meta_description="We do things.",
        text="Lorem ipsum " * 50,
    )
    result = assess_alignment(page, "paternity test", brand_name="Acme")
    assert not result.aligned
    assert "title" in result.missing_from
    assert result.proposed_title == "Paternity Test | Acme"
    assert result.meta_guidance and "no description has been generated" in result.meta_guidance


def test_an_aligned_page_proposes_nothing() -> None:
    page = _page(
        "https://acme.test/services/paternity-test",
        title="Paternity test | Acme",
        h1="Paternity test",
        meta_description="An accredited paternity test with results in days.",
        text="Our paternity test is accredited.",
    )
    result = assess_alignment(page, "paternity test")
    assert result.aligned and result.proposed_title is None


def test_a_long_title_drops_the_brand_before_truncating_the_keyword() -> None:
    keyword = "non invasive prenatal screening for twin pregnancies in manchester"
    assert propose_title(keyword, "Acme Diagnostics") == propose_title(keyword, "")


def test_pages_without_a_mapped_keyword_are_not_judged() -> None:
    pages = [_page("https://acme.test/a", title="A"), _page("https://acme.test/b", title="B")]
    assert [a.url for a in alignment_report(pages, {"https://acme.test/a/": "dna"})] == [
        "https://acme.test/a"
    ]


# --- indexability -----------------------------------------------------------
def test_index_states_follow_the_stored_indexability() -> None:
    assert classify_state(_page("https://a.test/x")) is IndexState.INDEXABLE
    assert (
        classify_state(
            _page(
                "https://a.test/x",
                indexability="not_indexable",
                indexability_reason="noindex directive",
            )
        )
        is IndexState.NOINDEX
    )
    assert classify_state(_page("https://a.test/x", status_code=404)) is IndexState.CLIENT_ERROR
    assert (
        classify_state(_page("https://a.test/x", indexability="canonicalised"))
        is IndexState.CANONICALISED
    )


def test_a_non_indexable_priority_landing_page_is_critical() -> None:
    pages = [
        _page("https://a.test/"),
        _page(
            "https://a.test/services/dna",
            indexability="not_indexable",
            indexability_reason="noindex directive",
        ),
    ]
    report = reconcile(
        pages,
        sitemap_urls=["https://a.test/", "https://a.test/services/dna", "https://a.test/never"],
        priority_urls={"https://a.test/services/dna": "DNA testing"},
    )
    issues = {(i.issue, i.severity) for i in report.issues}
    assert ("priority_url_not_indexable", "critical") in issues
    assert ("sitemap_lists_non_indexable_url", "high") in issues
    # A sitemap URL the crawl never reached is unverified, not broken.
    assert report.sitemap_unverified == ["a.test/never"]
    assert not any(i.url.endswith("/never") for i in report.issues)


def test_search_console_impressions_on_a_404_are_reported() -> None:
    report = reconcile(
        [_page("https://a.test/gone", status_code=404, indexability="not_indexable")],
        gsc_urls=["https://a.test/gone"],
    )
    assert any(i.issue == "earning_url_not_indexable" for i in report.issues)


# --- intent fit and architecture ---------------------------------------------
def test_page_type_is_read_from_structure_and_says_why() -> None:
    decision = classify_page_type(_page("https://a.test/blog/what-is-nipt", title="What is NIPT"))
    assert decision.page_type is PageType.ARTICLE and "URL path" in decision.signal
    assert classify_page_type(_page("https://a.test/")).page_type is PageType.HOME


def test_a_transactional_query_on_a_blog_post_is_a_mismatch() -> None:
    intent = IntentDistribution(transactional=0.8, informational=0.2)
    fit = assess_fit(_page("https://a.test/blog/book-a-test"), "book dna test", intent)
    assert fit.fits is False
    assert fit.recommended_page_type is PageType.SERVICE


def test_an_unidentifiable_page_type_asserts_no_mismatch() -> None:
    fit = assess_fit(_page("https://a.test/xyz"), "dna", IntentDistribution(transactional=1))
    assert fit.fits is True and fit.recommended_page_type is None


def test_cannibalisation_names_the_competing_urls_and_a_primary() -> None:
    keywords = [
        MappedKeyword("dna test", "c1", "dna test", "https://a.test/dna", 80, True),
        MappedKeyword("dna test cost", "c1", "dna test", "https://a.test/blog/dna-cost", 40),
    ]
    found = find_cannibalisation(
        keywords, [_page("https://a.test/dna"), _page("https://a.test/blog/dna-cost")]
    )
    assert found and found[0].urls == ["https://a.test/blog/dna-cost", "https://a.test/dna"]
    assert found[0].recommended_primary == "https://a.test/dna"


def test_a_spoke_that_never_links_to_its_hub_is_reported() -> None:
    keywords = [
        MappedKeyword("dna test", "c1", "dna", "https://a.test/dna", 80, True),
        MappedKeyword("dna test cost", "c1", "dna", "https://a.test/dna-cost", 40),
        MappedKeyword("dna test time", "c1", "dna", "https://a.test/dna-time", 30),
    ]
    links = [("https://a.test/dna-time", "https://a.test/dna/")]
    structure = cluster_structures(keywords, links)[0]
    assert structure.hub_url == "https://a.test/dna"
    assert structure.spokes_missing_hub_link == ["https://a.test/dna-cost"]


# --- research -----------------------------------------------------------------
def test_the_demand_landscape_carries_provenance_and_its_limitation() -> None:
    rows = [
        {
            "query": "acme dna",
            "impressions": 100,
            "clicks": 20,
            "position": 1.2,
            "provenance": "synthetic_demo",
        },
        {
            "query": "how much is a dna test",
            "impressions": 300,
            "clicks": 5,
            "position": 14.0,
            "provenance": "synthetic_demo",
        },
    ]
    landscape = demand_landscape(rows, brand_terms={"acme"})
    assert landscape.provenance == "synthetic_demo"
    assert landscape.branded_share == 0.25
    assert landscape.question_share == 0.75
    assert landscape.striking_distance[0]["query"] == "how much is a dna test"
    assert landscape.as_dict()["limitation"] == VISIBILITY_LIMITATION


def test_no_rows_means_no_figures() -> None:
    landscape = demand_landscape([], brand_terms={"acme"})
    assert landscape.impressions == 0 and landscape.provenance == "unknown"


def test_a_synthetic_serp_stays_labelled_through_the_summary() -> None:
    snapshots = [
        _snapshot("dna test", ["rival.test", "acme.test", "x.test"], synthetic=True),
        _snapshot("paternity test", ["rival.test", "y.test"], synthetic=True),
    ]
    landscape = summarise_serps(snapshots, brand_domain="acme.test")
    assert landscape.synthetic is True
    assert landscape.brand_positions == {"dna test": 2, "paternity test": None}
    assert landscape.recurring_domains[0] == {
        "domain": "rival.test",
        "appearances": 2,
        "average_position": 1.0,
    }


def test_questions_merge_sources_and_keep_the_weakest_provenance() -> None:
    questions = gather_questions(
        gsc_queries=[
            {"query": "how much is a dna test", "impressions": 40, "provenance": "observed"}
        ],
        serp_questions=[("How much is a DNA test?", DataProvenance.SYNTHETIC_DEMO)],
        audience_questions=["is it safe", "not a question at all"],
    )
    merged = next(q for q in questions if "dna" in q.question.lower())
    assert merged.sources == ["search_console", "serp_people_also_ask"]
    assert merged.provenance is DataProvenance.SYNTHETIC_DEMO
    assert {q.question for q in questions} == {"How much is a dna test?", "Is it safe?"}


def test_a_question_is_answered_by_a_matching_heading() -> None:
    questions = gather_questions(audience_questions=["how much does a dna test cost"])
    pages = [_page("https://a.test/pricing", headings=["How much does a DNA test cost?"])]
    mapped = map_to_pages(questions, pages)
    assert mapped[0].answered_by_url == "https://a.test/pricing"
    assert mapped[0].answered_in == "heading"


def test_source_tiers_follow_explicit_rules() -> None:
    assert tier_for_url("https://www.nhs.uk/conditions").tier is SourceTier.TIER_1_PRIMARY
    assert tier_for_url("https://www.bmj.com/x").tier is SourceTier.TIER_2_AUTHORITATIVE
    assert tier_for_url("https://www.reddit.com/r/x").tier is SourceTier.TIER_5_COMMUNITY
    assert tier_for_url("https://synthetic-result-1.example/x").tier is SourceTier.TIER_6_UNVERIFIED
    unverified = build_source(
        "https://www.nhs.uk/x", title="x", retrieved_at=utcnow(), verified=False
    )
    assert unverified.verified is False and unverified.reliability <= 0.5


def test_a_named_but_unfetched_source_does_not_count_as_support() -> None:
    coverage = claim_coverage(
        [("Our laboratory is UKAS accredited.", "UKAS certificate 1234"), ("We are fast.", None)],
        [],
    )
    assert [c.status for c in coverage] == ["source_named_unverified", "unsourced"]


# --- brand ---------------------------------------------------------------------
def test_profile_comparison_proposes_but_never_asserts() -> None:
    pages = [
        _page("https://a.test/services/dna-testing", title="DNA testing"),
        _page("https://a.test/services/drug-testing", title="Drug testing"),
    ]
    declared = [
        DeclaredItem("service", "DNA testing"),
        DeclaredItem(
            "service", "Prenatal screening", landing_url="https://a.test/services/prenatal"
        ),
    ]
    comparison = compare_profile(pages, declared, brand_name="Acme")
    kinds = {(p.proposal, p.subject) for p in comparison.proposals}
    assert ("declared_not_found", "Prenatal screening") in kinds
    assert ("found_not_declared", "drug testing") in kinds
    assert comparison.covered[0]["name"] == "DNA testing"


def test_a_lead_goal_without_analytics_is_not_measurable() -> None:
    assert metric_for_goal("Increase qualified organic leads", "acquisition", None) == (
        "qualified_organic_leads"
    )
    assessment = assess_goal(
        description="Increase qualified organic leads",
        goal_type="acquisition",
        stated_metric=None,
        target_value=None,
        timeframe="6 months",
        connected=set(),
        lead_events_confirmed=False,
        has_website=True,
    )
    assert assessment.measurable is False
    assert "not connected" in assessment.blockers[0]
    assert "No target value is set." in assessment.specificity_gaps


def test_a_lead_goal_needs_confirmed_lead_events() -> None:
    assessment = assess_goal(
        description="More enquiries",
        goal_type="acquisition",
        stated_metric=None,
        target_value=50,
        timeframe="6 months",
        connected={"google_analytics_4"},
        lead_events_confirmed=False,
        has_website=True,
    )
    assert assessment.measurable is False
    assert "Confirm which events are leads" in assessment.blockers[0]


# --- competitive gaps -----------------------------------------------------------
def test_a_topic_with_coverage_and_visibility_gaps_scores_highest() -> None:
    gaps = competitive_gaps(
        keyword_gaps=[
            {"keyword": "nipt cost", "competitor_domains": ["rival.test"]},
            {"keyword": "dna kit", "competitor_domains": ["rival.test"]},
        ],
        snapshots=[_snapshot("nipt cost", ["rival.test", "other.test"])],
        brand_domain="acme.test",
        competitor_domains={"rival.test"},
    )
    assert gaps[0].topic == "nipt cost"
    assert gaps[0].gap_types == ["coverage", "visibility"]
    assert gaps[0].score > gaps[1].score


def test_no_gap_where_the_brand_already_outranks() -> None:
    gaps = competitive_gaps(
        keyword_gaps=[],
        snapshots=[_snapshot("dna test", ["acme.test", "rival.test"])],
        brand_domain="acme.test",
        competitor_domains={"rival.test"},
    )
    assert gaps == []


# --- content production ---------------------------------------------------------
def _brief(**kwargs) -> ContentBrief:
    defaults = {
        "title": "How much does a DNA test cost?",
        "primary_topic": "dna test cost",
        "primary_keyword": "dna test cost",
        "audience": "Parents",
        "business_goal": "Leads",
        "unique_value_proposition": "Accredited",
        "required_sections": ["What affects the price", "What is included"],
        "questions_to_answer": ["How long do results take?"],
        "prohibited_claims": ["Our tests are 100% accurate."],
        "approved_claims": ["Our laboratory is UKAS accredited for DNA testing."],
        "risk_category": RiskCategory.HEALTH,
        "target_word_count": 800,
        "cta": "Book a test",
    }
    defaults.update(kwargs)
    return ContentBrief(**defaults)


def _prose(body: str, **kwargs) -> ContentDraft:
    return ContentDraft(
        title=kwargs.get("title", "How much does a DNA test cost?"),
        meta_description="Pricing explained.",
        slug="dna-test-cost",
        sections=[ContentSection(heading="What affects the price", body=body)],
        body_markdown=f"## What affects the price\n\n{body}",
        unverified_claims=kwargs.get("unverified_claims", []),
    )


def test_the_roadmap_fixes_before_it_creates_and_respects_capacity() -> None:
    gaps = [
        {
            "topic": f"new topic {i}",
            "decision": "create",
            "intent": {"transactional": 1},
            "confidence": 0.9,
        }
        for i in range(5)
    ] + [
        {
            "topic": "dna testing",
            "decision": "update",
            "intent": {"commercial": 1},
            "confidence": 0.5,
        },
        {"topic": "idle", "decision": "do_nothing", "decision_reason": "no demand"},
    ]
    roadmap = build_roadmap(
        gaps, services=[("DNA testing", ["dna test"])], months=1, capacity_per_month=3
    )
    assert roadmap.items[0].decision is ContentDecision.UPDATE
    assert roadmap.items[0].service == "DNA testing"
    assert len(roadmap.items) == 3 and len(roadmap.backlog) == 3
    assert roadmap.not_pursued == [{"topic": "idle", "reason": "no demand"}]


def test_the_gate_blocks_an_outline_however_well_it_scores() -> None:
    brief = _brief()
    outline = build_outline(brief)
    result = quality_gate(
        outline, brief, evaluation=ContentEvaluation(overall_score=90, passed=True)
    )
    assert result.passed is False
    assert any("outline" in b for b in result.blocking)
    assert result.requires_human_review is True


def test_the_gate_blocks_duplicates_thin_copy_and_scaled_templates() -> None:
    body = " ".join(["The price of an accredited test depends on the sample type."] * 20)
    draft = _prose(body, title="DNA test cost in Leeds")
    result = quality_gate(
        draft,
        _brief(target_word_count=2000),
        evaluation=ContentEvaluation(overall_score=80, passed=True),
        other_bodies={"asset:1": body},
        sibling_titles=["DNA test cost in York", "DNA test cost in Hull"],
    )
    blocks = " ".join(result.blocking)
    assert "duplicates existing content" in blocks
    assert "too thin" in blocks
    assert "scaled content" in blocks


def test_the_gate_requires_an_evaluation() -> None:
    result = quality_gate(_prose("words " * 500), _brief(target_word_count=300), evaluation=None)
    assert result.passed is False and "not been evaluated" in result.blocking[0]


def test_compliance_ignores_prohibitions_quoted_to_the_writer() -> None:
    brief = _brief()
    outline = build_outline(brief)
    result = check_compliance(
        outline,
        prohibited_claims=brief.prohibited_claims,
        forbidden_terms=["guaranteed"],
        risk_category=RiskCategory.GENERAL,
    )
    assert not [v for v in result.violations if v["rule"] == "prohibited_claim"]


def test_compliance_blocks_prohibited_claims_and_absolutes_in_regulated_copy() -> None:
    draft = _prose(
        "Our tests are 100% accurate and results are guaranteed.",
        unverified_claims=["a statistic from an unfetched page"],
    )
    result = check_compliance(
        draft,
        prohibited_claims=["Our tests are 100% accurate."],
        forbidden_terms=["guaranteed"],
        risk_category=RiskCategory.HEALTH,
    )
    rules = {v["rule"] for v in result.violations}
    assert {
        "prohibited_claim",
        "forbidden_terminology",
        "unverified_claim_in_regulated_content",
        "absolute_outcome_language",
    } <= rules
    assert result.compliant is False


def test_optimisation_turns_weak_criteria_into_specific_edits() -> None:
    brief = _brief(
        internal_links=[InternalLinkTarget(url="https://a.test/pricing", anchor_text="pricing")]
    )
    draft = _prose("Price depends on the test.", title="Pricing")
    evaluation = ContentEvaluation(
        criteria=[
            EvaluationCriterionResult(criterion="completeness", score=40, passed=False),
            EvaluationCriterionResult(criterion="internal_linking", score=30, passed=False),
        ],
        overall_score=65,
        passed=True,
    )
    edits = {(e.edit_type, e.target) for e in optimisation_edits(draft, brief, evaluation)}
    assert ("add_section", "headings") in edits
    assert ("answer_question", "body") in edits
    assert ("add_internal_link", "https://a.test/pricing") in edits
    assert ("retitle", "title") in edits


# --- quality audit ----------------------------------------------------------------
def _rec(**kwargs) -> RecommendationFacts:
    defaults = {
        "id": "r1",
        "title": "Fix titles",
        "recommendation_type": "technical_fix",
        "status": "proposed",
        "evidence_refs": ["ev1"],
        "confidence": 0.7,
        "is_hypothesis": False,
        "risk": "low",
        "approval_required": True,
        "expected_outcome": "Higher CTR",
    }
    defaults.update(kwargs)
    return RecommendationFacts(**defaults)


def test_the_audit_flags_synthetic_dangling_and_overconfident_recommendations() -> None:
    evidence = {
        "ev1": EvidenceFacts("ev1", "synthetic_demo", True, 0.9),
        "ev2": EvidenceFacts("ev2", "inferred", False, 0.5),
    }
    report = audit_recommendations(
        [
            _rec(id="r1"),
            _rec(id="r2", title="Other", evidence_refs=["ev2", "missing"], confidence=0.8),
            _rec(id="r3", title="Risky", risk="high", approval_required=False, expected_outcome=""),
            _rec(id="r4"),
        ],
        evidence,
    )
    rules = report.by_rule()
    assert rules["synthetic_only_basis"] == 3
    assert rules["dangling_evidence"] == 1
    assert rules["inference_only_overconfident"] == 1
    assert rules["confidence_exceeds_evidence"] == 1
    assert rules["high_risk_without_approval"] == 1
    assert rules["no_expected_outcome"] == 1
    assert rules["duplicate_recommendation"] == 1
    assert report.quality_score == 0.0


def test_a_well_founded_recommendation_is_clean() -> None:
    report = audit_recommendations([_rec()], {"ev1": EvidenceFacts("ev1", "observed", True, 0.9)})
    assert report.issues == [] and report.clean == 1 and report.quality_score == 100.0
