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
        # Checked first and deliberately narrow: an explicit request to produce
        # content, not any objective that mentions content.
        "content_production",
        re.compile(
            r"\b(write|draft|produce|create|publish)\b.{0,40}"
            r"\b(content|articles?|posts?|blogs?|guides?|copy)\b",
            re.I,
        ),
    ),
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
        re.compile(r"\b(content\s+(strategy|plan|calendar|roadmap)|six[- ]month)\b", re.I),
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
#: Order matters: it is the order stages are created in, and every stage appears
#: after everything it depends on.
MISSION_STAGES: dict[str, list[str]] = {
    "qualified_leads": [
        "brand_understanding",
        "website_audit",
        "brand_profile",
        "gsc_analysis",
        "ga4_analysis",
        "objective_assessment",
        "search_research",
        "indexability",
        "keyword_research",
        "serp_research",
        "on_page",
        "search_intent",
        "keyword_architecture",
        "question_research",
        "competitor_discovery",
        "competitor_analysis",
        "competitive_gap",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
        "policy_review",
        "execution_plan",
    ],
    "organic_traffic": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "search_research",
        "indexability",
        "keyword_research",
        "serp_research",
        "on_page",
        "search_intent",
        "keyword_architecture",
        "competitor_analysis",
        "competitive_gap",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
    ],
    "content_strategy": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "serp_research",
        "question_research",
        "source_research",
        "competitor_analysis",
        "content_gap",
        "content_strategy",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
    ],
    "content_production": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "serp_research",
        "question_research",
        "source_research",
        "content_gap",
        "content_strategy",
        "content_research",
        "content_brief",
        "content_draft",
        "content_evaluation",
        "content_optimisation",
        "content_quality_gate",
        "policy_review",
        "content_repurposing",
        "publishing",
    ],
    "content_refresh": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "keyword_research",
        "content_gap",
        "content_update",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
    ],
    "competitor": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "serp_research",
        "competitor_discovery",
        "competitor_analysis",
        "competitive_gap",
        "content_gap",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
    ],
    "technical_recovery": [
        "brand_understanding",
        "website_audit",
        "gsc_analysis",
        "indexability",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
        "quality_review",
    ],
    "local": [
        "brand_understanding",
        "website_audit",
        "keyword_research",
        "serp_research",
        "competitor_discovery",
        "competitor_analysis",
        "opportunity_detection",
        "prioritisation",
        "recommendation",
    ],
    "generic": [
        "brand_understanding",
        "website_audit",
        "indexability",
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
    "content_production": None,
    "content_refresh": "organic_clicks",
    "competitor": None,
    "technical_recovery": "indexable_pages",
    "local": None,
    "generic": None,
}


@dataclass(slots=True)
class StageSpec:
    """One stage of the plan.

    ``depends_on`` are hard prerequisites: if one is not run, neither is this
    stage. ``after`` only orders: the stage runs after them when they are in the
    plan and simply proceeds without their output when they are not (it then
    reports the missing input as a limitation).
    """

    stage: str
    agent_id: str
    task_type: str
    objective: str
    depends_on: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    required: bool = True
    requires_integration: str | None = None
    requires_website: bool = False
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.NORMAL


#: Stages whose output carries opportunity seeds for opportunity detection.
SEED_STAGES: tuple[str, ...] = (
    "on_page",
    "indexability",
    "search_intent",
    "keyword_architecture",
    "question_research",
    "competitive_gap",
)

GSC = IntegrationProvider.GOOGLE_SEARCH_CONSOLE.value
SERP = IntegrationProvider.SERP_API.value


def _stage(stage: str, agent_id: str, task_type: str, objective: str, **kwargs: Any) -> StageSpec:
    kwargs.setdefault("capabilities", [task_type])
    return StageSpec(
        stage=stage, agent_id=agent_id, task_type=task_type, objective=objective, **kwargs
    )


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
    "objective_assessment": _stage(
        "objective_assessment",
        "BRD-003",
        "brand.objectives.assess",
        "Map each business goal to a measurable metric and its data source",
        depends_on=["brand_understanding"],
        # After the analytics sync, so lead events it identified are visible.
        after=["ga4_analysis", "gsc_analysis"],
        tools=["memory"],
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
    "brand_profile": _stage(
        "brand_profile",
        "BRD-002",
        "brand.profile.review",
        "Compare the brand profile with what the crawled website says",
        depends_on=["website_audit"],
        requires_website=True,
        tools=["memory"],
    ),
    "indexability": _stage(
        "indexability",
        "SEO-012",
        "seo.audit.indexability",
        "Reconcile sitemap, crawl and business priorities for index coverage",
        depends_on=["website_audit"],
        after=["gsc_analysis"],
        requires_website=True,
        tools=["gsc"],
    ),
    "gsc_analysis": StageSpec(
        stage="gsc_analysis",
        agent_id="ANA-001",
        task_type="analytics.gsc",
        objective="Analyse Search Console performance for queries with recoverable positions",
        depends_on=["brand_understanding"],
        requires_integration=GSC,
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
    "search_research": _stage(
        "search_research",
        "RES-001",
        "research.search.demand",
        "Describe the measured search demand landscape",
        depends_on=["gsc_analysis"],
        requires_integration=GSC,
        tools=["gsc"],
    ),
    "keyword_research": StageSpec(
        stage="keyword_research",
        agent_id="SEO-003",
        task_type="seo.keyword_research",
        objective="Discover, classify, cluster and score search opportunities",
        depends_on=["brand_understanding"],
        after=["website_audit", "gsc_analysis"],
        capabilities=["seo.keyword.research", "seo.keyword.cluster", "seo.search.intent"],
        tools=["gsc"],
    ),
    "serp_research": _stage(
        "serp_research",
        "RES-002",
        "seo.serp.research",
        "Observe the results pages for the priority queries",
        depends_on=["keyword_research"],
        requires_integration=SERP,
        tools=["serp"],
    ),
    "on_page": _stage(
        "on_page",
        "SEO-002",
        "seo.audit.onpage",
        "Check each page signals the keyword mapped to it",
        depends_on=["website_audit", "keyword_research"],
        requires_website=True,
        tools=["memory"],
    ),
    "search_intent": _stage(
        "search_intent",
        "SEO-004",
        "seo.search.intent",
        "Compare query intent with the type of page that answers it",
        depends_on=["website_audit", "keyword_research"],
        after=["serp_research"],
        requires_website=True,
        tools=["serp"],
    ),
    "keyword_architecture": _stage(
        "keyword_architecture",
        "SEO-005",
        "seo.keyword.architecture",
        "Find cannibalisation and broken hub-and-spoke linking",
        depends_on=["website_audit", "keyword_research"],
        requires_website=True,
        tools=["memory"],
    ),
    "question_research": _stage(
        "question_research",
        "RES-005",
        "research.questions",
        "Gather audience questions and map them to answering pages",
        depends_on=["keyword_research"],
        after=["website_audit", "serp_research", "gsc_analysis"],
        tools=["gsc"],
    ),
    "source_research": _stage(
        "source_research",
        "RES-006",
        "research.sources",
        "Register, tier and verify the sources content may cite",
        depends_on=["brand_understanding"],
        after=["website_audit"],
        capabilities=["research.sources", "website.crawl"],
        tools=["crawler"],
    ),
    "competitor_discovery": _stage(
        "competitor_discovery",
        "CMP-001",
        "competitor.discover",
        "Identify the domains that compete in the observed results",
        depends_on=["serp_research"],
        tools=["serp"],
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
    "competitive_gap": _stage(
        "competitive_gap",
        "CMP-003",
        "competitor.gap",
        "Join competitor coverage with search visibility into scored gaps",
        depends_on=["competitor_analysis"],
        after=["serp_research", "competitor_discovery"],
        tools=["memory"],
    ),
    "content_gap": StageSpec(
        stage="content_gap",
        agent_id="SEO-006",
        task_type="seo.content_gap",
        objective="Decide create, update, consolidate, redirect or do nothing for each topic",
        depends_on=["keyword_research", "website_audit"],
        after=["competitor_analysis"],
        capabilities=["seo.content.gap"],
        tools=[],
    ),
    "content_strategy": _stage(
        "content_strategy",
        "CNT-001",
        "content.strategy.plan",
        "Sequence the content decisions into a capacity-bounded roadmap",
        depends_on=["content_gap"],
        tools=["memory"],
    ),
    "content_research": _stage(
        "content_research",
        "CNT-002",
        "content.research",
        "Assemble a research pack for each scheduled topic",
        depends_on=["content_strategy"],
        after=["question_research", "source_research", "serp_research"],
        tools=["memory"],
    ),
    "content_brief": _stage(
        "content_brief",
        "CNT-003",
        "content.write.brief",
        "Write the definitive brief for each researched topic",
        depends_on=["content_research"],
        tools=["memory"],
    ),
    "content_draft": _stage(
        "content_draft",
        "CNT-004",
        "content.write.draft",
        "Produce the first internal draft of each briefed piece",
        depends_on=["content_brief"],
        tools=["llm", "memory"],
    ),
    "content_evaluation": _stage(
        "content_evaluation",
        "CNT-007",
        "content.evaluate",
        "Score each draft against its brief",
        depends_on=["content_draft"],
        tools=["memory"],
    ),
    "content_optimisation": _stage(
        "content_optimisation",
        "CNT-005",
        "content.edit.optimise",
        "Turn weak evaluation criteria into specific edits",
        depends_on=["content_evaluation"],
        tools=["memory"],
    ),
    "content_quality_gate": _stage(
        "content_quality_gate",
        "CNT-009",
        "content.evaluate.gate",
        "Decide whether each draft may go to a human approver",
        depends_on=["content_evaluation"],
        after=["content_optimisation"],
        tools=["memory"],
    ),
    "content_update": _stage(
        "content_update",
        "CNT-006",
        "content.edit.update",
        "Plan updates to existing pages the gap stage marked for update",
        depends_on=["content_gap"],
        requires_website=True,
        tools=["memory"],
    ),
    "content_repurposing": _stage(
        "content_repurposing",
        "CNT-008",
        "content.write.repurpose",
        "Derive platform assets from reviewed canonical content",
        depends_on=["content_quality_gate"],
        after=["policy_review"],
        tools=["memory"],
    ),
    "opportunity_detection": StageSpec(
        stage="opportunity_detection",
        agent_id="OPP-001",
        task_type="opportunity.detect",
        objective="Turn the observed findings into evidence-backed opportunities",
        depends_on=["website_audit"],
        after=[
            "gsc_analysis",
            "content_gap",
            "content_update",
            "competitive_gap",
            *SEED_STAGES,
        ],
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
    "quality_review": _stage(
        "quality_review",
        "QUAL-001",
        "recommendation.audit",
        "Audit the recommendations against the evidence behind them",
        depends_on=["recommendation"],
        tools=["memory"],
    ),
    "policy_review": _stage(
        "policy_review",
        "POL-001",
        "policy.evaluate",
        "Hold drafts and open actions to the brand's rules and current policy",
        depends_on=["brand_understanding"],
        after=["recommendation", "quality_review", "content_quality_gate"],
        tools=["policy", "memory"],
    ),
    "execution_plan": StageSpec(
        stage="execution_plan",
        agent_id="EXE-001",
        task_type="execution.plan",
        objective="Turn approved recommendations into a concrete, approvable action plan",
        depends_on=["recommendation"],
        after=["quality_review", "policy_review"],
        capabilities=["execution.plan"],
        tools=["cms"],
    ),
    "publishing": _stage(
        "publishing",
        "PUB-001",
        "content.publish",
        "Publish only content that has passed every gate and approval",
        depends_on=["content_quality_gate", "policy_review"],
        after=["content_repurposing"],
        capabilities=["content.publish", "cms.publish"],
        tools=["cms"],
        priority=TaskPriority.HIGH,
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
        upstream = [
            created[dep] for dep in dict.fromkeys([*spec.depends_on, *spec.after]) if dep in created
        ]
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
    "MISSION_PATTERNS",
    "MISSION_STAGES",
    "MISSION_TARGET_METRIC",
    "SEED_STAGES",
    "STAGE_SPECS",
    "MissionPlan",
    "Orchestrator",
    "PlannedStage",
    "StageSpec",
    "build_task_graph",
    "classify_objective",
]
