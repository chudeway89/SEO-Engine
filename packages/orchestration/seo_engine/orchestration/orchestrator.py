"""The orchestrator.

Given a business objective it builds a task graph: which agents run, in what
order, and why each was chosen. It delegates — it never executes tools itself
(Build Specification §29).

The important behaviour is **selection**. The orchestrator does not run every
agent every time. A mission whose objective is about competitors does not need
the GA4 stage; a brand with no connected analytics does not get analytics tasks
at all, and the omission is recorded as the stage's reason rather than silently
skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from seo_engine.schemas.enums import IntegrationProvider, TaskPriority

# ---------------------------------------------------------------------------
# Mission classification
# ---------------------------------------------------------------------------
MISSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "qualified_leads",
        re.compile(r"\b(qualified\s+)?(organic\s+)?(leads?|enquir|inquir|conversions?)\b", re.I),
    ),
    (
        "organic_traffic",
        re.compile(r"\b(organic\s+)?(traffic|visits?|sessions?|visibility)\b", re.I),
    ),
    (
        "content_strategy",
        re.compile(r"\b(content\s+(strategy|plan|calendar)|six[- ]month)\b", re.I),
    ),
    (
        "content_refresh",
        re.compile(r"\b(update|refresh|improve)\b.{0,30}\b(content|pages?)\b", re.I),
    ),
    ("competitor", re.compile(r"\b(competitor|competitive|against\s+my|rival)\b", re.I)),
    ("technical_recovery", re.compile(r"\b(technical|crawl|index|recover(y|ing)?|drop)\b", re.I)),
    ("local", re.compile(r"\b(local|near me|location|branch|store)\b", re.I)),
)

#: What each mission type actually needs.  Absent from a list means the stage is
#: not run for that mission — that is the selection the specification asks for.
MISSION_STAGES: dict[str, list[str]] = {
    "qualified_leads": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "ga4_analysis",
        "keyword_research",
        "competitor_analysis",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "execution_plan",
    ],
    "organic_traffic": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "keyword_research",
        "competitor_analysis",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "content_strategy": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "competitor_analysis",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "content_refresh": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "competitor": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "competitor_analysis",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "technical_recovery": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "local": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "competitor_analysis",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "generic": [
        "brand_understanding",
        "website_audit",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
}

#: Target metric per mission type.  ``None`` means the mission has no single
#: measurable target and is reported as such rather than given a made-up one.
MISSION_TARGET_METRIC: dict[str, str | None] = {
    "qualified_leads": "qualified_organic_leads",
    "organic_traffic": "organic_clicks",
    "content_strategy": None,
    "content_refresh": "organic_clicks",
    "competitor": None,
    "technical_recovery": "indexable_pages",
    "local": None,
    "generic": None,
}


@dataclass(slots=True)
class StageSpec:
    """One stage of the plan."""

    stage: str
    agent_id: str
    task_type: str
    objective: str
    depends_on: list[str] = field(default_factory=list)
    required: bool = True
    requires_integration: str | None = None
    requires_website: bool = False
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL


STAGE_SPECS: dict[str, StageSpec] = {
    "brand_understanding": StageSpec(
        stage="brand_understanding",
        agent_id="BRD-001",
        task_type="brand.understand",
        objective="Build the working model of the brand from its supplied profile",
        capabilities=["brand.understand"],
        tools=["memory"],
        priority=TaskPriority.HIGH,
    ),
    "website_audit": StageSpec(
        stage="website_audit",
        agent_id="SEO-001",
        task_type="seo.technical_audit",
        objective="Crawl the website and run the deterministic technical and on-page checks",
        depends_on=["brand_understanding"],
        requires_website=True,
        capabilities=["seo.audit", "website.crawl"],
        tools=["crawler"],
        priority=TaskPriority.HIGH,
    ),
    "gsc_analysis": StageSpec(
        stage="gsc_analysis",
        agent_id="ANA-001",
        task_type="analytics.gsc",
        objective="Analyse Search Console performance for queries with recoverable positions",
        depends_on=["brand_understanding"],
        requires_integration=IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value,
        capabilities=["analytics.gsc.read"],
        tools=["gsc"],
    ),
    "ga4_analysis": StageSpec(
        stage="ga4_analysis",
        agent_id="ANA-002",
        task_type="analytics.ga4",
        objective="Analyse organic traffic and conversions to establish the lead baseline",
        depends_on=["brand_understanding"],
        requires_integration=IntegrationProvider.GOOGLE_ANALYTICS_4.value,
        capabilities=["analytics.ga4.read"],
        tools=["ga4"],
    ),
    "keyword_research": StageSpec(
        stage="keyword_research",
        agent_id="SEO-003",
        task_type="seo.keyword_research",
        objective="Discover, classify, cluster and score search opportunities",
        depends_on=["brand_understanding"],
        capabilities=["seo.keyword.research", "seo.keyword.cluster", "seo.search.intent"],
        tools=["gsc"],
    ),
    "competitor_analysis": StageSpec(
        stage="competitor_analysis",
        agent_id="CMP-002",
        task_type="competitor.analyse",
        objective="Analyse competitor coverage and identify keyword and content gaps",
        depends_on=["brand_understanding", "keyword_research"],
        capabilities=["competitor.analyse"],
        tools=["crawler"],
    ),
    "content_gap": StageSpec(
        stage="content_gap",
        agent_id="SEO-006",
        task_type="seo.content_gap",
        objective="Decide create, update, consolidate, redirect or do nothing for each topic",
        depends_on=["keyword_research", "website_audit"],
        capabilities=["seo.content.gap"],
        tools=[],
    ),
    "opportunity_detection": StageSpec(
        stage="opportunity_detection",
        agent_id="OPP-001",
        task_type="opportunity.detect",
        objective="Turn the observed findings into evidence-backed opportunities",
        depends_on=["website_audit"],
        capabilities=["opportunity.detect"],
        tools=[],
        priority=TaskPriority.HIGH,
    ),
    "prioritisation": StageSpec(
        stage="prioritisation",
        agent_id="PRI-001",
        task_type="opportunity.prioritise",
        objective="Rank the opportunities by the internal prioritisation model",
        depends_on=["opportunity_detection"],
        capabilities=["opportunity.prioritise"],
        tools=[],
    ),
    "recommendation": StageSpec(
        stage="recommendation",
        agent_id="DEC-001",
        task_type="decision.recommend",
        objective="Challenge the opportunities and produce evidence-backed recommendations",
        depends_on=["prioritisation"],
        capabilities=["decision.recommend"],
        tools=[],
        priority=TaskPriority.HIGH,
    ),
    "execution_plan": StageSpec(
        stage="execution_plan",
        agent_id="EXE-001",
        task_type="execution.plan",
        objective="Turn approved recommendations into a concrete, approvable action plan",
        depends_on=["recommendation"],
        capabilities=["execution.plan"],
        tools=["cms"],
    ),
}


@dataclass(slots=True)
class PlannedStage:
    spec: StageSpec
    included: bool
    reason: str


@dataclass(slots=True)
class MissionPlan:
    mission_type: str
    target_metric: str | None
    stages: list[PlannedStage]
    summary: str

    @property
    def included(self) -> list[PlannedStage]:
        return [s for s in self.stages if s.included]

    @property
    def excluded(self) -> list[PlannedStage]:
        return [s for s in self.stages if not s.included]


def classify_objective(objective: str) -> str:
    """Map a plain-language objective to a mission type."""
    for mission_type, pattern in MISSION_PATTERNS:
        if pattern.search(objective):
            return mission_type
    return "generic"


class Orchestrator:
    """Decomposes an objective into a selected, dependency-ordered task graph."""

    def plan(
        self,
        objective: str,
        *,
        has_website: bool,
        connected_integrations: set[str] | None = None,
        has_competitors: bool = True,
    ) -> MissionPlan:
        mission_type = classify_objective(objective)
        wanted = MISSION_STAGES.get(mission_type, MISSION_STAGES["generic"])
        connected = connected_integrations or set()

        planned: list[PlannedStage] = []
        included_names: set[str] = set()

        for name in wanted:
            spec = STAGE_SPECS[name]
            included, reason = self._should_include(
                spec,
                has_website=has_website,
                connected=connected,
                has_competitors=has_competitors,
            )
            if included:
                included_names.add(name)
            planned.append(PlannedStage(spec=spec, included=included, reason=reason))

        # A stage whose prerequisite was dropped cannot run either.
        changed = True
        while changed:
            changed = False
            for stage in planned:
                if not stage.included:
                    continue
                missing = [
                    dep
                    for dep in stage.spec.depends_on
                    if dep in wanted and dep not in included_names
                ]
                if missing:
                    stage.included = False
                    stage.reason = (
                        f"Not run because it depends on {', '.join(missing)}, which was "
                        "not included."
                    )
                    included_names.discard(stage.spec.stage)
                    changed = True

        return MissionPlan(
            mission_type=mission_type,
            target_metric=MISSION_TARGET_METRIC.get(mission_type),
            stages=planned,
            summary=self._summary(objective, mission_type, planned),
        )

    def _should_include(
        self,
        spec: StageSpec,
        *,
        has_website: bool,
        connected: set[str],
        has_competitors: bool,
    ) -> tuple[bool, str]:
        if spec.requires_website and not has_website:
            return False, (
                "Not run because no website is connected to this brand, so there is "
                "nothing to crawl."
            )
        if spec.requires_integration and spec.requires_integration not in connected:
            return False, (
                f"Not run because {spec.requires_integration} is not connected. No data "
                "from it is available, and nothing has been estimated in its place."
            )
        if spec.stage == "competitor_analysis" and not has_competitors:
            return False, (
                "Not run because no competitors are recorded for this brand. Competitor "
                "gaps cannot be asserted without competitors to compare against."
            )
        return True, f"Selected for a {spec.stage.replace('_', ' ')} mission."

    def _summary(self, objective: str, mission_type: str, stages: list[PlannedStage]) -> str:
        included = [s for s in stages if s.included]
        excluded = [s for s in stages if not s.included]
        parts = [
            f"Objective classified as '{mission_type}'.",
            f"{len(included)} stage(s) selected: "
            + ", ".join(s.spec.stage.replace("_", " ") for s in included)
            + ".",
        ]
        if excluded:
            parts.append(
                f"{len(excluded)} stage(s) not run: "
                + "; ".join(f"{s.spec.stage.replace('_', ' ')} ({s.reason})" for s in excluded)
            )
        return " ".join(parts)


async def build_task_graph(
    mission_service: Any,
    mission: Any,
    plan: MissionPlan,
    *,
    inputs: dict[str, Any] | None = None,
) -> list[Any]:
    """Persist the plan as a real task graph with dependency edges."""
    created: dict[str, Any] = {}
    tasks: list[Any] = []

    for index, stage in enumerate(plan.included):
        spec = stage.spec
        upstream = [created[dep] for dep in spec.depends_on if dep in created]
        task = await mission_service.add_task(
            mission,
            agent_id=spec.agent_id,
            task_type=spec.task_type,
            objective=spec.objective,
            stage=spec.stage,
            sequence=index,
            inputs={**(inputs or {}), "stage": spec.stage},
            depends_on=upstream,
            priority=spec.priority,
            required_capabilities=spec.capabilities,
            allowed_tools=spec.tools,
            selection_reason=stage.reason,
        )
        created[spec.stage] = task
        tasks.append(task)
    return tasks


__all__ = [
    "MISSION_STAGES",
    "MISSION_TARGET_METRIC",
    "STAGE_SPECS",
    "MissionPlan",
    "Orchestrator",
    "PlannedStage",
    "StageSpec",
    "build_task_graph",
    "classify_objective",
]
