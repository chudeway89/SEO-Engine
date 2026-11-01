"""Applying approved SEO changes to live pages.

The executors are exercised against the development CMS and against an
in-process fake WordPress REST API, so the real lookup, matching and update
requests run. The agent-level tests assert the governance around them: an
action the executing agent's manifest lists as approval-required waits for a
person whatever policy allows; an approved action without a concrete change is
reported and left approved, never guessed at; a settled action is never re-run.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from seo_engine.domain.services import BrandService, IntegrationService
from seo_engine.domain.services.decision import DecisionService
from seo_engine.integrations.cms.adapters import (
    DevelopmentCMSAdapter,
    WebflowAdapter,
    WordPressAdapter,
)
from seo_engine.integrations.cms.changes import (
    ChangeNotSpecified,
    ChangeNotSupported,
    apply_change,
    missing_specification,
)
from seo_engine.schemas.agent import ProposedRecommendation
from seo_engine.schemas.enums import (
    ActionStatus,
    IntegrationMode,
    IntegrationProvider,
    RiskLevel,
)
from seo_engine.shared.errors import IntegrationError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fixtures.agents import AgentHarness

pytestmark = [pytest.mark.integration]


# --- a fake WordPress ----------------------------------------------------------
def _wordpress(pages: dict[int, dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/wp-json/wp/v2")
        if request.method == "GET" and path in {"/pages", "/posts"}:
            kind = path.strip("/")[:-1]
            slug = request.url.params["slug"]
            found = [
                {
                    "id": pid,
                    "link": page["link"],
                    "title": {"raw": page["title"], "rendered": page["title"]},
                    "content": {"raw": page["content"], "rendered": page["content"]},
                }
                for pid, page in pages.items()
                if page["type"] == kind and page["link"].rstrip("/").endswith(f"/{slug}")
            ]
            return httpx.Response(200, json=found)
        if request.method == "POST" and path.startswith(("/pages/", "/posts/")):
            pid = int(path.rsplit("/", 1)[-1])
            pages[pid].update(json.loads(request.content))
            return httpx.Response(200, json={"id": pid, **pages[pid]})
        return httpx.Response(404, json={"code": "rest_no_route"})

    return httpx.MockTransport(handler)


def _wp_adapter(pages: dict[int, dict], client: httpx.AsyncClient) -> WordPressAdapter:
    return WordPressAdapter(
        site_url="https://site.test", username="editor", application_password="pw", client=client
    )


# --- executors -------------------------------------------------------------------
async def test_a_title_change_is_applied_to_the_page_whose_link_matches() -> None:
    pages = {
        1: {
            "type": "page",
            "link": "https://site.test/services/dna",
            "title": "Old",
            "content": "",
        },
        # Same slug elsewhere in the hierarchy: must not be touched.
        2: {"type": "page", "link": "https://site.test/old/dna", "title": "Other", "content": ""},
    }
    async with httpx.AsyncClient(transport=_wordpress(pages)) as client:
        result = await apply_change(
            _wp_adapter(pages, client),
            action_type="seo.metadata_update",
            target={"url": "https://site.test/services/dna/"},
            change={"title": "DNA Testing | Acme"},
        )

    assert pages[1]["title"] == "DNA Testing | Acme"
    assert pages[2]["title"] == "Other"
    assert result.applied[0]["before"] == "Old" and result.mode == "production"
    assert result.notice is None


async def test_internal_links_are_added_once_and_escaped() -> None:
    pages = {
        1: {
            "type": "post",
            "link": "https://site.test/blog/cost",
            "title": "",
            "content": "<p>Body</p>",
        },
        2: {
            "type": "post",
            "link": "https://site.test/blog/time",
            "title": "",
            "content": '<p>See <a href="https://site.test/dna">dna</a></p>',
        },
    }
    async with httpx.AsyncClient(transport=_wordpress(pages)) as client:
        result = await apply_change(
            _wp_adapter(pages, client),
            action_type="seo.internal_link_add",
            target={"url": "https://site.test/dna"},
            change={
                "from_urls": ["https://site.test/blog/cost", "https://site.test/blog/time"],
                "anchor_text": "DNA <testing>",
            },
        )

    assert [a["url"] for a in result.applied] == ["https://site.test/blog/cost"]
    assert 'href="https://site.test/dna">DNA &lt;testing&gt;</a>' in pages[1]["content"]
    assert result.skipped[0]["reason"] == "the page already links to the target"


async def test_a_page_wordpress_does_not_have_is_reported_not_invented() -> None:
    async with httpx.AsyncClient(transport=_wordpress({})) as client:
        with pytest.raises(IntegrationError) as caught:
            await apply_change(
                _wp_adapter({}, client),
                action_type="seo.metadata_update",
                target={"url": "https://site.test/missing"},
                change={"title": "T"},
            )
    assert caught.value.details["not_found"] is True


async def test_unspecified_and_unsupported_changes_are_refused() -> None:
    cms = DevelopmentCMSAdapter()
    assert missing_specification("seo.metadata_update", {"url": "https://a.test/"}, {}) is not None
    with pytest.raises(ChangeNotSpecified):
        await apply_change(cms, action_type="seo.metadata_update", target={"url": "x"}, change={})
    with pytest.raises(ChangeNotSupported):
        await apply_change(cms, action_type="seo.redirect_create", target={}, change={})
    assert "person" in (missing_specification("seo.schema_update", {}, {}) or "")


async def test_the_development_cms_labels_every_change() -> None:
    cms = DevelopmentCMSAdapter()
    result = await apply_change(
        cms,
        action_type="seo.metadata_update",
        target={"url": "https://acme.test/x"},
        change={"title": "New"},
    )
    assert result.mode == IntegrationMode.DEVELOPMENT_ADAPTER.value
    assert result.notice, "development changes carry the synthetic notice"
    assert cms.pages["https://acme.test/x"]["synthetic"] is True


async def test_webflow_refuses_live_page_changes_explicitly() -> None:
    adapter = WebflowAdapter(api_token="t", collection_id="c")
    with pytest.raises(IntegrationError) as caught:
        await adapter.find_page(url="https://site.test/x")
    assert caught.value.details["supported"] is False


# --- the execution agent -----------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _registry() -> None:
    set_registry(AgentRegistry(find_repo_root() / "agents").load(force=True))


@pytest.fixture
async def general_harness(session: AsyncSession, tenant_ctx):
    """A general-category brand, where policy alone would let low-risk changes run."""
    _, _, principal = tenant_ctx
    brand = await BrandService(session, principal).create(name=f"Acme {uuid.uuid4().hex[:6]}")
    await IntegrationService(session, principal).connect(brand.id, IntegrationProvider.GENERIC_CMS)
    return AgentHarness(session, principal, brand.id, None, client=None)


async def _recommend(harness: AgentHarness, *, change: dict | None, title: str) -> None:
    from seo_engine.evidence.collector import EvidenceCollector
    from seo_engine.schemas.enums import EvidenceType

    collector = EvidenceCollector(
        harness.session, harness.principal.tenant_id, brand_id=harness.brand_id
    )
    evidence = collector.observe(
        evidence_type=EvidenceType.CRAWL_RESULT, source="crawler", observation="Title misaligned"
    )
    await collector.persist()
    await DecisionService(harness.session, harness.principal).create_recommendation(
        harness.brand_id,
        ProposedRecommendation(
            type="on_page",
            title=title,
            problem="The title does not carry the keyword",
            opportunity="Clearer relevance",
            reason="Observed on the crawl",
            risk=RiskLevel.LOW,
            confidence=0.7,
            expected_outcome="Higher CTR",
            evidence_ids=[evidence.id],
            proposed_action={
                "action_type": "seo.metadata_update",
                "target": {"url": "https://acme.test/services/dna"},
                "attributes": {"category": "general"},
                "change": change,
            },
        ),
    )


async def test_an_approval_required_action_waits_for_a_person_whatever_policy_allows(
    general_harness: AgentHarness,
) -> None:
    await _recommend(general_harness, change={"title": "DNA Testing | Acme"}, title="Fix title")

    first = await general_harness.run("EXE-001", {})
    plan = first.result.outputs["execution_plan"]
    assert plan["actions_awaiting_approval"] == 1 and plan["actions_executed"] == 0
    assert (
        "declares seo.metadata_update as requiring human approval"
        in (plan["actions"][0]["policy_reason"])
    )

    decisions = DecisionService(general_harness.session, general_harness.principal)
    await decisions.approve_action(uuid.UUID(plan["actions"][0]["id"]), note="approved")
    second = await general_harness.run("EXE-001", {})
    executed = second.result.outputs["execution_plan"]["executed"]
    assert len(executed) == 1 and executed[0]["applied"][0]["after"] == "DNA Testing | Acme"
    assert executed[0]["mode"] == IntegrationMode.DEVELOPMENT_ADAPTER.value
    assert any("Nothing reached a real website" in lim for lim in second.result.limitations)

    # The recommendation is now implemented, so a further run has nothing to
    # plan — and the action is never re-run.
    third = await general_harness.run("EXE-001", {})
    assert "No recommendations" in third.result.summary
    actions = await decisions.list_actions(general_harness.brand_id)
    assert [a.status for a in actions] == [ActionStatus.EXECUTED.value]


async def test_an_approved_action_without_a_concrete_change_is_left_approved(
    general_harness: AgentHarness,
) -> None:
    await _recommend(general_harness, change=None, title="Improve the title")
    first = await general_harness.run("EXE-001", {})
    action_id = first.result.outputs["execution_plan"]["actions"][0]["id"]
    decisions = DecisionService(general_harness.session, general_harness.principal)
    await decisions.approve_action(uuid.UUID(action_id))

    second = await general_harness.run("EXE-001", {})
    plan = second.result.outputs["execution_plan"]
    assert plan["actions_executed"] == 0
    assert "no exact new title" in plan["not_executable"][0]["reason"]
    actions = await decisions.list_actions(general_harness.brand_id)
    assert actions[0].status == ActionStatus.APPROVED.value, "never marked executed or failed"


async def test_no_empty_cms_draft_is_ever_created(general_harness: AgentHarness) -> None:
    from seo_engine.evidence.collector import EvidenceCollector
    from seo_engine.schemas.enums import EvidenceType

    collector = EvidenceCollector(
        general_harness.session,
        general_harness.principal.tenant_id,
        brand_id=general_harness.brand_id,
    )
    evidence = collector.observe(
        evidence_type=EvidenceType.CONTENT, source="gap", observation="Uncovered topic"
    )
    await collector.persist()
    decisions = DecisionService(general_harness.session, general_harness.principal)
    await decisions.create_recommendation(
        general_harness.brand_id,
        ProposedRecommendation(
            type="content_create",
            title="Create: dna test cost",
            problem="No page",
            opportunity="Demand",
            reason="Gap",
            evidence_ids=[evidence.id],
            expected_outcome="A page",
            proposed_action={"action_type": "cms.create_draft", "target": {"url": None}},
        ),
    )
    first = await general_harness.run("EXE-001", {})
    await decisions.approve_action(
        uuid.UUID(first.result.outputs["execution_plan"]["actions"][0]["id"])
    )
    second = await general_harness.run("EXE-001", {})
    assert second.result.outputs["execution_plan"]["actions_executed"] == 0
    assert "never created" in second.result.outputs["execution_plan"]["not_executable"][0]["reason"]
