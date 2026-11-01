"""Behavioural tests for the content production pipeline, the policy guardian
and the publishing agent.

The central property: **nothing publishes itself.** A draft written without a
model is an outline and is blocked; a passing draft reaches review and stops;
content is published only after a person approved the asset, the version passed
the quality gate and the policy review, and the publish action carries the
approval policy requires. With the development CMS the record says nothing
reached a real site.
"""

from __future__ import annotations

import uuid

import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from seo_engine.domain.models.agents import LLMUsage
from seo_engine.domain.models.decision import Policy
from seo_engine.domain.repositories import repository_for
from seo_engine.domain.seed.demo import build_demo_brand
from seo_engine.domain.services import ContentService, IntegrationService
from seo_engine.domain.services.content import EVALUATION_GATE, EVALUATION_QUALITY
from seo_engine.domain.services.decision import DecisionService
from seo_engine.schemas.content import (
    ContentBrief,
    ContentDraft,
    ContentEvaluation,
    ContentSection,
    EvaluationCriterionResult,
    InternalLinkTarget,
)
from seo_engine.schemas.enums import (
    ActionStatus,
    ContentStatus,
    IntegrationMode,
    IntegrationProvider,
    RiskCategory,
    RiskLevel,
    SynthesisMode,
)
from seo_engine.shared.llm import ModelGateway, ModelProviderError
from seo_engine.workflows.mission import MissionWorkflow
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.agents import AgentHarness
from tests.fixtures.fake_site import build_web_client
from tests.fixtures.models import ScriptedProvider

pytestmark = [pytest.mark.integration]

PROSE = (
    "The price of a DNA test depends on what the result will be used for. A test "
    "for personal knowledge needs less paperwork than one a court will rely on, "
    "because a legal test requires a documented chain of custody from the moment "
    "the sample is taken. Most people choose a home kit, which typically arrives "
    "within two working days. The laboratory then analyses the sample and, in most "
    "cases, reports within a week. Prices usually reflect the number of people "
    "tested and how quickly the result is needed. Our laboratory is UKAS accredited "
    "for DNA testing, and the accreditation covers both home and legal tests. Before "
    "you order, check whether a solicitor or a court has asked for a particular "
    "kind of test, because a home kit cannot be upgraded later. If you are unsure "
    "which test you need, our team can explain the options and what each one can "
    "and cannot tell you. Book a test when you are ready."
)


@pytest.fixture(scope="module", autouse=True)
def _registry() -> None:
    set_registry(AgentRegistry(find_repo_root() / "agents").load(force=True))


@pytest.fixture
async def harness(session: AsyncSession, tenant_ctx):
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)
    async with build_web_client() as client:
        yield AgentHarness(
            session=session,
            principal=principal,
            brand_id=scenario.brand.id,
            website_id=scenario.website.id,
            client=client,
        )


def _brief(**overrides) -> ContentBrief:
    fields = {
        "title": "How much does a DNA test cost?",
        "primary_topic": "dna test cost",
        "primary_keyword": "dna test cost",
        "audience": "Expectant parents",
        "business_goal": "Qualified enquiries",
        "unique_value_proposition": "Accredited pricing explained plainly",
        "required_sections": ["What affects the price"],
        "prohibited_claims": ["Our tests are 100% accurate."],
        "risk_category": RiskCategory.HEALTH,
        "target_word_count": 120,
        "cta": "Book a test",
    }
    fields.update(overrides)
    return ContentBrief(**fields)


def _draft(body: str = PROSE, *, title: str = "How much does a DNA test cost?") -> ContentDraft:
    return ContentDraft(
        title=title,
        meta_description="What a DNA test costs and why.",
        slug=f"dna-test-cost-{uuid.uuid4().hex[:6]}",
        sections=[ContentSection(heading="What affects the price", body=body)],
        body_markdown=f"# {title}\n\n## What affects the price\n\n{body}",
        cta="Book a test",
    )


async def _prose_asset(harness: AgentHarness, *, body: str = PROSE, evaluated: bool = True):
    """A written (not outline) draft with a brief, as a writer would hand over.

    The evaluator's scoring is unit-tested on its own; here a passing quality
    evaluation is recorded directly so the downstream gates are what is tested.
    """
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(harness.brand_id, _brief())
    draft = _draft(body)
    asset = await content.create_asset(
        harness.brand_id,
        title=draft.title,
        slug=draft.slug,
        url=f"https://acme.test/guides/{draft.slug}",
        risk_category=RiskCategory.HEALTH,
    )
    version = await content.add_version(asset, draft, change_summary="written", brief_id=brief.id)
    await content.link_brief_to_asset(brief.id, asset.id)
    if evaluated:
        await content.record_evaluation(
            asset.id,
            ContentEvaluation(overall_score=82.0, passed=True),
            version_id=version.id,
            evaluation_type=EVALUATION_QUALITY,
        )
    return content, asset, version


# --- the content production mission ---------------------------------------------
async def test_without_a_model_the_pipeline_produces_outlines_and_publishes_nothing(
    session: AsyncSession, tenant_ctx
) -> None:
    _, _, principal = tenant_ctx
    scenario = await build_demo_brand(session, principal)
    async with build_web_client() as client:
        harness = AgentHarness(session, principal, scenario.brand.id, scenario.website.id, client)
        workflow = MissionWorkflow(
            session,
            principal,
            extra_services={"crawler_factory": harness.crawler_factory},
            options={"max_pages": 30, "max_depth": 3, "max_content_topics": 2},
        )
        mission, plan = await workflow.plan(
            scenario.brand.id,
            "Write and publish content that answers prenatal screening questions",
            website_id=scenario.website.id,
        )
        report = await workflow.run(mission, plan)

    assert plan.mission_type == "content_production"
    assert report.failed_stages == [], f"stages failed: {report.failed_stages}"

    drafts = report.outputs["content_draft"]["content_writer"]
    assert drafts["drafts_written"] > 0
    assert drafts["outlines"] == drafts["drafts_written"], "no model: outlines only, never prose"

    gate = report.outputs["content_quality_gate"]["content_quality_gate"]
    assert gate["gated"] == drafts["drafts_written"] and gate["passed"] == 0
    assert all(any("outline" in b for b in r["blocking"]) for r in gate["results"])

    publishing = report.outputs["publishing"]["publishing"]
    assert publishing["published"] == []

    content = ContentService(session, principal)
    for item in drafts["drafts"]:
        asset = await content.get_asset(uuid.UUID(item["asset_id"]))
        assert asset.status == ContentStatus.DRAFT.value
        repairs = await content.list_repairs(asset.id)
        assert any(r.repair_type == "outline_needs_prose" for r in repairs), (
            "a block is tracked as a repair, not just reported"
        )


async def test_the_writer_declares_its_autonomous_action_and_reports_its_mode(
    harness: AgentHarness,
) -> None:
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(harness.brand_id, _brief(target_word_count=900))
    outcome = await harness.run("CNT-004", {"brief_ids": [str(brief.id)]})

    result = outcome.result
    assert [a.action_type for a in result.actions] == ["content.create"]
    assert result.requires_approval is False, "an internal draft changes nothing visible"
    assert result.synthesis_mode is SynthesisMode.DETERMINISTIC
    writer = result.outputs["content_writer"]
    assert writer["outlines"] == 1
    asset = await content.get_asset(uuid.UUID(writer["drafts"][0]["asset_id"]))
    assert asset.status == ContentStatus.DRAFT.value and asset.current_version == 1


async def test_with_a_model_the_writer_writes_prose_and_reports_a_hybrid_run(
    harness: AgentHarness,
) -> None:
    provider = ScriptedProvider(
        f"# How much does a DNA test cost?\n\n## What affects the price\n\n{PROSE}"
    )
    # Any model: the provider and the model name are whatever the operator connected.
    harness.extra["model_gateway"] = ModelGateway(provider=provider, model="any-connected-model")
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(harness.brand_id, _brief())

    outcome = await harness.run("CNT-004", {"brief_ids": [str(brief.id)]})

    result = outcome.result
    assert result.synthesis_mode is SynthesisMode.HYBRID, "a model wrote the prose"
    # Every model call is recorded against the run that made it, and what the
    # provider did not report (tokens) or the operator did not price (cost) is
    # recorded as unknown, never as zero.
    usage = await repository_for(LLMUsage)(harness.session, harness.principal.tenant_id).list(
        LLMUsage.agent_run_id == outcome.run.id
    )
    assert [(u.provider, u.model, u.succeeded) for u in usage] == [
        ("scripted_test_double", "any-connected-model", True)
    ]
    assert usage[0].agent_id == "CNT-004" and usage[0].estimated_cost_usd is None
    writer = result.outputs["content_writer"]
    assert writer["outlines"] == 0 and writer["drafts"][0]["synthesis_mode"] == "llm"
    assert provider.requests, "the run went through the injected gateway"
    # The brand's voice and the brief's prohibited claims reach the model as
    # policy, never as part of the untrusted channel.
    policy = "\n".join(m.content for m in provider.requests[0] if m.channel == "developer_policy")
    assert "Our tests are 100% accurate." in policy

    # A written draft is not mistaken for an outline by the quality gate.
    asset_id = writer["drafts"][0]["asset_id"]
    await harness.run("CNT-007", {"asset_ids": [asset_id]})
    gate = await harness.run("CNT-009", {"asset_ids": [asset_id]})
    blocking = gate.result.outputs["content_quality_gate"]["results"][0]["blocking"]
    assert not any("outline" in b for b in blocking)


async def test_when_the_connected_model_fails_the_writer_still_delivers(
    harness: AgentHarness,
) -> None:
    failing = ScriptedProvider([ModelProviderError("connection refused", retryable=False)])
    harness.extra["model_gateway"] = ModelGateway(provider=failing, model="any-connected-model")
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(harness.brand_id, _brief())

    outcome = await harness.run("CNT-004", {"brief_ids": [str(brief.id)]})

    result = outcome.result
    assert result.status == "completed", "a model failure never stops the platform"
    assert result.synthesis_mode is SynthesisMode.DETERMINISTIC
    assert result.outputs["content_writer"]["outlines"] == 1
    assert any("connection refused" in lim for lim in result.limitations), "and it says why"
    usage = await repository_for(LLMUsage)(harness.session, harness.principal.tenant_id).list(
        LLMUsage.agent_run_id == outcome.run.id
    )
    assert [u.succeeded for u in usage] == [False] and "connection refused" in usage[0].error


async def test_connecting_a_model_later_upgrades_the_outline_and_never_overwrites_prose(
    harness: AgentHarness,
) -> None:
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(harness.brand_id, _brief())
    inputs = {"brief_ids": [str(brief.id)]}

    # No model: an outline.
    first = await harness.run("CNT-004", inputs)
    asset_id = first.result.outputs["content_writer"]["drafts"][0]["asset_id"]

    # Still no model: running again adds nothing.
    again = await harness.run("CNT-004", inputs)
    assert again.result.outputs["content_writer"]["drafts_written"] == 0
    assert "outline is unchanged" in again.result.outputs["content_writer"]["skipped"][0]["reason"]

    # A model is connected — any model, and its own wording of the title does
    # not change which asset it writes into.
    provider = ScriptedProvider(
        f"# A different title the model chose\n\n## What affects the price\n\n{PROSE}"
    )
    harness.extra["model_gateway"] = ModelGateway(provider=provider, model="any-connected-model")
    upgraded = await harness.run("CNT-004", inputs)
    drafts = upgraded.result.outputs["content_writer"]["drafts"]
    assert [d["asset_id"] for d in drafts] == [asset_id] and drafts[0]["synthesis_mode"] == "llm"
    asset = await content.get_asset(uuid.UUID(asset_id))
    assert asset.current_version == 2

    # Prose is never overwritten, and the model is not even asked.
    calls = len(provider.sent)
    last = await harness.run("CNT-004", inputs)
    assert last.result.outputs["content_writer"]["drafts_written"] == 0
    assert "already written prose" in last.result.outputs["content_writer"]["skipped"][0]["reason"]
    assert len(provider.sent) == calls
    assert (await content.get_asset(uuid.UUID(asset_id))).current_version == 2


# --- evaluation, optimisation and the gate --------------------------------------
async def test_the_evaluator_records_its_verdict_against_the_exact_version(
    harness: AgentHarness,
) -> None:
    content, asset, version = await _prose_asset(harness, evaluated=False)
    outcome = await harness.run("CNT-007", {"asset_ids": [str(asset.id)]})

    evaluation = outcome.result.outputs["content_evaluation"]["evaluations"][0]
    assert evaluation["version_id"] == str(version.id)
    stored = await content.latest_evaluation(
        asset.id, evaluation_type=EVALUATION_QUALITY, version_id=version.id
    )
    assert stored is not None and stored.overall_score == evaluation["score"]


async def test_optimisation_records_edits_and_leaves_the_draft_untouched(
    harness: AgentHarness,
) -> None:
    content = ContentService(harness.session, harness.principal)
    brief = await content.save_brief(
        harness.brand_id,
        _brief(
            required_sections=["What affects the price", "How long results take"],
            internal_links=[
                InternalLinkTarget(url="https://acme.test/contact", anchor_text="contact us")
            ],
        ),
    )
    draft = _draft()
    asset = await content.create_asset(harness.brand_id, title=draft.title, slug=draft.slug)
    version = await content.add_version(asset, draft, change_summary="v1", brief_id=brief.id)
    await content.record_evaluation(
        asset.id,
        ContentEvaluation(
            criteria=[
                EvaluationCriterionResult(criterion="completeness", score=40, passed=False),
                EvaluationCriterionResult(criterion="internal_linking", score=20, passed=False),
            ],
            overall_score=66,
            passed=True,
        ),
        version_id=version.id,
        evaluation_type=EVALUATION_QUALITY,
    )

    outcome = await harness.run("CNT-005", {"asset_ids": [str(asset.id)]})
    edits = {e["edit_type"] for e in outcome.result.outputs["content_optimisation"]["edits"]}
    assert {"add_section", "add_internal_link"} <= edits
    assert {r.repair_type for r in await content.list_repairs(asset.id)} >= edits
    assert (await content.get_asset(asset.id)).current_version == 1, "no draft was rewritten"


async def test_a_passing_draft_reaches_review_and_stops_there(harness: AgentHarness) -> None:
    content, asset, version = await _prose_asset(harness)
    outcome = await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})

    gate = outcome.result.outputs["content_quality_gate"]["results"][0]
    assert gate["passed"] is True, gate["blocking"]
    refreshed = await content.get_asset(asset.id)
    assert refreshed.status == ContentStatus.IN_REVIEW.value, "review, never approval"
    stored = await content.latest_evaluation(
        asset.id, evaluation_type=EVALUATION_GATE, version_id=version.id
    )
    assert stored is not None and stored.passed and stored.requires_human_review


async def test_the_gate_blocks_a_draft_that_was_never_evaluated(harness: AgentHarness) -> None:
    content, asset, _ = await _prose_asset(harness, evaluated=False)
    outcome = await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})
    gate = outcome.result.outputs["content_quality_gate"]["results"][0]
    assert gate["passed"] is False
    assert (await content.get_asset(asset.id)).status == ContentStatus.DRAFT.value


# --- policy ----------------------------------------------------------------------
async def test_the_policy_guardian_returns_a_prohibited_claim_to_draft(
    harness: AgentHarness,
) -> None:
    content, asset, _ = await _prose_asset(
        harness, body=PROSE + " Our tests are 100% accurate, guaranteed."
    )
    await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})
    assert (await content.get_asset(asset.id)).status == ContentStatus.IN_REVIEW.value

    outcome = await harness.run("POL-001", {"asset_ids": [str(asset.id)]})
    review = outcome.result.outputs["policy_review"]
    rules = {v["rule"] for v in review["content"][0]["violations"]}
    assert {"prohibited_claim", "forbidden_terminology", "absolute_outcome_language"} <= rules
    assert review["returned_to_draft"] == 1
    assert (await content.get_asset(asset.id)).status == ContentStatus.DRAFT.value


async def test_the_policy_guardian_reports_an_action_current_policy_would_block(
    harness: AgentHarness,
) -> None:
    decisions = DecisionService(harness.session, harness.principal)
    action = await decisions.propose_action(
        brand_id=harness.brand_id,
        action_type="seo.metadata_update",
        target={"url": "https://acme.test/"},
        payload={},
        risk=RiskLevel.LOW,
    )
    assert action.status in {ActionStatus.APPROVED, ActionStatus.PENDING_APPROVAL}

    repository_for(Policy)(harness.session, harness.principal.tenant_id).add(
        Policy(
            name="metadata-freeze",
            rules=[
                {
                    "when": {"action_type": "seo.metadata_update"},
                    "require": {"deny": True},
                    "reason": "metadata is frozen during the site migration",
                }
            ],
        )
    )
    await harness.session.flush()

    outcome = await harness.run("POL-001")
    attention = outcome.result.outputs["policy_review"]["actions_needing_attention"]
    assert [a["action_id"] for a in attention] == [str(action.id)]
    assert "blocks" in attention[0]["problem"]
    assert "frozen" in attention[0]["policy_reason"]


# --- publishing -------------------------------------------------------------------
async def test_publishing_needs_editorial_approval_and_action_approval(
    harness: AgentHarness,
) -> None:
    content, asset, _ = await _prose_asset(harness)
    await IntegrationService(harness.session, harness.principal).connect(
        harness.brand_id, IntegrationProvider.GENERIC_CMS
    )
    await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})
    await harness.run("POL-001", {"asset_ids": [str(asset.id)]})

    # 1. In review, not approved by a person: nothing happens.
    first = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    assert first.result.outputs["publishing"]["awaiting_editorial_approval"] == 1
    assert first.result.outputs["publishing"]["published"] == []

    # 2. A person approves the content; health content still needs the action approved.
    await content.approve(asset.id, note="clinically reviewed")
    second = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    waiting = second.result.outputs["publishing"]["awaiting_action_approval"]
    assert len(waiting) == 1 and second.result.requires_approval is True
    assert (await content.get_asset(asset.id)).status == ContentStatus.APPROVED.value

    # 3. A person approves the publish action; now, and only now, it publishes.
    decisions = DecisionService(harness.session, harness.principal)
    await decisions.approve_action(uuid.UUID(waiting[0]["action_id"]), note="go")
    third = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    published = third.result.outputs["publishing"]["published"]
    assert len(published) == 1
    assert published[0]["mode"] == IntegrationMode.DEVELOPMENT_ADAPTER.value
    assert any("Nothing reached a real website" in lim for lim in third.result.limitations)

    refreshed = await content.get_asset(asset.id)
    assert refreshed.status == ContentStatus.PUBLISHED.value
    assert refreshed.external_ref["mode"] == IntegrationMode.DEVELOPMENT_ADAPTER.value
    executed = [
        a for a in await decisions.list_actions(harness.brand_id) if a.action_type == "cms.publish"
    ]
    assert [a.status for a in executed] == [ActionStatus.EXECUTED.value]


async def test_publishing_refuses_an_approved_asset_whose_new_version_is_unreviewed(
    harness: AgentHarness,
) -> None:
    content, asset, _ = await _prose_asset(harness)
    await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})
    await harness.run("POL-001", {"asset_ids": [str(asset.id)]})
    await content.approve(asset.id)

    # Any change is a new version, which sends the asset back through review.
    await content.add_version(asset, _draft(PROSE + " Updated."), change_summary="edit")
    assert (await content.get_asset(asset.id)).status == ContentStatus.DRAFT.value
    outcome = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    assert outcome.result.outputs["publishing"]["published"] == []


async def test_without_a_connected_cms_nothing_is_published(harness: AgentHarness) -> None:
    # The demonstration brand connects the development CMS; revoke it.
    await IntegrationService(harness.session, harness.principal).disconnect(
        harness.brand_id, IntegrationProvider.GENERIC_CMS
    )
    content, asset, _ = await _prose_asset(harness)
    await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})
    await harness.run("POL-001", {"asset_ids": [str(asset.id)]})
    await content.approve(asset.id)
    first = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    action_id = first.result.outputs["publishing"]["awaiting_action_approval"][0]["action_id"]
    await DecisionService(harness.session, harness.principal).approve_action(uuid.UUID(action_id))

    outcome = await harness.run("PUB-001", {"asset_ids": [str(asset.id)]})
    assert outcome.result.outputs["publishing"]["published"] == []
    assert any("No content management system" in lim for lim in outcome.result.limitations)
    assert (await content.get_asset(asset.id)).status == ContentStatus.APPROVED.value


# --- repurposing and updates --------------------------------------------------------
async def test_repurposing_names_the_canonical_source_and_skips_outlines(
    harness: AgentHarness,
) -> None:
    content, asset, _ = await _prose_asset(harness)
    await harness.run("CNT-009", {"asset_ids": [str(asset.id)]})

    outline_brief = await content.save_brief(harness.brand_id, _brief(title="An outline only"))
    writer = await harness.run("CNT-004", {"brief_ids": [str(outline_brief.id)]})
    outline_id = writer.result.outputs["content_writer"]["drafts"][0]["asset_id"]

    outcome = await harness.run(
        "CNT-008",
        {"asset_ids": [str(asset.id), outline_id], "platforms": ["linkedin", "email", "nope"]},
    )
    result = outcome.result.outputs["content_repurposing"]
    assert {i["platform"] for i in result["items"]} == {"linkedin", "email"}
    assert all(i["canonical_source_url"] == asset.url for i in result["items"])
    assert all(i["status"] == "draft" for i in result["items"])
    assert [s["asset_id"] for s in result["skipped"]] == [outline_id]


async def test_live_page_updates_in_a_regulated_category_require_approval(
    harness: AgentHarness,
) -> None:
    await harness.crawl()
    await harness.research_keywords()
    gap = await harness.run("SEO-006", {"max_clusters": 25})
    gaps = gap.result.outputs["content_gaps"]
    assert any(g["decision"] == "update" for g in gaps), "the demo site has pages to update"

    outcome = await harness.run("CNT-006", {"content_gaps": gaps})
    update = outcome.result.outputs["content_update"]
    assert update["pages_planned"] + len(update["skipped"]) > 0
    if update["pages_planned"]:
        assert outcome.result.requires_approval is True
        assert all(r.risk is RiskLevel.HIGH for r in outcome.result.recommendations)
        assert all(
            r.proposed_action and r.proposed_action["action_type"] == "content.update"
            for r in outcome.result.recommendations
        )
