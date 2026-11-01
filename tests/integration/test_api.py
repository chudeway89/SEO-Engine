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
    assert len(agents) >= 11
    for agent in agents:
        assert agent["capabilities"], f"{agent['id']} must declare capabilities"
        assert "risk_level" in agent


async def test_openapi_documents_the_contract(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["info"]["title"] == "SEO Engine API"
    assert "/api/v1/brands" in spec["paths"]
    assert "/api/v1/missions/{mission_id}" in spec["paths"]
