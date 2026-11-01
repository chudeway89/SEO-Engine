"""CMS adapters.

The abstraction is draft-first: creating and updating a draft is a different
operation from publishing, so the ordinary content path can never publish as a
side effect. Publication is always a separate, separately-approved action.

``WordPressAdapter`` and ``WebflowAdapter`` implement the real REST contracts.
``DevelopmentCMSAdapter`` keeps drafts in memory so the full content loop —
brief, draft, evaluation, approval, draft creation, measurement — can be
exercised without a live CMS, and labels everything it returns as synthetic.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
from seo_engine.integrations.base import (
    Capability,
    CMSAdapter,
    HealthStatus,
    ProviderResponse,
)
from seo_engine.schemas.enums import IntegrationMode, IntegrationProvider, IntegrationStatus
from seo_engine.shared.errors import CredentialError, IntegrationError
from seo_engine.shared.ids import new_ref, utcnow


class WordPressAdapter(CMSAdapter):
    """WordPress REST API v2.

    Authenticates with an application password, which is the supported way to
    use the REST API without a plugin. Posts are created with ``status=draft``.
    """

    provider = IntegrationProvider.WORDPRESS
    mode = IntegrationMode.PRODUCTION

    def __init__(
        self,
        *,
        site_url: str,
        username: str,
        application_password: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site_url = site_url.rstrip("/")
        self._auth = base64.b64encode(f"{username}:{application_password}".encode()).decode()
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _request(
        self, method: str, path: str, *, json: dict | None = None
    ) -> tuple[dict[str, Any], int]:
        client = await self._http()
        response = await client.request(
            method,
            f"{self.site_url}/wp-json/wp/v2{path}",
            headers={"Authorization": f"Basic {self._auth}"},
            json=json,
        )
        if response.status_code in {401, 403}:
            raise CredentialError(
                "WordPress rejected the credentials", {"status": response.status_code}
            )
        if response.status_code >= 400:
            raise IntegrationError(
                "WordPress returned an error",
                {"status": response.status_code, "body": response.text[:500]},
            )
        return response.json(), response.status_code

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        try:
            await self._request("GET", "/users/me")
        except CredentialError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.EXPIRED, mode=self.mode, detail=exc.message
            )
        except IntegrationError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.ERROR, mode=self.mode, detail=exc.message
            )
        return HealthStatus(healthy=True, status=IntegrationStatus.CONNECTED, mode=self.mode)

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("cms.draft", "Create and update draft posts"),
            Capability("cms.publish", "Publish an existing draft"),
            Capability("cms.read", "Read existing content"),
        ]

    async def disconnect(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_draft(
        self, *, title: str, body_markdown: str, slug: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        body = {
            "title": title,
            "content": body_markdown,
            "slug": slug,
            "status": "draft",
            "excerpt": metadata.get("meta_description", ""),
        }
        payload, status = await self._request("POST", "/posts", json=body)
        return self._response("/posts", body, payload, status_code=status)

    async def update_draft(
        self, *, external_id: str, title: str, body_markdown: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        body = {
            "title": title,
            "content": body_markdown,
            "excerpt": metadata.get("meta_description", ""),
        }
        payload, status = await self._request("POST", f"/posts/{external_id}", json=body)
        return self._response(f"/posts/{external_id}", body, payload, status_code=status)

    async def publish(self, *, external_id: str) -> ProviderResponse:
        body = {"status": "publish"}
        payload, status = await self._request("POST", f"/posts/{external_id}", json=body)
        return self._response(f"/posts/{external_id}", body, payload, status_code=status)

    async def get_content(self, *, external_id: str) -> ProviderResponse:
        payload, status = await self._request("GET", f"/posts/{external_id}")
        return self._response(f"/posts/{external_id}", {}, payload, status_code=status)


class WebflowAdapter(CMSAdapter):
    """Webflow CMS API v2 (collection items)."""

    provider = IntegrationProvider.WEBFLOW
    mode = IntegrationMode.PRODUCTION

    def __init__(
        self,
        *,
        api_token: str,
        collection_id: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_token = api_token
        self.collection_id = collection_id
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0, base_url="https://api.webflow.com/v2")
        return self._client

    async def _request(
        self, method: str, path: str, *, json: dict | None = None
    ) -> tuple[dict[str, Any], int]:
        client = await self._http()
        response = await client.request(
            method,
            path,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "accept-version": "2.0.0",
            },
            json=json,
        )
        if response.status_code in {401, 403}:
            raise CredentialError("Webflow rejected the token", {"status": response.status_code})
        if response.status_code >= 400:
            raise IntegrationError(
                "Webflow returned an error",
                {"status": response.status_code, "body": response.text[:500]},
            )
        return response.json(), response.status_code

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        try:
            await self._request("GET", f"/collections/{self.collection_id}")
        except CredentialError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.EXPIRED, mode=self.mode, detail=exc.message
            )
        except IntegrationError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.ERROR, mode=self.mode, detail=exc.message
            )
        return HealthStatus(healthy=True, status=IntegrationStatus.CONNECTED, mode=self.mode)

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("cms.draft", "Create and update draft collection items"),
            Capability("cms.publish", "Publish a collection item"),
        ]

    async def disconnect(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_draft(
        self, *, title: str, body_markdown: str, slug: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        body = {
            "isArchived": False,
            "isDraft": True,
            "fieldData": {
                "name": title,
                "slug": slug,
                "post-body": body_markdown,
                "post-summary": metadata.get("meta_description", ""),
            },
        }
        path = f"/collections/{self.collection_id}/items"
        payload, status = await self._request("POST", path, json=body)
        return self._response(path, body, payload, status_code=status)

    async def update_draft(
        self, *, external_id: str, title: str, body_markdown: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        body = {
            "fieldData": {
                "name": title,
                "post-body": body_markdown,
                "post-summary": metadata.get("meta_description", ""),
            }
        }
        path = f"/collections/{self.collection_id}/items/{external_id}"
        payload, status = await self._request("PATCH", path, json=body)
        return self._response(path, body, payload, status_code=status)

    async def publish(self, *, external_id: str) -> ProviderResponse:
        body = {"itemIds": [external_id]}
        path = f"/collections/{self.collection_id}/items/publish"
        payload, status = await self._request("POST", path, json=body)
        return self._response(path, body, payload, status_code=status)

    async def get_content(self, *, external_id: str) -> ProviderResponse:
        path = f"/collections/{self.collection_id}/items/{external_id}"
        payload, status = await self._request("GET", path)
        return self._response(path, {}, payload, status_code=status)


class DevelopmentCMSAdapter(CMSAdapter):
    """In-memory CMS so the content loop runs without a live site."""

    provider = IntegrationProvider.GENERIC_CMS
    mode = IntegrationMode.DEVELOPMENT_ADAPTER

    def __init__(self, *, site_url: str = "https://demo.seo-engine.local") -> None:
        self.site_url = site_url.rstrip("/")
        self.store: dict[str, dict[str, Any]] = {}

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            status=IntegrationStatus.CONNECTED,
            mode=self.mode,
            detail=(
                "Development adapter. Drafts are held in memory; nothing is written to "
                "a real content management system."
            ),
        )

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("cms.draft", "Create and update in-memory drafts"),
            Capability("cms.publish", "Mark an in-memory draft published"),
        ]

    async def disconnect(self) -> None:
        self.store.clear()

    async def create_draft(
        self, *, title: str, body_markdown: str, slug: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        external_id = new_ref("draft")
        record = {
            "id": external_id,
            "title": title,
            "slug": slug,
            "content": body_markdown,
            "status": "draft",
            "link": f"{self.site_url}/{slug}",
            "meta_description": metadata.get("meta_description", ""),
            "created_at": utcnow().isoformat(),
        }
        self.store[external_id] = record
        return self._response(
            "/drafts", {"title": title, "slug": slug}, dict(record), status_code=201
        )

    async def update_draft(
        self, *, external_id: str, title: str, body_markdown: str, metadata: dict[str, Any]
    ) -> ProviderResponse:
        record = self.store.get(external_id)
        if record is None:
            raise IntegrationError("no such draft", {"external_id": external_id})
        record.update(
            {
                "title": title,
                "content": body_markdown,
                "meta_description": metadata.get("meta_description", ""),
                "updated_at": utcnow().isoformat(),
            }
        )
        return self._response(
            f"/drafts/{external_id}", {"title": title}, dict(record), status_code=200
        )

    async def publish(self, *, external_id: str) -> ProviderResponse:
        record = self.store.get(external_id)
        if record is None:
            raise IntegrationError("no such draft", {"external_id": external_id})
        record["status"] = "published"
        record["published_at"] = utcnow().isoformat()
        return self._response(f"/drafts/{external_id}/publish", {}, dict(record), status_code=200)

    async def get_content(self, *, external_id: str) -> ProviderResponse:
        record = self.store.get(external_id)
        if record is None:
            raise IntegrationError("no such draft", {"external_id": external_id})
        return self._response(f"/drafts/{external_id}", {}, dict(record), status_code=200)


__all__ = [
    "DevelopmentCMSAdapter",
    "WebflowAdapter",
    "WordPressAdapter",
]
