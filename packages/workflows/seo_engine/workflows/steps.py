"""Stage wiring: what each stage is given, and what it hands downstream.

These are pure functions over the accumulated stage outputs, which is what makes
the mission workflow testable without a database, a crawler or a model. A stage
receives only what an upstream stage actually produced — if the upstream stage
did not run, the key is simply absent, and the receiving agent records the gap
as a limitation instead of assuming a value.
"""

from __future__ import annotations

import uuid
from typing import Any

#: How many upstream keywords are worth handing to competitor analysis. Enough
#: to compare coverage, few enough to keep the competitor crawl shallow.
COMPETITOR_KEYWORD_LIMIT = 25

#: Results pages fetched per mission. Each is a paid API call in production.
SERP_QUERY_LIMIT = 8

#: Stages whose output carries opportunity seeds (kept in step with the
#: orchestrator's SEED_STAGES; duplicated here so this module stays pure).
SEED_STAGES: tuple[str, ...] = (
    "on_page",
    "indexability",
    "search_intent",
    "keyword_architecture",
    "question_research",
    "competitive_gap",
)


def stage_inputs(
    stage: str,
    *,
    brand_id: uuid.UUID,
    mission_id: uuid.UUID,
    website_id: uuid.UUID | None,
    outputs: dict[str, dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the input payload for one stage from what upstream stages produced."""
    options = options or {}
    base: dict[str, Any] = {"brand_id": str(brand_id)}
    if website_id is not None:
        base["website_id"] = str(website_id)

    if stage in {
        "brand_understanding",
        "objective_assessment",
        "brand_profile",
        "indexability",
        "on_page",
        "search_intent",
        "keyword_architecture",
        "question_research",
        "competitor_discovery",
    }:
        return base

    if stage == "search_research":
        return {"brand_id": str(brand_id)}

    if stage == "serp_research":
        return {
            **base,
            "queries": _upstream_keywords(outputs)[
                : options.get("max_serp_queries", SERP_QUERY_LIMIT)
            ],
            "max_queries": options.get("max_serp_queries", SERP_QUERY_LIMIT),
        }

    if stage == "source_research":
        return {**base, "max_fetch": options.get("max_source_fetch", 5)}

    if stage == "competitive_gap":
        analysis = _get(outputs, "competitor_analysis", "competitor_analysis")
        discovery = _get(outputs, "competitor_discovery", "competitor_discovery")
        return {
            **base,
            "keyword_gaps": analysis.get("keyword_gaps") or [],
            # Synthetic SERP domains are never treated as competitors.
            "discovered_competitors": [
                c["domain"]
                for c in discovery.get("candidates") or []
                if isinstance(c, dict) and not c.get("synthetic")
            ],
        }

    if stage == "content_strategy":
        return {
            "brand_id": str(brand_id),
            "content_gaps": outputs.get("content_gap", {}).get("content_gaps") or [],
            "months": options.get("roadmap_months", 6),
            "capacity_per_month": options.get("roadmap_capacity", 4),
        }

    if stage == "content_research":
        roadmap = outputs.get("content_strategy", {}).get("content_roadmap") or []
        return {**base, "topics": roadmap, "max_topics": options.get("max_content_topics", 3)}

    if stage == "content_brief":
        packs = _get(outputs, "content_research", "content_research").get("packs") or []
        return {**base, "research": packs, "max_briefs": options.get("max_content_topics", 3)}

    if stage == "content_draft":
        briefs = _get(outputs, "content_brief", "content_briefs").get("briefs") or []
        return {
            **base,
            "brief_ids": [
                b["brief_id"] for b in briefs if isinstance(b, dict) and b.get("brief_id")
            ],
        }

    if stage in {
        "content_evaluation",
        "content_optimisation",
        "content_quality_gate",
        "content_repurposing",
        "policy_review",
        "publishing",
    }:
        inputs: dict[str, Any] = {**base, "asset_ids": _mission_assets(outputs)}
        if stage in {"policy_review", "publishing"}:
            inputs["mission_id"] = str(mission_id)
            inputs.pop("website_id", None)
        if stage == "content_repurposing" and options.get("repurpose_platforms"):
            inputs["platforms"] = options["repurpose_platforms"]
        return inputs

    if stage == "content_update":
        return {
            **base,
            "content_gaps": outputs.get("content_gap", {}).get("content_gaps") or [],
        }

    if stage == "quality_review":
        return {"brand_id": str(brand_id), "mission_id": str(mission_id)}

    if stage == "website_audit":
        return {
            **base,
            "max_pages": options.get("max_pages"),
            "max_depth": options.get("max_depth"),
        }

    if stage == "gsc_analysis":
        return {**base, "days": options.get("days", 28)}

    if stage == "ga4_analysis":
        return {"brand_id": str(brand_id), "days": options.get("days", 28)}

    if stage == "keyword_research":
        return {**base, "max_keywords": options.get("max_keywords", 300)}

    if stage == "competitor_analysis":
        return {
            **base,
            "keywords": _upstream_keywords(outputs),
            "max_competitors": options.get("max_competitors", 5),
        }

    if stage == "content_gap":
        gap_inputs = {**base, "max_clusters": options.get("max_clusters", 25)}
        competitor_pages = _get(outputs, "competitor_analysis", "competitor_analysis").get(
            "competitor_pages"
        )
        if competitor_pages:
            gap_inputs["competitor_pages"] = competitor_pages
        return gap_inputs

    if stage == "opportunity_detection":
        upstream: dict[str, Any] = {}
        gaps = outputs.get("content_gap", {}).get("content_gaps")
        if gaps:
            upstream["content_gaps"] = gaps
        queries = outputs.get("gsc_analysis", {}).get("observed_queries")
        if queries:
            upstream["observed_queries"] = queries
        seeds = [
            item
            for name in SEED_STAGES
            for item in outputs.get(name, {}).get("opportunity_seeds") or []
            if isinstance(item, dict)
        ]
        if seeds:
            upstream["opportunity_seeds"] = seeds
        return {**base, "mission_id": str(mission_id), "upstream": upstream}

    if stage == "prioritisation":
        return {
            "brand_id": str(brand_id),
            "mission_id": str(mission_id),
            "limit": options.get("prioritise_limit", 50),
        }

    if stage == "recommendation":
        return {
            "brand_id": str(brand_id),
            "mission_id": str(mission_id),
            "max_recommendations": options.get("max_recommendations", 10),
        }

    if stage == "execution_plan":
        return {
            "brand_id": str(brand_id),
            "mission_id": str(mission_id),
            "execute_approved": bool(options.get("execute_approved", True)),
        }

    return base


def _upstream_keywords(outputs: dict[str, dict[str, Any]]) -> list[str]:
    research = outputs.get("keyword_research", {}).get("keyword_research", {})
    keywords = [
        str(row["keyword"])
        for row in research.get("top_keywords", [])
        if isinstance(row, dict) and row.get("keyword")
    ]
    return keywords[:COMPETITOR_KEYWORD_LIMIT]


def _mission_assets(outputs: dict[str, dict[str, Any]]) -> list[str]:
    """Content assets this mission's writer produced, if it ran."""
    drafts = _get(outputs, "content_draft", "content_writer").get("drafts") or []
    return [d["asset_id"] for d in drafts if isinstance(d, dict) and d.get("asset_id")]


def _get(outputs: dict[str, dict[str, Any]], stage: str, key: str) -> dict[str, Any]:
    value = outputs.get(stage, {}).get(key)
    return value if isinstance(value, dict) else {}


def measured_baseline(outputs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The mission baseline, but only when a provider actually measured it.

    Returns ``None`` when no analytics stage ran or the provider returned
    nothing. The mission then carries no baseline at all, which is honest;
    inventing one would make every later progress figure meaningless.
    """
    analytics = _get(outputs, "ga4_analysis", "analytics")
    if analytics.get("organic_lead_baseline") is not None:
        return {
            "metric": "qualified_organic_leads",
            "value": float(analytics["organic_lead_baseline"]),
            "provenance": analytics.get("baseline_provenance", "unknown"),
            "source": analytics.get("baseline_source") or "google_analytics_4",
        }

    console = _get(outputs, "gsc_analysis", "search_console")
    if console.get("total_clicks") is not None:
        return {
            "metric": "organic_clicks",
            "value": float(console["total_clicks"]),
            "provenance": console.get("provenance", "observed"),
            "source": "google_search_console",
        }
    return None


__all__ = [
    "COMPETITOR_KEYWORD_LIMIT",
    "SEED_STAGES",
    "SERP_QUERY_LIMIT",
    "measured_baseline",
    "stage_inputs",
]
