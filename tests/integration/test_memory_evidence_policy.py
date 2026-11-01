"""Memory, evidence and policy engine tests."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from seo_engine.evidence.collector import EvidenceCollector
from seo_engine.memory.embedding import HashingEmbedder, cosine_similarity
from seo_engine.memory.service import MemoryService
from seo_engine.policies.engine import ActionRequest, PolicyEngine
from seo_engine.schemas.enums import (
    ActionType,
    AutomationPolicy,
    DataProvenance,
    EvidenceType,
    MemoryScope,
    MemoryType,
    RiskCategory,
    RiskLevel,
)
from seo_engine.shared.errors import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import make_tenant

pytestmark = [pytest.mark.integration]


# --- Embedding --------------------------------------------------------------
def test_embeddings_are_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder()
    a = embedder.embed("dna paternity testing in lagos")
    b = embedder.embed("dna paternity testing in lagos")
    assert a == b
    assert abs(sum(v * v for v in a) - 1.0) < 1e-6


def test_related_text_scores_above_unrelated_text() -> None:
    embedder = HashingEmbedder()
    query = embedder.embed("dna paternity test price")
    related = embedder.embed("how much does a dna paternity test cost")
    unrelated = embedder.embed("commercial roof insulation contractors")
    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_empty_text_never_produces_a_zero_vector() -> None:
    """A zero vector has no direction and breaks cosine distance."""
    vector = HashingEmbedder().embed("")
    assert any(v != 0.0 for v in vector)


# --- Memory -----------------------------------------------------------------
async def test_store_and_semantic_search_round_trip(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    brand_id = uuid.uuid4()
    service = MemoryService(session, principal.tenant_id)

    await service.store(
        key="brand:services",
        content="The clinic offers DNA paternity testing and prenatal screening in Lagos.",
        brand_id=brand_id,
    )
    await service.store(
        key="brand:logistics",
        content="Sample collection is available at three walk-in centres.",
        brand_id=brand_id,
    )

    hits = await service.search_semantic("paternity testing", brand_id=brand_id)
    assert hits, "semantic search returned nothing"
    assert hits[0].memory.key == "brand:services"
    assert hits[0].score > 0


async def test_brand_scoped_memory_does_not_leak_between_brands(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = MemoryService(session, principal.tenant_id)
    brand_a, brand_b = uuid.uuid4(), uuid.uuid4()

    await service.store(key="a", content="Brand A pricing strategy", brand_id=brand_a)
    await service.store(key="b", content="Brand B pricing strategy", brand_id=brand_b)

    found = await service.retrieve(brand_id=brand_a)
    assert {m.key for m in found} == {"a"}


async def test_tenant_scoped_memory_is_visible_to_all_brands_in_that_tenant(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = MemoryService(session, principal.tenant_id)
    brand_a = uuid.uuid4()

    await service.store(
        key="tenant:preference",
        content="This customer prefers British English spelling.",
        scope=MemoryScope.TENANT,
        memory_type=MemoryType.PREFERENCE,
        brand_id=None,
    )
    found = await service.retrieve(brand_id=brand_a)
    assert "tenant:preference" in {m.key for m in found}


async def test_brand_scoped_memory_requires_a_brand(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    with pytest.raises(ValidationError, match="requires a brand_id"):
        await MemoryService(session, principal.tenant_id).store(
            key="k", content="c", scope=MemoryScope.BRAND, brand_id=None
        )


async def test_working_memory_expires_and_brand_facts_do_not(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = MemoryService(session, principal.tenant_id)
    brand_id = uuid.uuid4()

    working = await service.store(
        key="task:scratch",
        content="12 opportunities under consideration",
        memory_type=MemoryType.WORKING,
        brand_id=brand_id,
    )
    fact = await service.store(key="brand:fact", content="Founded in 2011", brand_id=brand_id)
    assert working.expires_at is not None
    assert fact.expires_at is None


async def test_expired_memory_is_forgotten_and_no_longer_retrieved(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = MemoryService(session, principal.tenant_id)
    brand_id = uuid.uuid4()

    await service.store(
        key="task:stale",
        content="stale working note",
        memory_type=MemoryType.WORKING,
        brand_id=brand_id,
        ttl=timedelta(seconds=-1),
    )
    assert await service.forget_expired() >= 1
    assert await service.retrieve(brand_id=brand_id, key="task:stale") == []


async def test_forget_is_soft_by_default_so_the_trail_survives(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    service = MemoryService(session, principal.tenant_id)
    record = await service.store(key="k", content="c", brand_id=uuid.uuid4())

    await service.forget(record.id)
    assert record.is_active is False
    assert record.forgotten_at is not None
    assert await service.repo.get(record.id) is not None


async def test_outcome_memory_records_conditions_not_universal_rules(
    session: AsyncSession, tenant_ctx
) -> None:
    """Architecture Pack §85: never learn 'X always works'."""
    _, _, principal = tenant_ctx
    memory = await MemoryService(session, principal.tenant_id).record_outcome(
        brand_id=uuid.uuid4(),
        action_summary="the page title was rewritten to lead with the service",
        result_summary="click-through rate rose from 2.1% to 2.5%",
        metric="ctr",
        delta=0.4,
        window_days=28,
        confidence=0.82,
        conditions=["existing authority", "commercial intent", "strong internal links"],
    )
    assert "Under these conditions" in memory.content
    assert memory.conditions == [
        "existing authority",
        "commercial intent",
        "strong internal links",
    ]
    assert "always" not in memory.content.lower()


# --- Evidence ---------------------------------------------------------------
async def test_observations_and_inferences_are_stored_distinctly(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    brand_id = uuid.uuid4()
    collector = EvidenceCollector(session, principal.tenant_id, brand_id=brand_id)

    observed = collector.observe(
        evidence_type=EvidenceType.CRAWL_RESULT,
        source="crawler",
        observation="12 pages have no meta description.",
        data={"count": 12},
    )
    inferred = collector.infer(
        source="technical_seo",
        conclusion="Missing descriptions are suppressing click-through on commercial pages.",
        confidence=0.6,
        derived_from=[observed.id],
    )

    assert observed.provenance is DataProvenance.OBSERVED
    assert inferred.provenance is DataProvenance.INFERRED
    assert observed.is_observation and inferred.is_inference

    rows = await collector.persist()
    by_ref = {row.ref: row for row in rows}
    assert by_ref[observed.id].is_observation is True
    assert by_ref[inferred.id].is_observation is False
    assert by_ref[inferred.id].structured_data["derived_from"] == [observed.id]


async def test_persisting_the_same_evidence_twice_is_idempotent(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    collector = EvidenceCollector(session, principal.tenant_id)
    collector.observe(
        evidence_type=EvidenceType.CRAWL_RESULT, source="crawler", observation="Observed."
    )
    first = await collector.persist()
    second = await collector.persist()
    assert [r.id for r in first] == [r.id for r in second]


async def test_inference_confidence_is_capped_below_certainty(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    collector = EvidenceCollector(session, principal.tenant_id)
    record = collector.infer(source="x", conclusion="A conclusion.", confidence=1.0)
    assert record.confidence <= 0.95


async def test_evidence_can_be_reloaded_by_reference(session: AsyncSession, tenant_ctx) -> None:
    _, _, principal = tenant_ctx
    collector = EvidenceCollector(session, principal.tenant_id)
    record = collector.observe(
        evidence_type=EvidenceType.GSC, source="gsc", observation="1,204 impressions."
    )
    await collector.persist()

    reloaded = await collector.load([record.id])
    assert [r.observation for r in reloaded] == ["1,204 impressions."]
    assert reloaded[0].type is EvidenceType.GSC


# --- Policy -----------------------------------------------------------------
async def test_medical_content_publication_always_requires_approval(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    engine = PolicyEngine(session, principal.tenant_id)
    await engine.seed_default_policies()

    decision = await engine.evaluate(
        ActionRequest(
            action_type=ActionType.CMS_PUBLISH,
            risk=RiskLevel.LOW,
            category=RiskCategory.MEDICAL,
            automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
        )
    )
    assert decision.requires_approval is True
    assert "medical" in decision.reason or "regulated" in decision.reason


async def test_general_content_follows_the_tenant_automation_policy(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    engine = PolicyEngine(session, principal.tenant_id)
    await engine.seed_default_policies()

    supervised = await engine.evaluate(
        ActionRequest(
            action_type=ActionType.CMS_PUBLISH,
            risk=RiskLevel.LOW,
            category=RiskCategory.GENERAL,
            automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
        )
    )
    assert supervised.requires_approval is False

    approval_required = await engine.evaluate(
        ActionRequest(
            action_type=ActionType.CMS_PUBLISH,
            risk=RiskLevel.MEDIUM,
            category=RiskCategory.GENERAL,
            automation_policy=AutomationPolicy.APPROVAL_REQUIRED,
        )
    )
    assert approval_required.requires_approval is True


@pytest.mark.parametrize(
    ("increase_percent", "expected"),
    [(10, False), (20, False), (21, True), (200, True)],
)
async def test_ads_budget_threshold_rule_uses_numeric_comparison(
    session: AsyncSession, tenant_ctx, increase_percent: int, expected: bool
) -> None:
    _, _, principal = tenant_ctx
    engine = PolicyEngine(session, principal.tenant_id)
    await engine.seed_default_policies()

    decision = await engine.evaluate(
        ActionRequest(
            action_type=ActionType.ADS_BUDGET_CHANGE,
            risk=RiskLevel.LOW,
            automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
            attributes={"increase_percent": increase_percent},
        )
    )
    # Any ad spend change requires approval regardless; the threshold rule adds
    # its own explicit reason above 20%.
    assert decision.requires_approval is True
    assert ("above 20%" in decision.reason) is expected


async def test_destructive_actions_always_require_approval(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    engine = PolicyEngine(session, principal.tenant_id)
    await engine.seed_default_policies()

    for action in (ActionType.PAGE_DELETE, ActionType.REDIRECT_CREATE):
        decision = await engine.evaluate(
            ActionRequest(
                action_type=action,
                risk=RiskLevel.LOW,
                automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
            )
        )
        assert decision.requires_approval is True, action


async def test_an_unrecognised_action_defaults_to_requiring_approval(
    session: AsyncSession, tenant_ctx
) -> None:
    """Fail closed: an action nobody anticipated is not auto-approved."""
    _, _, principal = tenant_ctx
    decision = await PolicyEngine(session, principal.tenant_id).evaluate(
        ActionRequest(
            action_type="some.brand.new.action",
            risk=RiskLevel.HIGH,
            automation_policy=AutomationPolicy.SUPERVISED_AUTONOMY,
        )
    )
    assert decision.requires_approval is True
    assert "no policy matched" in decision.reason


async def test_manual_automation_policy_overrides_everything(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    engine = PolicyEngine(session, principal.tenant_id)
    await engine.seed_default_policies()

    decision = await engine.evaluate(
        ActionRequest(
            action_type=ActionType.CMS_PUBLISH,
            risk=RiskLevel.LOW,
            category=RiskCategory.GENERAL,
            automation_policy=AutomationPolicy.MANUAL,
        )
    )
    assert decision.requires_approval is True
    assert "manual" in decision.reason


async def test_a_deny_rule_blocks_the_action_outright(session: AsyncSession, tenant_ctx) -> None:
    from seo_engine.domain.models.decision import Policy
    from seo_engine.domain.repositories import repository_for

    _, _, principal = tenant_ctx
    repo = repository_for(Policy)(session, principal.tenant_id)
    repo.add(
        Policy(
            name="no-deletions",
            scope="website",
            rules=[
                {
                    "when": {"action": ActionType.PAGE_DELETE.value},
                    "require": {"deny": True},
                    "reason": "this tenant never permits automated deletion",
                }
            ],
        )
    )
    await session.flush()

    decision = await PolicyEngine(session, principal.tenant_id).evaluate(
        ActionRequest(action_type=ActionType.PAGE_DELETE, risk=RiskLevel.LOW)
    )
    assert decision.allowed is False
    assert "never permits" in decision.reason


async def test_policies_are_tenant_scoped(
    session: AsyncSession, second_session: AsyncSession
) -> None:
    _, _, alice = await make_tenant(session, "alice")
    _, _, bob = await make_tenant(second_session, "bob")

    await PolicyEngine(second_session, bob.tenant_id).seed_default_policies()
    await second_session.commit()

    try:
        assert await PolicyEngine(session, alice.tenant_id).policies_for(None) == []
    finally:
        from seo_engine.domain.models.decision import Policy
        from seo_engine.domain.repositories import repository_for

        await repository_for(Policy)(second_session, bob.tenant_id).delete_where()
        await second_session.commit()
