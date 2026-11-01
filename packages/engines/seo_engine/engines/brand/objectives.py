"""Business objectives → measurable search metrics.

A goal the platform cannot measure is a goal it cannot report progress on, and
reporting progress anyway would mean inventing a figure. This engine maps each
stated goal to the metric that would measure it, names the data source that
metric needs, and says plainly when that source is missing — so a mission is
never started against a target nobody can observe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from seo_engine.schemas.enums import IntegrationProvider


@dataclass(frozen=True, slots=True)
class MetricSpec:
    metric: str
    description: str
    requires: str | None  # integration provider value, or None when the crawl suffices
    needs_lead_events: bool = False


METRICS: dict[str, MetricSpec] = {
    "qualified_organic_leads": MetricSpec(
        "qualified_organic_leads",
        "Organic sessions that complete a confirmed lead event",
        IntegrationProvider.GOOGLE_ANALYTICS_4.value,
        needs_lead_events=True,
    ),
    "organic_revenue": MetricSpec(
        "organic_revenue",
        "Revenue attributed to organic sessions",
        IntegrationProvider.GOOGLE_ANALYTICS_4.value,
    ),
    "organic_clicks": MetricSpec(
        "organic_clicks",
        "Clicks from organic search results",
        IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value,
    ),
    "organic_impressions": MetricSpec(
        "organic_impressions",
        "Impressions in organic search results",
        IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value,
    ),
    "branded_search_impressions": MetricSpec(
        "branded_search_impressions",
        "Impressions for queries containing the brand name",
        IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value,
    ),
    "indexable_pages": MetricSpec(
        "indexable_pages",
        "Pages the crawl observes as indexable",
        None,
    ),
}

#: Goal text or goal type → metric. Checked in order; the first match wins.
GOAL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(leads?|enquir\w*|inquir\w*|bookings?|sign[- ]?ups?|acquisition)\b", re.I),
        "qualified_organic_leads",
    ),
    (re.compile(r"\b(revenue|sales|orders|ecommerce|purchases?)\b", re.I), "organic_revenue"),
    (re.compile(r"\b(traffic|visits?|sessions?|clicks?)\b", re.I), "organic_clicks"),
    (
        re.compile(r"\b(brand(ed)? (awareness|search)|awareness)\b", re.I),
        "branded_search_impressions",
    ),
    (
        re.compile(r"\b(visib\w*|found|rank\w*|impressions?|presence)\b", re.I),
        "organic_impressions",
    ),
    (re.compile(r"\b(technical|index\w*|crawl\w*|site health)\b", re.I), "indexable_pages"),
)


@dataclass(slots=True)
class GoalAssessment:
    goal: str
    goal_type: str
    stated_metric: str | None
    metric: str | None
    measurable: bool
    blockers: list[str] = field(default_factory=list)
    specificity_gaps: list[str] = field(default_factory=list)
    data_source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "goal_type": self.goal_type,
            "stated_metric": self.stated_metric,
            "metric": self.metric,
            "measurable": self.measurable,
            "blockers": self.blockers,
            "specificity_gaps": self.specificity_gaps,
            "data_source": self.data_source,
        }


#: A declared goal type is the customer's own classification and outranks any
#: word that happens to appear in the description.
GOAL_TYPE_METRICS: dict[str, str] = {
    "acquisition": "qualified_organic_leads",
    "leads": "qualified_organic_leads",
    "conversion": "qualified_organic_leads",
    "revenue": "organic_revenue",
    "sales": "organic_revenue",
    "traffic": "organic_clicks",
    "visibility": "organic_impressions",
    "awareness": "branded_search_impressions",
    "brand": "branded_search_impressions",
    "technical": "indexable_pages",
}


def metric_for_goal(description: str, goal_type: str, stated_metric: str | None) -> str | None:
    """The metric that measures a goal: stated metric, then goal type, then wording."""
    if stated_metric and stated_metric in METRICS:
        return stated_metric
    by_type = GOAL_TYPE_METRICS.get((goal_type or "").strip().lower())
    if by_type:
        return by_type
    for pattern, metric in GOAL_RULES:
        if pattern.search(description or ""):
            return metric
    return None


def assess_goal(
    *,
    description: str,
    goal_type: str,
    stated_metric: str | None,
    target_value: float | None,
    timeframe: str | None,
    connected: set[str],
    lead_events_confirmed: bool,
    has_website: bool,
) -> GoalAssessment:
    metric = metric_for_goal(description, goal_type, stated_metric)
    assessment = GoalAssessment(
        goal=description,
        goal_type=goal_type,
        stated_metric=stated_metric,
        metric=metric,
        measurable=False,
    )
    if stated_metric and stated_metric not in METRICS:
        assessment.specificity_gaps.append(
            f"The stated metric '{stated_metric}' is not one the platform can measure; "
            + (f"'{metric}' is the closest measurable metric." if metric else "")
        )
    if metric is None:
        assessment.blockers.append(
            "The goal does not name an outcome search data can measure (leads, revenue, "
            "traffic, visibility or index coverage)."
        )
        return assessment

    spec = METRICS[metric]
    assessment.data_source = spec.requires or "website crawl"
    if spec.requires and spec.requires not in connected:
        assessment.blockers.append(
            f"Measuring {metric} needs {spec.requires}, which is not connected. Until it "
            "is, no progress figure can be reported and none will be estimated."
        )
    if spec.requires is None and not has_website:
        assessment.blockers.append("Measuring index coverage needs a website to crawl.")
    if spec.needs_lead_events and spec.requires in connected and not lead_events_confirmed:
        assessment.blockers.append(
            "No conversion event is confirmed as a lead, so organic sessions cannot yet "
            "be counted as qualified leads. Confirm which events are leads."
        )
    if target_value is None:
        assessment.specificity_gaps.append("No target value is set.")
    if not timeframe:
        assessment.specificity_gaps.append("No timeframe is set.")

    assessment.measurable = not assessment.blockers
    return assessment


__all__ = [
    "GOAL_RULES",
    "METRICS",
    "GoalAssessment",
    "MetricSpec",
    "assess_goal",
    "metric_for_goal",
]
