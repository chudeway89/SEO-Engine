"""Decision stack tests: opportunity → recommendation → approval → action → outcome."""

from __future__ import annotations

import uuid

import pytest
from seo_engine.domain.models.decision import ActionApproval
from seo_engine.domain.models.observability import AuditLog, EventRecord
from seo_engine.domain.services import BrandService, DecisionService
from seo_engine.engines.opportunities.detection import (
    DetectedOpportunity,
    from_content_gaps,
    from_keyword_positions,
    from_technical_issues,
    prioritise,
    prioritise_all,
)
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.agent import ProposedRecommendation
from seo_engine.schemas.enums import (
    ActionStatus,
    ActionType,
    AutomationPolicy,
    ContentDecision,
    DataProvenance,
    IssueSeverity,
    OpportunityType,
    RecommendationStatus,
    RiskCategory,
    RiskLevel,
    Role,
    SEODimension,
)
from seo_engine.schemas.search import ContentGap, IntentDistribution, KeywordMetric, KeywordRecord
from seo_engine.schemas.seo import SEOIssue
from seo_engine.shared.errors import (
    ApprovalRequiredError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


async def _brand(session: AsyncSession, principal: Principal):
    return await BrandService(session, principal).create(
        name=f"Acme {uuid.uuid4().hex[:6]}", industry="healthcare"
    )


def _recommendation(**overrides) -> ProposedRecommendation:
    base = {
        "type": "content_update",
        "title": "Update the pricing guide",
        "problem": "The pricing guide has not been revised since 2024.",
        "opportunity": "Recover commercial queries currently going to competitors.",
        "reason": "Search Console shows impressions without clicks on this URL.",
        "evidence_ids": ["ev_1"],
        "business_impact": 8.0,
        "seo_impact": 7.0,
        "effort": 4.0,
        "confidence": 0.8,
    }
    base.update(overrides)
    return ProposedRecommendation(**base)


# --- Detection --------------------------------------------------------------
def test_technical_issues_group_into_one_opportunity_per_check() -> None:
    issues = [
        SEOIssue(
            check_id="missing_meta_description",
            title="Page has no meta description",
            severity=IssueSeverity.MEDIUM,
            dimension=SEODimension.SEARCH_ALIGNMENT,
            url=f"https://acme.test/p{i}",
        )
        for i in range(20)
    ]
    detected = from_technical_issues(issues, pages_total=40)
    assert len(detected) == 1
    assert "20 page(s)" in detected[0].title
    assert detected[0].data["affected_count"] == 20


def test_an_issue_on_a_commercial_page_scores_higher() -> None:
    issue = SEOIssue(
        check_id="missing_title",
        title="Page has no title element",
        severity=IssueSeverity.CRITICAL,
        dimension=SEODimension.SEARCH_ALIGNMENT,
        url="https://acme.test/services/dna-testing",
    )
    commercial = from_technical_issues(
        [issue], pages_total=10, commercial_urls={"https://acme.test/services/dna-testing"}
    )[0]
    ordinary = from_technical_issues([issue], pages_total=10)[0]
    assert commercial.business_impact > ordinary.business_impact
    assert commercial.strategic_fit > ordinary.strategic_fit


def test_a_do_nothing_gap_produces_no_opportunity() -> None:
    """The correct action is sometimes no action."""
    gap = ContentGap(
        topic="something nobody searches",
        decision=ContentDecision.DO_NOTHING,
        decision_reason="no evidence justifies a page",
    )
    assert from_content_gaps([gap]) == []


def test_gap_decisions_map_to_the_right_opportunity_types() -> None:
    gaps = [
        ContentGap(topic="a", decision=ContentDecision.CREATE),
        ContentGap(topic="b", decision=ContentDecision.UPDATE),
        ContentGap(topic="c", decision=ContentDecision.CONSOLIDATE),
    ]
    types = [o.opportunity_type for o in from_content_gaps(gaps)]
    assert types == [
        OpportunityType.CONTENT_CREATE,
        OpportunityType.CONTENT_UPDATE,
        OpportunityType.CONTENT_CONSOLIDATE,
    ]


def test_a_transactional_gap_outscores_an_informational_one_on_business_impact() -> None:
    transactional = ContentGap(
        topic="book a dna test",
        decision=ContentDecision.CREATE,
        intent=IntentDistribution(transactional=1.0),
    )
    informational = ContentGap(
        topic="what is dna",
        decision=ContentDecision.CREATE,
        intent=IntentDistribution(informational=1.0),
    )
    detected = from_content_gaps([transactional, informational])
    assert detected[0].business_impact > detected[1].business_impact


def test_position_opportunities_require_observed_data() -> None:
    """Rule 14: no GSC, no position opportunities — not guessed ones."""
    unmeasured = KeywordRecord(
        keyword="dna test cost",
        normalised="dna test cost",
        metrics=[KeywordMetric(name="search_volume", provenance=DataProvenance.UNKNOWN)],
    )
    assert from_keyword_positions([unmeasured]) == []

    measured = KeywordRecord(
        keyword="dna test cost",
        normalised="dna test cost",
        metrics=[
            KeywordMetric(name="position", value=8.4, provenance=DataProvenance.OBSERVED),
            KeywordMetric(name="impressions", value=1200, provenance=DataProvenance.OBSERVED),
        ],
    )
    found = from_keyword_positions([measured])
    assert len(found) == 1
    assert found[0].data["position"] == 8.4


def test_positions_outside_the_realistic_band_are_ignored() -> None:
    def record(position: float) -> KeywordRecord:
        return KeywordRecord(
            keyword="k",
            normalised="k",
            metrics=[
                KeywordMetric(name="position", value=position, provenance=DataProvenance.OBSERVED),
                KeywordMetric(name="impressions", value=500, provenance=DataProvenance.OBSERVED),
            ],
        )

    assert from_keyword_positions([record(1.2)]) == []
    assert from_keyword_positions([record(64.0)]) == []
    assert len(from_keyword_positions([record(7.0)])) == 1


# --- Prioritisation ---------------------------------------------------------
def test_priority_follows_the_documented_formula() -> None:
    opportunity = prioritise(
        DetectedOpportunity(
            opportunity_type=OpportunityType.ON_PAGE,
            title="t",
            description="d",
            business_impact=10,
            seo_impact=10,
            effort=1.0,
            confidence=1.0,
            strategic_fit=1.0,
        )
    )
    # impact 10 x 1 x 1 / 1 = 10 → 50% of the theoretical maximum of 20.
    assert opportunity.priority_score == pytest.approx(50.0)
    assert "not a Google ranking formula" in opportunity.priority_breakdown["formula"]


def test_higher_effort_lowers_priority_and_higher_confidence_raises_it() -> None:
    def build(effort: float, confidence: float) -> float:
        return prioritise(
            DetectedOpportunity(
                opportunity_type=OpportunityType.ON_PAGE,
                title="t",
                description="d",
                business_impact=8,
                seo_impact=8,
                effort=effort,
                confidence=confidence,
            )
        ).priority_score

    assert build(2.0, 0.8) > build(8.0, 0.8)
    assert build(4.0, 0.9) > build(4.0, 0.4)


def test_prioritise_all_orders_by_score() -> None:
    scored = prioritise_all(
        [
            DetectedOpportunity(
                opportunity_type=OpportunityType.ON_PAGE,
                title="low",
                description="",
                business_impact=2,
                seo_impact=2,
                effort=9,
                confidence=0.3,
            ),
            DetectedOpportunity(
                opportunity_type=OpportunityType.ON_PAGE,
                title="high",
                description="",
                business_impact=9,
                seo_impact=9,
                effort=1,
                confidence=0.95,
            ),
        ]
    )
    assert [o.title for o in scored] == ["high", "low"]


# --- Persistence ------------------------------------------------------------
async def test_opportunities_persist_with_their_priority_working(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    stored = await service.record_opportunities(
        brand.id,
        [
            DetectedOpportunity(
                opportunity_type=OpportunityType.ON_PAGE,
                title="Fix missing titles",
                description="d",
                business_impact=8,
                seo_impact=8,
                effort=2,
                confidence=0.9,
                evidence_refs=["ev_1"],
            )
        ],
        agent_id="OPP-001",
    )
    assert stored[0].priority_score > 0
    assert stored[0].priority_breakdown["formula"]
    assert stored[0].evidence_refs == ["ev_1"]

    events = await session.execute(
        select(EventRecord).where(EventRecord.aggregate_id == str(stored[0].id))
    )
    assert events.scalars().first().event_type == "OpportunityDetected"


async def test_redetecting_an_opportunity_refreshes_rather_than_duplicates(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    def build(confidence: float) -> DetectedOpportunity:
        return DetectedOpportunity(
            opportunity_type=OpportunityType.ON_PAGE,
            title="Fix missing titles",
            description="d",
            business_impact=8,
            seo_impact=8,
            effort=2,
            confidence=confidence,
        )

    first = await service.record_opportunities(brand.id, [build(0.5)])
    second = await service.record_opportunities(brand.id, [build(0.9)])

    assert first[0].id == second[0].id
    assert len(await service.list_opportunities(brand.id)) == 1


async def test_a_recommendation_without_evidence_is_refused(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    with pytest.raises(ValidationError):
        # Bypass the schema validator to prove the service refuses it too.
        proposed = ProposedRecommendation.model_construct(
            type="content_update",
            title="t",
            problem="p",
            opportunity="o",
            reason="r",
            evidence_ids=[],
            is_hypothesis=False,
            business_impact=5,
            seo_impact=5,
            effort=5,
            confidence=0.5,
            strategic_fit=0.7,
            risk=RiskLevel.LOW,
            dependencies=[],
        )
        await service.create_recommendation(brand.id, proposed)


async def test_a_hypothesis_is_accepted_and_labelled(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    record = await DecisionService(session, principal).create_recommendation(
        brand.id, _recommendation(evidence_ids=[], is_hypothesis=True, confidence=0.5)
    )
    assert record.is_hypothesis is True
    assert record.evidence_refs == []


async def test_approving_a_recommendation_is_audited(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    record = await service.create_recommendation(brand.id, _recommendation())

    approved = await service.approve_recommendation(record.id, note="looks right")
    assert approved.status == RecommendationStatus.APPROVED
    assert approved.decided_by == principal.user_id

    audits = await session.execute(select(AuditLog).where(AuditLog.resource_id == str(record.id)))
    entry = audits.scalars().one()
    assert entry.action == "recommendation.approve"
    assert entry.evidence_refs == ["ev_1"]


async def test_a_recommendation_cannot_be_decided_twice(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    record = await service.create_recommendation(brand.id, _recommendation())

    await service.approve_recommendation(record.id)
    with pytest.raises(ConflictError):
        await service.approve_recommendation(record.id)


async def test_an_editor_cannot_approve_a_recommendation(session: AsyncSession, tenant_ctx) -> None:
    tenant, user, owner = tenant_ctx
    brand = await _brand(session, owner)
    record = await DecisionService(session, owner).create_recommendation(
        brand.id, _recommendation()
    )

    editor = Principal.build(
        user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.EDITOR
    )
    with pytest.raises(PermissionDeniedError):
        await DecisionService(session, editor).approve_recommendation(record.id)


# --- Actions ----------------------------------------------------------------
async def test_a_low_risk_draft_under_supervised_autonomy_needs_no_approval(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    await service.policies.seed_default_policies()

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.CMS_CREATE_DRAFT,
        target={"url": "https://acme.test/new"},
        payload={},
        automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
    )
    assert action.approval_required is False
    assert action.status == ActionStatus.APPROVED


async def test_publishing_medical_content_requires_approval(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    await service.policies.seed_default_policies()

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.CMS_PUBLISH,
        target={"url": "https://acme.test/treatment"},
        payload={},
        risk_category=RiskCategory.MEDICAL,
        automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
    )
    assert action.approval_required is True
    assert action.status == ActionStatus.PENDING_APPROVAL


async def test_an_unapproved_action_cannot_be_executed(session: AsyncSession, tenant_ctx) -> None:
    """The approval gate, checked immediately before execution."""
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    await service.policies.seed_default_policies()

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.CMS_PUBLISH,
        target={"url": "https://acme.test/x"},
        payload={},
        risk_category=RiskCategory.MEDICAL,
    )
    with pytest.raises(ApprovalRequiredError) as excinfo:
        await service.mark_executing(action.id)
    assert excinfo.value.details["action_type"] == ActionType.CMS_PUBLISH


async def test_an_approved_action_executes_and_records_an_approval_row(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    await service.policies.seed_default_policies()

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.CMS_PUBLISH,
        target={"url": "https://acme.test/x"},
        payload={},
        risk_category=RiskCategory.MEDICAL,
    )
    await service.approve_action(action.id, note="clinically reviewed")
    await service.mark_executing(action.id)
    executed = await service.mark_executed(
        action.id, {"draft_id": "123"}, mode="development_adapter"
    )

    assert executed.status == ActionStatus.EXECUTED
    approvals = await session.execute(
        select(ActionApproval).where(ActionApproval.action_id == action.id)
    )
    row = approvals.scalars().one()
    assert row.decision == "approved"
    assert row.decided_by_role == Role.OWNER.value


async def test_a_rejected_action_can_never_be_executed(session: AsyncSession, tenant_ctx) -> None:
    from seo_engine.shared.errors import PolicyViolationError

    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)
    await service.policies.seed_default_policies()

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.PAGE_DELETE,
        target={"url": "https://acme.test/x"},
        payload={},
        risk=RiskLevel.HIGH,
    )
    await service.reject_action(action.id, note="we still need that page")
    with pytest.raises(PolicyViolationError):
        await service.mark_executing(action.id)


async def test_proposing_the_same_action_twice_is_idempotent(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    kwargs = {
        "brand_id": brand.id,
        "action_type": ActionType.METADATA_UPDATE,
        "target": {"url": "https://acme.test/page"},
        "payload": {"title": "New title"},
    }
    first = await service.propose_action(**kwargs)
    second = await service.propose_action(**kwargs)
    assert first.id == second.id


async def test_executing_an_action_marks_its_recommendation_implemented(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    recommendation = await service.create_recommendation(brand.id, _recommendation())
    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.METADATA_UPDATE,
        target={"url": "https://acme.test/page"},
        payload={},
        recommendation_id=recommendation.id,
        automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
    )
    await service.mark_executing(action.id)
    await service.mark_executed(action.id, {"ok": True})
    assert recommendation.status == RecommendationStatus.IMPLEMENTED


# --- Outcomes ---------------------------------------------------------------
async def test_an_outcome_with_no_measurement_is_pending_not_zero(
    session: AsyncSession, tenant_ctx
) -> None:
    """An unmeasured action must never look like a failed one."""
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.METADATA_UPDATE,
        target={"url": "https://acme.test/p"},
        payload={},
        automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
    )
    outcome = await service.record_outcome(
        action.id, metric="organic_clicks", baseline=None, result=None
    )
    assert outcome.status == "pending"
    assert outcome.result is None
    assert outcome.delta is None
    assert "pending rather than as no change" in outcome.detail


async def test_a_measured_outcome_computes_the_delta(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand = await _brand(session, principal)
    service = DecisionService(session, principal)

    action = await service.propose_action(
        brand_id=brand.id,
        action_type=ActionType.METADATA_UPDATE,
        target={"url": "https://acme.test/p"},
        payload={},
        automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
    )
    outcome = await service.record_outcome(
        action.id,
        metric="organic_clicks",
        baseline=100.0,
        result=123.0,
        provenance=DataProvenance.OBSERVED,
        source="google_search_console",
        confidence=0.8,
    )
    assert outcome.delta == 23.0
    assert outcome.delta_percent == 23.0
    assert outcome.status == "measured"
    assert outcome.provenance == DataProvenance.OBSERVED.value
