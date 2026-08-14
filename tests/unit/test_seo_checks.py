"""Deterministic SEO check and scoring tests.

The checks run against a real crawl of the in-process test site, which is
deliberately built with one instance of each defect. A check that fires on a
clean site, or fails to fire on a broken one, is a bug — so each test names the
specific defect it expects.
"""

from __future__ import annotations

import pytest
from seo_engine.engines.crawler.crawler import WebsiteCrawler
from seo_engine.engines.crawler.parser import PageParser
from seo_engine.engines.seo.checks import (
    CheckContext,
    registered_checks,
    run_all_checks,
)
from seo_engine.engines.seo.readiness import (
    assess_agentic_web_readiness,
    assess_ai_search_readiness,
)
from seo_engine.engines.seo.scoring import DIMENSION_WEIGHTS, score_dimensions
from seo_engine.schemas.crawl import CrawlConfig, CrawlResult
from seo_engine.schemas.enums import IssueSeverity, ObservationConfidenceClass, SEODimension
from seo_engine.shared.ids import utcnow

from tests.fixtures.fake_site import BASE, build_client

CONFIG = CrawlConfig(
    max_pages=50,
    max_depth=3,
    concurrency=2,
    requests_per_second=50.0,
    request_timeout_seconds=5.0,
    user_agent="SEOEngineBot/0.1",
)


@pytest.fixture(scope="module")
async def crawl() -> CrawlResult:
    async with build_client() as client:
        return await WebsiteCrawler(CONFIG, client=client).crawl(f"{BASE}/", website_id="w1")


@pytest.fixture(scope="module")
def issues(crawl: CrawlResult):
    return run_all_checks(crawl)


def _by_check(issues, check_id: str):
    return [i for i in issues if i.check_id == check_id]


def _urls(issues, check_id: str) -> set[str]:
    return {i.url for i in _by_check(issues, check_id)}


# --- Registry ---------------------------------------------------------------
def test_every_specified_check_is_registered() -> None:
    """The Build Specification section 13 list, plus the additions we declared."""
    required = {
        "missing_title",
        "duplicate_title",
        "title_length",
        "missing_meta_description",
        "duplicate_meta_description",
        "missing_h1",
        "multiple_h1",
        "missing_canonical",
        "canonical_mismatch",
        "noindex",
        "broken_internal_link",
        "redirect_chain",
        "http_4xx",
        "http_5xx",
        "orphan_page",
        "thin_content",
        "missing_image_alt",
        "invalid_structured_data",
        "hreflang_no_return_tag",
        "robots_txt_missing",
        "sitemap_missing",
        "mixed_protocol",
    }
    assert required <= set(registered_checks())


def test_check_ids_are_unique() -> None:
    ids = registered_checks()
    assert len(ids) == len(set(ids))


# --- Individual checks ------------------------------------------------------
def test_duplicate_titles_are_detected_and_list_every_affected_url(issues) -> None:
    found = _by_check(issues, "duplicate_title")
    assert found, "the two 'Our locations' pages should collide"
    assert len(found[0].affected_urls) == 2


def test_missing_h1_is_detected_on_the_page_that_lacks_one(issues) -> None:
    assert f"{BASE}/no-h1-page" in _urls(issues, "missing_h1")


def test_thin_content_is_detected(issues) -> None:
    assert f"{BASE}/thin-page" in _urls(issues, "thin_content")


def test_missing_meta_description_is_detected(issues) -> None:
    assert f"{BASE}/thin-page" in _urls(issues, "missing_meta_description")


def test_noindex_pages_are_reported_with_their_source(issues) -> None:
    found = _by_check(issues, "noindex")
    assert f"{BASE}/noindex-page" in {i.url for i in found}
    assert "meta robots tag" in found[0].detail


def test_4xx_responses_are_reported(issues) -> None:
    assert f"{BASE}/broken-link-target" in _urls(issues, "http_4xx")


def test_broken_internal_links_name_the_pages_that_link_to_them(issues) -> None:
    found = _by_check(issues, "broken_internal_link")
    assert found
    assert f"{BASE}/" in found[0].affected_urls


def test_redirect_chains_beyond_the_threshold_are_reported(issues) -> None:
    found = _by_check(issues, "redirect_chain")
    assert found
    assert found[0].evidence_data["hops"] >= 3


def test_orphan_pages_are_detected_and_sitemap_presence_lowers_severity(issues) -> None:
    found = _by_check(issues, "orphan_page")
    orphan = next(i for i in found if i.url == f"{BASE}/orphan-page")
    assert orphan.evidence_data["in_sitemap"] is True
    assert orphan.severity is IssueSeverity.MEDIUM


def test_the_start_url_is_never_reported_as_an_orphan(issues) -> None:
    assert f"{BASE}/" not in _urls(issues, "orphan_page")


def test_duplicate_content_is_detected_by_body_hash(issues) -> None:
    found = _by_check(issues, "duplicate_content")
    assert found
    assert set(found[0].affected_urls) == {f"{BASE}/duplicate-a", f"{BASE}/duplicate-b"}


def test_canonical_mismatch_is_detected(issues) -> None:
    assert f"{BASE}/duplicate-b" in _urls(issues, "canonical_mismatch")


def test_invalid_structured_data_is_reported(issues) -> None:
    # /private/public-note carries a broken JSON-LD block and is robots-allowed.
    found = _by_check(issues, "invalid_structured_data")
    assert found
    assert "invalid JSON" in found[0].detail


def test_javascript_dependent_content_is_reported(issues) -> None:
    assert f"{BASE}/app" in _urls(issues, "javascript_dependent_content")


def test_unlabelled_form_controls_are_reported(issues) -> None:
    found = _by_check(issues, "unlabelled_form_controls")
    assert f"{BASE}/contact" in {i.url for i in found}


def test_unnamed_buttons_are_reported(issues) -> None:
    assert f"{BASE}/contact" in _urls(issues, "unnamed_interactive_elements")


def test_a_conversion_path_is_expected_on_substantive_pages(issues) -> None:
    found = _urls(issues, "no_conversion_path")
    # The guide has substance and links onward, so it should not be flagged.
    assert f"{BASE}/services/dna-testing" not in found


def test_noindex_pages_are_not_penalised_for_on_page_issues(issues) -> None:
    """A page excluded from the index does not need a meta description."""
    assert f"{BASE}/noindex-page" not in _urls(issues, "missing_meta_description")
    assert f"{BASE}/noindex-page" not in _urls(issues, "missing_canonical")


def test_a_clean_site_produces_no_issues() -> None:
    """Guard against checks that fire on healthy pages."""
    html = (
        '<!doctype html><html lang="en"><head>'
        "<title>A perfectly reasonable page title here</title>"
        '<meta name="description" content="'
        + "A description of the page that is comfortably long enough to be useful "
        "to a reader scanning the results page." + '">'
        '<link rel="canonical" href="https://acme.test/good">'
        '<script type="application/ld+json">{"@type":"Article"}</script>'
        "</head><body><main><h1>A clear heading</h1><p>"
        + ("Substantive and genuinely useful body copy. " * 60)
        + '</p><a href="/contact">Contact us</a></main></body></html>'
    )
    page = PageParser(allowed_domains={"acme.test"}).parse(
        url="https://acme.test/good", html=html, status_code=200, content_type="text/html"
    )
    result = CrawlResult(
        website_id="w",
        start_url="https://acme.test/good",
        config=CONFIG,
        pages=[page],
        started_at=utcnow(),
    )
    result.robots.fetched = True
    result.sitemap.discovered = ["https://acme.test/sitemap.xml"]
    from seo_engine.schemas.crawl import SitemapEntry

    result.sitemap.entries = [SitemapEntry(loc="https://acme.test/good")]

    found = run_all_checks(result)
    unexpected = [
        i.check_id
        for i in found
        if i.check_id not in {"missing_image_alt", "no_semantic_landmarks", "page_not_in_sitemap"}
    ]
    assert unexpected == [], f"clean page triggered: {unexpected}"


# --- Scoring ----------------------------------------------------------------
def test_scorecard_reports_every_dimension(crawl: CrawlResult, issues) -> None:
    scorecard = score_dimensions(crawl, issues)
    assert {d.dimension for d in scorecard.dimensions} == set(SEODimension)


def test_dimension_weights_sum_to_one() -> None:
    assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


def test_the_overall_score_never_replaces_the_dimensions(crawl: CrawlResult, issues) -> None:
    scorecard = score_dimensions(crawl, issues)
    assert 0 <= scorecard.overall <= 100
    assert len(scorecard.dimensions) == 9
    assert "not a Google ranking score" in scorecard.method


def test_a_dimension_without_data_is_reported_as_not_evaluated(crawl: CrawlResult, issues) -> None:
    """An unassessed dimension must not be scored 100."""
    scorecard = score_dimensions(crawl, issues, has_local_data=False)
    local = scorecard.dimension(SEODimension.LOCAL_READINESS)
    assert local is not None
    assert local.evaluated is False
    assert local.not_evaluated_reason


def test_a_broken_site_scores_below_a_clean_one(crawl: CrawlResult, issues) -> None:
    broken = score_dimensions(crawl, issues)
    clean = score_dimensions(crawl, [])
    assert broken.overall < clean.overall
    assert broken.dimension(SEODimension.TECHNICAL_HEALTH).score < 100


def test_a_widespread_issue_costs_more_than_an_isolated_one(crawl: CrawlResult) -> None:
    from seo_engine.schemas.seo import SEOIssue

    def issue(affected: list[str]) -> SEOIssue:
        return SEOIssue(
            check_id="x",
            title="t",
            severity=IssueSeverity.HIGH,
            dimension=SEODimension.TECHNICAL_HEALTH,
            affected_urls=affected,
        )

    isolated = score_dimensions(crawl, [issue(["u1"])])
    widespread = score_dimensions(crawl, [issue([f"u{i}" for i in range(50)])])
    assert (
        widespread.dimension(SEODimension.TECHNICAL_HEALTH).score
        < isolated.dimension(SEODimension.TECHNICAL_HEALTH).score
    )


# --- Readiness --------------------------------------------------------------
def test_ai_search_readiness_separates_observed_inferred_and_unknown(
    crawl: CrawlResult,
) -> None:
    report = assess_ai_search_readiness(crawl, website_id="w1")
    classes = {s.classification for s in report.signals}
    assert ObservationConfidenceClass.OBSERVED in classes
    assert ObservationConfidenceClass.INFERRED in classes
    assert ObservationConfidenceClass.UNKNOWN in classes


def test_unknown_signals_carry_no_value_and_are_listed_explicitly(
    crawl: CrawlResult,
) -> None:
    """Rule 14: never present a proprietary unknown as a measurement."""
    report = assess_ai_search_readiness(crawl, website_id="w1")
    unknowns = [s for s in report.signals if s.classification is ObservationConfidenceClass.UNKNOWN]
    assert unknowns
    assert all(s.value is None for s in unknowns)
    assert report.unknowns


def test_readiness_score_excludes_unknown_signals(crawl: CrawlResult) -> None:
    report = assess_ai_search_readiness(crawl, website_id="w1")
    assert report.readiness_score is not None
    assert 0 <= report.readiness_score <= 100


def test_absent_citations_are_reported_as_unmeasured_not_as_zero_visibility(
    crawl: CrawlResult,
) -> None:
    report = assess_ai_search_readiness(crawl, website_id="w1")
    citations = next(s for s in report.signals if s.key == "observed_citations")
    assert citations.value == 0
    assert "not evidence that none exist" in citations.detail


def test_gsc_absence_is_stated_as_a_note(crawl: CrawlResult) -> None:
    report = assess_ai_search_readiness(crawl, website_id="w1", gsc_connected=False)
    assert any("Search Console is not connected" in note for note in report.notes)


def test_agentic_web_readiness_scores_the_documented_signals(crawl: CrawlResult) -> None:
    report = assess_agentic_web_readiness(crawl, website_id="w1")
    assert 0 <= report.score <= 100
    assert {
        "buttons_with_accessible_names",
        "form_controls_labelled",
        "main_landmark_present",
        "content_without_javascript",
        "natural_keyboard_order",
    } <= set(report.signals)


def test_check_context_counts_inbound_links(crawl: CrawlResult) -> None:
    ctx = CheckContext.build(crawl)
    assert ctx.inbound_links.get(f"{BASE}/services/dna-testing", 0) >= 1
