"""Contract tests for the core schemas.

These lock in the rules the rest of the platform depends on:
evidence-or-hypothesis, honest provenance, probabilistic intent, and the
internal (explicitly non-Google) scoring model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError
from seo_engine.schemas.agent import (
    AgentManifest,
    AgentResult,
    ProposedRecommendation,
)
from seo_engine.schemas.enums import (
    DataProvenance,
    EvidenceType,
    PermissionLevel,
    SearchIntent,
)
from seo_engine.schemas.evidence import EvidenceRecord
from seo_engine.schemas.search import IntentDistribution, KeywordMetric, KeywordScoreBreakdown


def _evidence(**overrides: object) -> EvidenceRecord:
    payload: dict[str, object] = {
        "id": "ev_1",
        "type": EvidenceType.CRAWL_RESULT,
        "source": "crawler",
        "observation": "The page has no meta description.",
        "observed_at": datetime.now(UTC),
    }
    payload.update(overrides)
    return EvidenceRecord(**payload)  # type: ignore[arg-type]


# --- Evidence --------------------------------------------------------------
def test_evidence_requires_a_non_empty_observation() -> None:
    with pytest.raises(PydanticValidationError):
        _evidence(observation="   ")


def test_observation_and_inference_are_distinguishable() -> None:
    assert _evidence(type=EvidenceType.GSC).is_observation is True
    assert _evidence(type=EvidenceType.MODEL_INFERENCE).is_inference is True


# --- Recommendations -------------------------------------------------------
def test_recommendation_without_evidence_is_rejected() -> None:
    with pytest.raises(PydanticValidationError, match="cite evidence or be marked"):
        ProposedRecommendation(
            type="content_update",
            title="Update the pricing guide",
            problem="Outdated pricing",
            opportunity="Recover commercial queries",
            reason="Competitors publish current prices",
        )


def test_recommendation_without_evidence_is_allowed_when_declared_a_hypothesis() -> None:
    rec = ProposedRecommendation(
        type="content_update",
        title="Update the pricing guide",
        problem="Outdated pricing",
        opportunity="Recover commercial queries",
        reason="Strategic hypothesis pending data",
        is_hypothesis=True,
    )
    assert rec.evidence_ids == []
    assert rec.is_hypothesis is True


def test_recommendation_with_evidence_needs_no_hypothesis_flag() -> None:
    rec = ProposedRecommendation(
        type="content_update",
        title="Update the pricing guide",
        problem="Outdated pricing",
        opportunity="Recover commercial queries",
        reason="GSC shows impressions without clicks",
        evidence_ids=["ev_1", "ev_2"],
    )
    assert rec.is_hypothesis is False


# --- Agent result ----------------------------------------------------------
def test_agent_result_requires_a_summary() -> None:
    with pytest.raises(PydanticValidationError):
        AgentResult(task_id=uuid.uuid4(), agent_id="SEO-001", summary="  ")


# --- Manifest --------------------------------------------------------------
def test_manifest_defaults_ungranted_capabilities_to_read() -> None:
    manifest = AgentManifest(
        id="SEO-003",
        name="Keyword Intelligence Agent",
        version="1.0.0",
        description="Discovers and clusters search opportunities.",
        capabilities=["seo.keyword.research", "seo.keyword.cluster"],
        input_schema="KeywordResearchInput",
        output_schema="KeywordResearchOutput",
    )
    assert manifest.permission_for("seo.keyword.research") == PermissionLevel.READ
    assert manifest.permission_for("content.publish") == PermissionLevel.DENY


def test_manifest_rejects_a_malformed_agent_id() -> None:
    with pytest.raises(PydanticValidationError):
        AgentManifest(
            id="keyword-agent",
            name="x",
            version="1.0.0",
            description="x",
            capabilities=["a"],
            input_schema="A",
            output_schema="B",
        )


def test_manifest_rejects_duplicate_capabilities() -> None:
    with pytest.raises(PydanticValidationError, match="duplicate"):
        AgentManifest(
            id="SEO-003",
            name="x",
            version="1.0.0",
            description="x",
            capabilities=["seo.keyword.research", "seo.keyword.research"],
            input_schema="A",
            output_schema="B",
        )


# --- Search ----------------------------------------------------------------
def test_intent_distribution_normalises_and_reports_a_primary() -> None:
    intent = IntentDistribution(informational=1.5, commercial=7.2, transactional=1.3)
    assert sum(intent.as_dict().values()) == pytest.approx(1.0, abs=1e-3)
    assert intent.primary is SearchIntent.COMMERCIAL


def test_empty_intent_defaults_to_informational_rather_than_inventing_one() -> None:
    assert IntentDistribution().primary is SearchIntent.INFORMATIONAL


def test_keyword_metric_defaults_to_unknown_provenance() -> None:
    """Rule 14: absent provider data must never look like observed data."""
    metric = KeywordMetric(name="search_volume")
    assert metric.value is None
    assert metric.provenance is DataProvenance.UNKNOWN


def test_opportunity_score_uses_the_documented_internal_weighting() -> None:
    breakdown = KeywordScoreBreakdown(
        business_relevance=100,
        intent_value=100,
        demand=0,
        ranking_feasibility=0,
        competitive_gap=0,
        conversion_potential=0,
    )
    # 100*0.30 + 100*0.20 = 50
    assert breakdown.opportunity_score == pytest.approx(50.0)
    assert sum(breakdown.weights.values()) == pytest.approx(1.0)
