"""Keyword pipeline, intent classification and competitor/gap engine tests."""

from __future__ import annotations

import pytest
from seo_engine.engines.competitors.analysis import (
    CompetitorPages,
    analyse_content_gap,
    classify_competitor_types,
    discover_serp_competitors,
    keyword_gaps,
    page_quality_score,
)
from seo_engine.engines.crawler.parser import PageParser
from seo_engine.engines.keywords.intent import (
    classify_intent,
    intent_commercial_value,
    refine_with_serp,
)
from seo_engine.engines.keywords.pipeline import (
    KeywordInputs,
    build_keyword_records,
    cluster_keywords,
    dedupe_key,
    deduplicate,
    map_to_pages,
    normalise,
    recommend_cluster_decision,
)
from seo_engine.schemas.enums import (
    CompetitorType,
    ContentDecision,
    DataProvenance,
    SearchIntent,
)
from seo_engine.schemas.search import (
    CompetitorProfile,
    KeywordCluster,
    SERPResultItem,
    SERPSnapshot,
)
from seo_engine.shared.ids import utcnow


# --- Intent -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("how does a dna test work", SearchIntent.INFORMATIONAL),
        ("best dna testing service", SearchIntent.COMMERCIAL),
        ("book a dna test appointment", SearchIntent.TRANSACTIONAL),
        ("acme diagnostics login", SearchIntent.NAVIGATIONAL),
        ("dna testing clinic near me", SearchIntent.LOCAL),
        ("is a home dna test worth it", SearchIntent.INVESTIGATIONAL),
    ],
)
def test_intent_classification(keyword: str, expected: SearchIntent) -> None:
    assert classify_intent(keyword).primary is expected


def test_intent_is_a_distribution_not_a_label() -> None:
    """A real query carries more than one intent."""
    intent = classify_intent("how much does the best dna test cost near me")
    active = intent.as_dict()
    assert len(active) >= 3, f"expected a mixed distribution, got {active}"
    assert sum(active.values()) == pytest.approx(1.0, abs=1e-3)


def test_a_brand_term_makes_a_query_navigational() -> None:
    intent = classify_intent("acme diagnostics", brand_terms={"acme"})
    assert intent.navigational > 0


def test_a_known_location_makes_a_query_local() -> None:
    intent = classify_intent("dna testing lagos", location_terms={"lagos"})
    assert intent.local > 0


def test_serp_features_refine_the_lexical_classification() -> None:
    # A query with no lexical local signal at all.
    lexical = classify_intent("dna testing")
    assert lexical.local == 0.0

    # But the SERP shows a local pack, which is a far stronger signal.
    refined = refine_with_serp(
        lexical,
        SERPSnapshot(
            query="dna testing",
            observed_at=utcnow(),
            provider="test",
            features=["local_pack"],
        ),
    )
    assert refined.local > lexical.local


def test_an_unavailable_serp_never_changes_the_classification() -> None:
    """Absent data must not silently become a signal."""
    lexical = classify_intent("dna testing centre")
    refined = refine_with_serp(
        lexical,
        SERPSnapshot(
            query="x",
            observed_at=utcnow(),
            provider="none",
            available=False,
            unavailable_reason="no provider connected",
        ),
    )
    assert refined.model_dump() == lexical.model_dump()


def test_transactional_intent_is_worth_more_than_informational() -> None:
    assert intent_commercial_value(classify_intent("buy dna test kit")) > intent_commercial_value(
        classify_intent("what is dna")
    )


# --- Normalisation and dedupe -----------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  DNA   Testing  ", "dna testing"),
        ("Café tests", "cafe tests"),
        ("DNA & Paternity", "dna and paternity"),
    ],
)
def test_normalisation(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_word_order_and_stopword_variants_deduplicate_together() -> None:
    assert dedupe_key("dna test for paternity") == dedupe_key("paternity dna test")


def test_deduplication_prefers_observed_forms_over_generated_ones() -> None:
    result = deduplicate([("paternity dna test", "expansion"), ("dna paternity test", "observed")])
    assert result == [("dna paternity test", "observed")]


# --- Pipeline ---------------------------------------------------------------
def _inputs(**overrides) -> KeywordInputs:
    base = {
        "brand_name": "Acme Diagnostics",
        "services": ["DNA testing", "prenatal screening"],
        "locations": ["Lagos"],
        "audience_vocabulary": ["paternity test"],
    }
    base.update(overrides)
    return KeywordInputs(**base)


def test_seeds_derive_only_from_supplied_business_facts() -> None:
    records = build_keyword_records(_inputs())
    keywords = " ".join(r.normalised for r in records)
    assert "dna testing" in keywords
    assert "prenatal screening" in keywords
    # Nothing about an unrelated industry can appear.
    assert "insurance" not in keywords
    assert "roofing" not in keywords


def test_an_empty_brand_produces_no_keywords_rather_than_invented_ones() -> None:
    assert build_keyword_records(KeywordInputs()) == []


def test_service_and_location_combine_into_a_local_keyword() -> None:
    records = build_keyword_records(_inputs())
    assert any(r.is_local and "lagos" in r.normalised for r in records)


def test_metrics_are_unknown_when_no_provider_is_connected() -> None:
    """Rule 14: never fabricate search volume."""
    records = build_keyword_records(_inputs())
    volumes = [r.metric("search_volume") for r in records if r.metric("search_volume")]
    assert volumes
    assert all(m.value is None for m in volumes)
    assert all(m.provenance is DataProvenance.UNKNOWN for m in volumes)


def test_observed_search_console_queries_are_marked_observed() -> None:
    records = build_keyword_records(
        _inputs(observed_queries=[("dna test cost lagos", 1200, 30, 8.4)])
    )
    record = next(r for r in records if r.normalised == "dna test cost lagos")
    impressions = record.metric("impressions")
    assert impressions.value == 1200
    assert impressions.provenance is DataProvenance.OBSERVED
    assert impressions.source == "google_search_console"


def test_demand_scores_only_where_demand_was_measured() -> None:
    records = build_keyword_records(
        _inputs(observed_queries=[("dna test cost lagos", 1200, 30, 8.4)])
    )
    measured = next(r for r in records if r.normalised == "dna test cost lagos")
    unmeasured = next(r for r in records if r.metric("search_volume"))

    assert measured.score.demand > 0
    assert "demand" in measured.score.dimensions_with_observed_data
    assert unmeasured.score.demand == 0
    assert "demand" not in unmeasured.score.dimensions_with_observed_data


def test_the_opportunity_score_follows_the_documented_weighting() -> None:
    records = build_keyword_records(_inputs())
    record = records[0]
    expected = sum(
        record.score.model_dump()[key] * weight for key, weight in record.score.weights.items()
    )
    assert record.score.opportunity_score == pytest.approx(round(expected, 2))


def test_a_service_keyword_outranks_an_unrelated_one_on_business_relevance() -> None:
    records = build_keyword_records(
        _inputs(competitor_terms=["office furniture"]),
    )
    service = next(r for r in records if r.normalised == "dna testing")
    unrelated = next(r for r in records if r.normalised == "office furniture")
    assert service.score.business_relevance > unrelated.score.business_relevance


def test_branded_keywords_are_flagged() -> None:
    records = build_keyword_records(_inputs(existing_keywords=["acme diagnostics reviews"]))
    assert any(r.is_branded for r in records)


# --- Clustering -------------------------------------------------------------
def test_related_keywords_cluster_together_and_unrelated_ones_do_not() -> None:
    records = build_keyword_records(
        KeywordInputs(
            services=["dna paternity testing"],
            existing_keywords=[
                "dna paternity testing cost",
                "dna paternity testing accuracy",
                "commercial roof insulation",
            ],
        )
    )
    clusters = cluster_keywords(records)
    by_keyword = {k: c.id for c in clusters for k in c.keywords}

    paternity = [k for k in by_keyword if "paternity" in k]
    assert len({by_keyword[k] for k in paternity}) <= 2
    roof = next(k for k in by_keyword if "roof" in k)
    assert by_keyword[roof] not in {by_keyword[k] for k in paternity}


def test_clustering_is_deterministic() -> None:
    records = build_keyword_records(_inputs())
    first = [(c.id, tuple(sorted(c.keywords))) for c in cluster_keywords(records)]
    records2 = build_keyword_records(_inputs())
    second = [(c.id, tuple(sorted(c.keywords))) for c in cluster_keywords(records2)]
    assert first == second


def test_every_keyword_is_assigned_to_a_cluster() -> None:
    records = build_keyword_records(_inputs())
    clusters = cluster_keywords(records)
    clustered = {k for c in clusters for k in c.keywords}
    assert clustered == {r.keyword for r in records}


# --- Mapping ----------------------------------------------------------------
def test_keywords_map_to_the_page_that_targets_them() -> None:
    records = build_keyword_records(
        _inputs(),
        pages={
            "https://acme.test/services/dna-testing": {
                "title": "DNA testing services",
                "h1": "DNA testing services",
                "text": "dna testing paternity",
            },
            "https://acme.test/about": {"title": "About us", "h1": "About", "text": "team"},
        },
    )
    mapped = next(r for r in records if r.normalised == "dna testing")
    assert mapped.mapped_url == "https://acme.test/services/dna-testing"


def test_an_unrelated_keyword_maps_to_nothing() -> None:
    from seo_engine.schemas.search import KeywordRecord

    record = KeywordRecord(
        keyword="commercial roof insulation", normalised="commercial roof insulation"
    )
    url, score = map_to_pages(
        record,
        {"https://acme.test/dna": {"title": "DNA testing", "h1": "DNA testing", "text": "dna"}},
    )
    assert url is None
    assert score < 0.3


# --- Cluster decisions ------------------------------------------------------
def test_a_well_covered_cluster_is_left_alone() -> None:
    cluster = KeywordCluster(
        id="c1", label="dna testing", head_keyword="dna testing", opportunity_score=80
    )
    assert (
        recommend_cluster_decision(cluster, mapped_urls=["/a"], best_page_quality=90)
        is ContentDecision.DO_NOTHING
    )


def test_a_weakly_covered_cluster_is_updated_not_recreated() -> None:
    cluster = KeywordCluster(
        id="c1", label="dna testing", head_keyword="dna testing", opportunity_score=80
    )
    assert (
        recommend_cluster_decision(cluster, mapped_urls=["/a"], best_page_quality=40)
        is ContentDecision.UPDATE
    )


def test_multiple_competing_pages_are_consolidated() -> None:
    cluster = KeywordCluster(
        id="c1", label="dna testing", head_keyword="dna testing", opportunity_score=80
    )
    assert (
        recommend_cluster_decision(cluster, mapped_urls=["/a", "/b"], best_page_quality=60)
        is ContentDecision.CONSOLIDATE
    )


def test_a_low_value_uncovered_cluster_does_not_justify_a_page() -> None:
    """Rule 13: a keyword alone is never a reason to publish."""
    cluster = KeywordCluster(id="c1", label="obscure", head_keyword="obscure", opportunity_score=5)
    assert (
        recommend_cluster_decision(cluster, mapped_urls=[], best_page_quality=None)
        is ContentDecision.DO_NOTHING
    )


# --- Competitors ------------------------------------------------------------
def _page(url: str, title: str, *, words: int = 400, schema: bool = False):
    body = "<p>" + ("Useful body copy about the subject. " * words) + "</p>"
    head = '<script type="application/ld+json">{"@type":"Article"}</script>' if schema else ""
    html = (
        f'<!doctype html><html lang="en"><head><title>{title}</title>'
        f'<meta name="description" content="A description long enough to be useful here.">'
        f"{head}</head><body><main><h1>{title}</h1><h2>a</h2><h2>b</h2><h2>c</h2>"
        f'{body}<a href="/contact">Contact</a><form><input id="x"><label for="x">X</label>'
        f"</form></main></body></html>"
    )
    return PageParser(allowed_domains={"acme.test", "rival.test"}).parse(
        url=url, html=html, status_code=200, content_type="text/html"
    )


def test_page_quality_rewards_a_well_equipped_page() -> None:
    strong = _page("https://acme.test/a", "DNA testing services", words=300, schema=True)
    weak = PageParser(allowed_domains={"acme.test"}).parse(
        url="https://acme.test/b", html="<html><body><p>Thin.</p></body></html>", status_code=200
    )
    assert page_quality_score(strong) > page_quality_score(weak)


def test_a_business_competitor_is_only_promoted_to_serp_on_observation() -> None:
    profile = CompetitorProfile(name="Rival", domain="rival.test", types=[CompetitorType.BUSINESS])
    assert classify_competitor_types(profile, serp_snapshots=[]) == [CompetitorType.BUSINESS]

    snapshot = SERPSnapshot(
        query="dna testing lagos",
        observed_at=utcnow(),
        provider="test",
        results=[SERPResultItem(position=1, url="https://rival.test/dna", domain="rival.test")],
    )
    promoted = classify_competitor_types(profile, serp_snapshots=[snapshot])
    assert CompetitorType.SERP in promoted


def test_serp_competitors_are_discovered_only_from_observed_results() -> None:
    assert discover_serp_competitors([], brand_domain="acme.test") == []

    snapshots = [
        SERPSnapshot(
            query=f"q{i}",
            observed_at=utcnow(),
            provider="test",
            results=[
                SERPResultItem(position=1, url="https://rival.test/a", domain="rival.test"),
                SERPResultItem(position=2, url="https://acme.test/a", domain="acme.test"),
            ],
        )
        for i in range(3)
    ]
    found = discover_serp_competitors(snapshots, brand_domain="acme.test")
    assert [c.domain for c in found] == ["rival.test"]
    assert found[0].discovered_via == "serp_observation"


def test_keyword_gaps_require_observed_competitor_pages() -> None:
    competitors = {
        "rival.test": CompetitorPages(
            domain="rival.test",
            pages=[_page("https://rival.test/cost", "DNA test cost guide")],
        )
    }
    gaps = keyword_gaps(
        brand_pages={"https://acme.test/a": {"title": "About us", "h1": "About"}},
        competitors=competitors,
        keywords=["dna test cost"],
    )
    assert [g.keyword for g in gaps] == ["dna test cost"]
    assert gaps[0].competitor_domains == ["rival.test"]

    # With no competitor pages observed, no gap is asserted.
    assert keyword_gaps(brand_pages={}, competitors={}, keywords=["dna test cost"]) == []


# --- Content gap decisions --------------------------------------------------
def _cluster(label: str, keywords: list[str]) -> KeywordCluster:
    return KeywordCluster(
        id="c1", label=label, head_keyword=label, keywords=keywords, opportunity_score=60
    )


def test_gap_recommends_update_when_a_weak_page_already_covers_the_topic() -> None:
    weak = PageParser(allowed_domains={"acme.test"}).parse(
        url="https://acme.test/dna-test-cost",
        html=(
            '<html lang="en"><head><title>DNA test cost</title></head>'
            "<body><h1>DNA test cost</h1><p>Short.</p></body></html>"
        ),
        status_code=200,
    )
    gap = analyse_content_gap(
        _cluster("dna test cost", ["dna test cost"]),
        brand_pages={"https://acme.test/dna-test-cost": weak},
        competitors={},
    )
    assert gap.decision is ContentDecision.UPDATE
    assert "already targets this topic" in gap.decision_reason


def test_gap_recommends_do_nothing_when_a_strong_page_already_covers_it() -> None:
    strong = _page("https://acme.test/dna-test-cost", "DNA test cost", words=400, schema=True)
    gap = analyse_content_gap(
        _cluster("dna test cost", ["dna test cost"]),
        brand_pages={"https://acme.test/dna-test-cost": strong},
        competitors={},
    )
    assert gap.decision is ContentDecision.DO_NOTHING


def test_gap_recommends_consolidate_when_pages_compete() -> None:
    a = _page("https://acme.test/dna-cost", "DNA test cost")
    b = _page("https://acme.test/cost-of-dna", "DNA test cost")
    gap = analyse_content_gap(
        _cluster("dna test cost", ["dna test cost"]),
        brand_pages={"https://acme.test/dna-cost": a, "https://acme.test/cost-of-dna": b},
        competitors={},
    )
    assert gap.decision is ContentDecision.CONSOLIDATE
    assert gap.consolidate_urls


def test_gap_recommends_create_only_with_a_reason() -> None:
    competitors = {
        "rival.test": CompetitorPages(
            domain="rival.test", pages=[_page("https://rival.test/cost", "DNA test cost")]
        )
    }
    gap = analyse_content_gap(
        _cluster("dna test cost", ["dna test cost"]),
        brand_pages={},
        competitors=competitors,
    )
    assert gap.decision is ContentDecision.CREATE
    assert "competitor page" in gap.decision_reason


def test_an_uncovered_topic_with_no_evidence_does_not_justify_a_page() -> None:
    gap = analyse_content_gap(
        _cluster("something nobody searches", ["something nobody searches"]),
        brand_pages={},
        competitors={},
    )
    assert gap.decision is ContentDecision.DO_NOTHING
    assert "keyword alone is not a reason to publish" in gap.decision_reason


def test_gap_confidence_rises_with_the_evidence_available() -> None:
    thin = analyse_content_gap(_cluster("t", ["t"]), brand_pages={}, competitors={})
    rich = analyse_content_gap(
        _cluster("dna test cost", ["dna test cost"]),
        brand_pages={"https://acme.test/a": _page("https://acme.test/a", "DNA test cost")},
        competitors={
            "rival.test": CompetitorPages(
                domain="rival.test", pages=[_page("https://rival.test/c", "DNA test cost")]
            )
        },
        serp_snapshot=SERPSnapshot(
            query="dna test cost",
            observed_at=utcnow(),
            provider="test",
            results=[SERPResultItem(position=1, url="https://rival.test/c", domain="rival.test")],
        ),
        demand_signal=1200,
        demand_provenance=DataProvenance.OBSERVED,
    )
    assert rich.confidence > thin.confidence
