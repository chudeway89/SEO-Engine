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

    if stage == "brand_understanding":
        return base

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
        row.get("keyword")
        for row in research.get("top_keywords", [])
        if isinstance(row, dict) and row.get("keyword")
    ]
    return keywords[:COMPETITOR_KEYWORD_LIMIT]


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


__all__ = ["COMPETITOR_KEYWORD_LIMIT", "measured_baseline", "stage_inputs"]
