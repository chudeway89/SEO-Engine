"""API surface tests.

These run the real ASGI application end to end through httpx: real middleware,
real auth, the real response envelope, the real domain services and the real
database. Nothing in the request path is mocked.

The app opens its own sessions (one per request, committed on success), so these
tests do not use the rolled-back ``session`` fixture; they register real tenants
through the API and the assertions read them back the same way.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from seo_engine.api.main import create_app

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        yield http


async def _register(client: httpx.AsyncClient, *, label: str | None = None) -> dict:
    label = label or uuid.uuid4().hex[:8]
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"owner-{label}@example.com",
            "password": "a-strong-password-123",
            "name": "Owner",
            "organisation_name": f"{label} Ltd",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- envelope and health ----------------------------------------------------
async def test_health_is_enveloped_and_needs_no_auth(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["request_id"].startswith("req_")
    assert response.headers["x-request-id"] == body["request_id"]


async def test_readiness_reports_the_database(client: httpx.AsyncClient) -> None:
    body = (await client.get("/readyz")).json()
    assert body["data"]["checks"]["database"] == "ok"


async def test_every_response_carries_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


# --- authentication ---------------------------------------------------------
async def test_registration_issues_a_working_token(client: httpx.AsyncClient) -> None:
    data = (await _register(client))["data"]
    assert data["tokens"]["access_token"]
    me = await client.get("/api/v1/auth/me", headers=_auth(data["tokens"]["access_token"]))
    assert me.status_code == 200
    assert me.json()["data"]["role"] == "owner"
    assert "brand.write" in me.json()["data"]["permissions"]


async def test_protected_routes_reject_a_missing_token(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/brands/{uuid.uuid4()}")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["request_id"]


async def test_a_garbage_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=_auth("not-a-real-token"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_round_trips(client: httpx.AsyncClient) -> None:
    label = uuid.uuid4().hex[:8]
    await _register(client, label=label)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": f"owner-{label}@example.com", "password": "a-strong-password-123"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["tokens"]["access_token"]


# --- brand CRUD through the envelope ----------------------------------------
async def test_brand_lifecycle(client: httpx.AsyncClient) -> None:
    token = (await _register(client))["data"]["tokens"]["access_token"]
    headers = _auth(token)

    created = await client.post(
        "/api/v1/brands",
        headers=headers,
        json={"name": "Acme Diagnostics", "industry": "diagnostics", "risk_category": "health"},
    )
    assert created.status_code == 201, created.text
    brand = created.json()["data"]
    assert brand["risk_category"] == "health"

    listing = await client.get("/api/v1/brands", headers=headers)
    assert listing.json()["meta"]["total"] == 1

    fetched = await client.get(f"/api/v1/brands/{brand['id']}", headers=headers)
    assert fetched.json()["data"]["name"] == "Acme Diagnostics"

    profile = await client.get(f"/api/v1/brands/{brand['id']}/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["data"]["brand"]["id"] == brand["id"]


async def test_validation_error_is_enveloped(client: httpx.AsyncClient) -> None:
    token = (await _register(client))["data"]["tokens"]["access_token"]
    response = await client.post("/api/v1/brands", headers=_auth(token), json={"name": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["fields"]


# --- tenant isolation across the HTTP boundary ------------------------------
async def test_one_tenant_cannot_read_another_tenants_brand(client: httpx.AsyncClient) -> None:
    alice = (await _register(client))["data"]["tokens"]["access_token"]
    bob = (await _register(client))["data"]["tokens"]["access_token"]

    created = await client.post("/api/v1/brands", headers=_auth(alice), json={"name": "Alice Co"})
    brand_id = created.json()["data"]["id"]

    # Bob, fully authenticated in his own tenant, must not see Alice's brand.
    response = await client.get(f"/api/v1/brands/{brand_id}", headers=_auth(bob))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

    # And Bob's brand list is his own, not Alice's.
    listing = await client.get("/api/v1/brands", headers=_auth(bob))
    assert listing.json()["meta"]["total"] == 0


# --- the mission surface ----------------------------------------------------
async def test_a_mission_plans_over_http(client: httpx.AsyncClient) -> None:
    token = (await _register(client))["data"]["tokens"]["access_token"]
    headers = _auth(token)
    brand_id = (await client.post("/api/v1/brands", headers=headers, json={"name": "Acme"})).json()[
        "data"
    ]["id"]
    await client.post(
        f"/api/v1/brands/{brand_id}/services",
        headers=headers,
        json={"name": "DNA testing", "keywords": ["dna testing"]},
    )

    planned = await client.post(
        f"/api/v1/brands/{brand_id}/missions",
        headers=headers,
        json={"objective": "Increase qualified organic leads"},
    )
    assert planned.status_code == 201, planned.text
    data = planned.json()["data"]
    assert data["plan"]["mission_type"] == "qualified_leads"
    # Stages the brand cannot support are excluded with a reason, not hidden.
    excluded = [s for s in data["plan"]["stages"] if not s["included"]]
    assert any(s["reason"] for s in excluded)


# --- agent registry ---------------------------------------------------------
async def test_agents_are_listed_with_their_contract(client: httpx.AsyncClient) -> None:
    token = (await _register(client))["data"]["tokens"]["access_token"]
    response = await client.get("/api/v1/agents", headers=_auth(token))
    assert response.status_code == 200
    agents = response.json()["data"]
    assert len(agents) == 36, "every MVP agent is registered"
    for agent in agents:
        assert agent["capabilities"], f"{agent['id']} must declare capabilities"
        assert "risk_level" in agent


async def test_openapi_documents_the_contract(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["info"]["title"] == "SEO Engine API"
    assert "/api/v1/brands" in spec["paths"]
    assert "/api/v1/missions/{mission_id}" in spec["paths"]
    assert "/api/v1/content/{asset_id}/approve" in spec["paths"]
    assert "/api/v1/brands/{brand_id}/strategy" in spec["paths"]


# --- strategy and content -----------------------------------------------------
async def _brand(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/v1/brands", headers=headers, json={"name": "Acme"})
    return response.json()["data"]["id"]


async def test_the_strategy_preview_runs_the_orchestrator_and_creates_no_mission(
    client: httpx.AsyncClient,
) -> None:
    headers = _auth((await _register(client))["data"]["tokens"]["access_token"])
    brand_id = await _brand(client, headers)

    response = await client.post(
        f"/api/v1/brands/{brand_id}/strategy",
        headers=headers,
        json={"objective": "Increase qualified organic leads"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["strategy"]["mission_type"] == "qualified_leads"
    assert data["next_tasks"], "the plan is delegated as next tasks"
    assert any(r["type"] == "integration.connect" for r in data["recommendations"])

    missions = await client.get(f"/api/v1/brands/{brand_id}/missions", headers=headers)
    assert missions.json()["data"] == [], "a preview is not a mission"
    runs = await client.get(
        f"/api/v1/agents/runs?brand_id={brand_id}&agent_id=ORCH-001", headers=headers
    )
    assert [r["id"] for r in runs.json()["data"]] == [data["agent_run_id"]]


async def test_content_cannot_be_approved_before_it_passes_the_gate(
    client: httpx.AsyncClient,
) -> None:
    from seo_engine.domain.services import ContentService
    from seo_engine.permissions.rbac import Principal
    from seo_engine.schemas.content import ContentDraft
    from seo_engine.schemas.enums import Role
    from seo_engine.shared.db import session_scope

    headers = _auth((await _register(client))["data"]["tokens"]["access_token"])
    brand_id = await _brand(client, headers)
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()["data"]

    principal = Principal.build(
        user_id=uuid.UUID(me["user_id"]),
        tenant_id=uuid.UUID(me["tenant"]["id"]),
        email=me["email"],
        role=Role.OWNER,
    )
    async with session_scope() as session:
        content = ContentService(session, principal)
        asset = await content.create_asset(uuid.UUID(brand_id), title="Draft", slug="draft")
        await content.add_version(
            asset,
            ContentDraft(title="Draft", meta_description="", slug="draft", body_markdown="Body"),
            change_summary="v1",
        )
        asset_id = str(asset.id)

    listed = await client.get(f"/api/v1/brands/{brand_id}/content", headers=headers)
    assert [a["id"] for a in listed.json()["data"]] == [asset_id]
    detail = (await client.get(f"/api/v1/content/{asset_id}", headers=headers)).json()["data"]
    assert detail["asset"]["status"] == "draft" and len(detail["versions"]) == 1

    refused = await client.post(f"/api/v1/content/{asset_id}/approve", headers=headers, json={})
    assert refused.status_code == 409
    assert "quality gate" in refused.json()["error"]["message"]


# --- the human writing path -------------------------------------------------
HUMAN_PROSE = (
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


async def _principal(client: httpx.AsyncClient, headers: dict[str, str]):
    from seo_engine.permissions.rbac import Principal
    from seo_engine.schemas.enums import Role

    me = (await client.get("/api/v1/auth/me", headers=headers)).json()["data"]
    return Principal.build(
        user_id=uuid.UUID(me["user_id"]),
        tenant_id=uuid.UUID(me["tenant"]["id"]),
        email=me["email"],
        role=Role.OWNER,
    )


async def test_a_person_writes_reviews_approves_and_publishes_an_outlined_piece(
    client: httpx.AsyncClient,
) -> None:
    """No model is configured, so the writer leaves an outline. A person writes
    the piece over HTTP; the agents review that exact version; a person approves
    it; publication waits for the action approval a health brand requires."""
    from datetime import UTC, datetime

    from seo_engine.domain.seed.demo import build_demo_brand
    from seo_engine.domain.services import ContentService
    from seo_engine.engines.content.generation import OUTLINE_NOTICE, generate_draft
    from seo_engine.schemas.content import ContentBrief
    from seo_engine.schemas.enums import RiskCategory, SourceTier
    from seo_engine.schemas.evidence import SourceReference
    from seo_engine.shared.db import session_scope
    from seo_engine.shared.llm import DeterministicProvider, ModelGateway

    headers = _auth((await _register(client))["data"]["tokens"]["access_token"])
    principal = await _principal(client, headers)
    async with session_scope() as session:
        scenario = await build_demo_brand(session, principal)
        content = ContentService(session, principal)
        brief = ContentBrief(
            title="How much does a DNA test cost?",
            primary_topic="dna test cost",
            primary_keyword="dna test cost",
            audience="Expectant parents",
            business_goal="Qualified enquiries",
            unique_value_proposition="Accredited pricing explained plainly",
            required_sections=["What affects the price"],
            prohibited_claims=["Our tests are 100% accurate."],
            approved_claims=["Our laboratory is UKAS accredited for DNA testing."],
            risk_category=RiskCategory.HEALTH,
            target_word_count=120,
            cta="Book a test",
        )
        record = await content.save_brief(scenario.brand.id, brief)
        outline = await generate_draft(brief, gateway=ModelGateway(DeterministicProvider()))
        asset = await content.create_asset(
            scenario.brand.id,
            title=outline.title,
            slug=outline.slug,
            url=f"https://acme.test/guides/{outline.slug}",
            risk_category=RiskCategory.HEALTH,
            primary_keyword="dna test cost",
        )
        await content.add_version(asset, outline, change_summary="outline", brief_id=record.id)
        await content.link_brief_to_asset(record.id, asset.id)
        # The register entry RES-006 records once it has fetched a source (its
        # fetch-to-verify path is tested with the agent).
        await content.add_sources(
            scenario.brand.id,
            [
                SourceReference(
                    url="https://www.ukas.com/accreditation/",
                    title="UKAS accreditation",
                    retrieved_at=datetime.now(UTC),
                    tier=SourceTier.TIER_2_AUTHORITATIVE,
                    reliability=0.85,
                    verified=True,
                )
            ],
        )
        asset_id = str(asset.id)
        brand_id = str(scenario.brand.id)

    # The outline is reviewed and blocked: it is not the piece.
    review = await client.post(f"/api/v1/content/{asset_id}/review", headers=headers)
    assert review.status_code == 200, review.text
    data = review.json()["data"]
    assert [r["agent_id"] for r in data["runs"]] == ["CNT-007", "CNT-009", "POL-001"]
    gate = data["runs"][1]["output"]["results"][0]
    assert any("outline" in b for b in gate["blocking"])
    assert data["asset"]["status"] == "draft"

    # Submitting the outline unchanged is refused; it is not human prose.
    laundered = await client.post(
        f"/api/v1/content/{asset_id}/versions",
        headers=headers,
        json={"title": "T", "body_markdown": f"{OUTLINE_NOTICE}\n\nbody"},
    )
    assert laundered.status_code == 422

    piece = {
        "title": "How much does a DNA test cost?",
        "meta_description": "What a DNA test costs, what changes the price, and how to choose.",
        "body_markdown": (
            "# How much does a DNA test cost?\n\n## What affects the price\n\n" + HUMAN_PROSE
        ),
        # No explicit sections: the body's own headings are the structure.
        "change_summary": "Wrote the piece over the outline",
    }
    # A source outside the register cannot be cited into the piece.
    unregistered = await client.post(
        f"/api/v1/content/{asset_id}/versions",
        headers=headers,
        json={**piece, "cited_source_urls": ["https://made-up.example/study"]},
    )
    assert unregistered.status_code == 422
    assert unregistered.json()["error"]["details"]["unregistered"] == [
        "https://made-up.example/study"
    ]

    register = (await client.get(f"/api/v1/brands/{brand_id}/sources", headers=headers)).json()
    assert [s["verified"] for s in register["data"]] == [True]
    written = await client.post(
        f"/api/v1/content/{asset_id}/versions",
        headers=headers,
        json={**piece, "cited_source_urls": [register["data"][0]["url"]]},
    )
    assert written.status_code == 201, written.text
    version = written.json()["data"]["version"]
    assert version["version"] == 2 and version["synthesis_mode"] == "human"
    assert version["created_by_user"] == str(principal.user_id)
    assert version["created_by_agent"] is None

    review = (await client.post(f"/api/v1/content/{asset_id}/review", headers=headers)).json()
    runs = {r["agent_id"]: r for r in review["data"]["runs"]}
    evaluation = runs["CNT-007"]["output"]["evaluations"][0]
    assert evaluation["version_id"] == version["id"], "the review is of the version just written"
    gate = runs["CNT-009"]["output"]["results"][0]
    assert gate["blocking"] == [], gate
    assert review["data"]["asset"]["status"] == "in_review", review["data"]
    detail = (await client.get(f"/api/v1/content/{asset_id}", headers=headers)).json()["data"]
    quality = next(
        e
        for e in detail["current_version_evaluations"]
        if e["evaluation_type"] == "quality_evaluation"
    )
    completeness = next(c for c in quality["criteria"] if c["criterion"] == "completeness")
    assert completeness["passed"], "the written headings count as the brief's sections"

    approved = await client.post(
        f"/api/v1/content/{asset_id}/approve", headers=headers, json={"note": "clinically checked"}
    )
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "approved"

    # A health brand: the publish action waits for a person.
    first = (await client.post(f"/api/v1/content/{asset_id}/publish", headers=headers)).json()
    waiting = first["data"]["run"]["output"]["awaiting_action_approval"]
    assert len(waiting) == 1 and first["data"]["asset"]["status"] == "approved"
    action = await client.post(
        f"/api/v1/actions/{waiting[0]['action_id']}/approve", headers=headers, json={}
    )
    assert action.status_code == 200, action.text

    second = (await client.post(f"/api/v1/content/{asset_id}/publish", headers=headers)).json()
    assert len(second["data"]["run"]["output"]["published"]) == 1
    assert second["data"]["asset"]["status"] == "published"
    assert any("development" in lim.lower() for lim in second["data"]["run"]["limitations"]), (
        "the development CMS says nothing reached a real website"
    )

    # A published piece takes no new version directly; it goes back to draft first.
    refused = await client.post(f"/api/v1/content/{asset_id}/versions", headers=headers, json=piece)
    assert refused.status_code == 409
    reopened = await client.post(
        f"/api/v1/content/{asset_id}/return-to-draft", headers=headers, json={"note": "update"}
    )
    assert reopened.status_code == 200 and reopened.json()["data"]["status"] == "draft"


async def test_a_new_version_needs_a_fresh_review_before_approval(
    client: httpx.AsyncClient,
) -> None:
    from seo_engine.domain.services import ContentService
    from seo_engine.domain.services.content import EVALUATION_GATE
    from seo_engine.schemas.content import ContentDraft, ContentEvaluation
    from seo_engine.shared.db import session_scope

    headers = _auth((await _register(client))["data"]["tokens"]["access_token"])
    principal = await _principal(client, headers)
    brand_id = await _brand(client, headers)
    async with session_scope() as session:
        content = ContentService(session, principal, acting_as_agent=True)
        asset = await content.create_asset(uuid.UUID(brand_id), title="T", slug="t")
        v1 = await content.add_version(
            asset,
            ContentDraft(title="T", meta_description="", slug="t", body_markdown="Body"),
            change_summary="v1",
        )
        await content.record_evaluation(
            asset.id,
            ContentEvaluation(overall_score=80, passed=True),
            version_id=v1.id,
            evaluation_type=EVALUATION_GATE,
        )
        asset_id = str(asset.id)

    # A person rewrites it; the asset goes back to draft and v1's pass no
    # longer counts for the text now current.
    rewritten = await client.post(
        f"/api/v1/content/{asset_id}/versions",
        headers=headers,
        json={"title": "T", "body_markdown": "A different body"},
    )
    assert rewritten.status_code == 201
    async with session_scope() as session:
        from seo_engine.schemas.enums import ContentStatus

        await ContentService(session, principal, acting_as_agent=True).set_status(
            uuid.UUID(asset_id), ContentStatus.IN_REVIEW, reason="forced for the test"
        )
    refused = await client.post(f"/api/v1/content/{asset_id}/approve", headers=headers, json={})
    assert refused.status_code == 409
    assert "current version" in refused.json()["error"]["message"]


async def test_an_integration_can_be_disconnected(client: httpx.AsyncClient) -> None:
    headers = _auth((await _register(client))["data"]["tokens"]["access_token"])
    brand_id = await _brand(client, headers)
    connected = await client.post(
        f"/api/v1/brands/{brand_id}/integrations", headers=headers, json={"provider": "generic_cms"}
    )
    assert connected.json()["data"]["status"] == "connected"

    revoked = await client.delete(
        f"/api/v1/brands/{brand_id}/integrations/generic_cms", headers=headers
    )
    assert revoked.status_code == 200 and revoked.json()["data"]["status"] == "revoked"
    listing = (await client.get(f"/api/v1/brands/{brand_id}/integrations", headers=headers)).json()
    assert [c["status"] for c in listing["data"]] == ["revoked"]

    missing = await client.delete(
        f"/api/v1/brands/{brand_id}/integrations/wordpress", headers=headers
    )
    assert missing.status_code == 404
