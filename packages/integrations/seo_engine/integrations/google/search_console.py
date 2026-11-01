"""Google Search Console adapters.

``GoogleSearchConsoleAdapter`` calls the real Search Console API v3.
``DevelopmentSearchConsoleAdapter`` produces structurally identical payloads so
the pipeline can be exercised without credentials — every one of them carries
the synthetic-data notice and is stored with ``provenance=synthetic_demo``.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

import httpx
from seo_engine.integrations.base import (
    Capability,
    HealthStatus,
    ProviderResponse,
    SearchConsoleAdapter,
)
from seo_engine.integrations.google.oauth import OAuthTokens, refresh_access_token
from seo_engine.observability.logging import get_logger
from seo_engine.schemas.enums import IntegrationMode, IntegrationStatus
from seo_engine.shared.errors import CredentialError, IntegrationError

log = get_logger(__name__)

API_BASE = "https://www.googleapis.com/webmasters/v3"
SEARCH_ANALYTICS_MAX_ROWS = 25_000


class GoogleSearchConsoleAdapter(SearchConsoleAdapter):
    """Production adapter for the real API."""

    mode = IntegrationMode.PRODUCTION

    def __init__(
        self,
        tokens: OAuthTokens,
        *,
        client: httpx.AsyncClient | None = None,
        on_token_refresh: Any = None,
    ) -> None:
        self.tokens = tokens
        self._client = client
        self._owns_client = client is None
        self._on_token_refresh = on_token_refresh

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _authorised(self) -> dict[str, str]:
        if self.tokens.is_expired:
            self.tokens = await refresh_access_token(self.tokens, client=await self._http())
            if self._on_token_refresh:
                await self._on_token_refresh(self.tokens)
        return {"Authorization": f"Bearer {self.tokens.access_token}"}

    async def _request(
        self, method: str, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> tuple[dict[str, Any], int]:
        client = await self._http()
        response = await client.request(
            method,
            f"{API_BASE}{path}",
            headers=await self._authorised(),
            params=params,
            json=json,
        )
        if response.status_code in {401, 403}:
            raise CredentialError(
                "Search Console rejected the credentials for this request",
                {"status": response.status_code, "path": path},
            )
        if response.status_code >= 400:
            raise IntegrationError(
                "Search Console returned an error",
                {"status": response.status_code, "body": response.text[:500]},
            )
        return response.json(), response.status_code

    # -- lifecycle ---------------------------------------------------------
    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        try:
            payload, _ = await self._request("GET", "/sites")
        except CredentialError as exc:
            return HealthStatus(
                healthy=False,
                status=IntegrationStatus.EXPIRED,
                mode=self.mode,
                detail=exc.message,
            )
        except IntegrationError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.ERROR, mode=self.mode, detail=exc.message
            )
        return HealthStatus(
            healthy=True,
            status=IntegrationStatus.CONNECTED,
            mode=self.mode,
            detail=f"{len(payload.get('siteEntry', []))} property/properties available",
            checked_scopes=self.tokens.scopes,
        )

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("performance", "Query clicks, impressions, CTR and position"),
            Capability("url_inspection", "Inspect indexing status for a URL"),
            Capability("sitemaps", "Read submitted sitemaps and their status"),
        ]

    async def disconnect(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- data --------------------------------------------------------------
    async def list_properties(self) -> ProviderResponse:
        payload, status = await self._request("GET", "/sites")
        return self._response("/sites", {}, payload, status_code=status)

    async def query_performance(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        row_limit: int = 1000,
    ) -> ProviderResponse:
        from urllib.parse import quote

        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": min(row_limit, SEARCH_ANALYTICS_MAX_ROWS),
        }
        path = f"/sites/{quote(site_url, safe='')}/searchAnalytics/query"
        payload, status = await self._request("POST", path, json=body)
        return self._response(path, body, payload, status_code=status)

    async def inspect_url(self, *, site_url: str, page_url: str) -> ProviderResponse:
        # URL inspection lives on a different host from the rest of v3.
        client = await self._http()
        body = {"inspectionUrl": page_url, "siteUrl": site_url}
        response = await client.post(
            "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
            headers=await self._authorised(),
            json=body,
        )
        if response.status_code >= 400:
            raise IntegrationError(
                "URL inspection failed",
                {"status": response.status_code, "body": response.text[:500]},
            )
        return self._response(
            "urlInspection/index:inspect", body, response.json(), status_code=response.status_code
        )

    async def list_sitemaps(self, *, site_url: str) -> ProviderResponse:
        from urllib.parse import quote

        path = f"/sites/{quote(site_url, safe='')}/sitemaps"
        payload, status = await self._request("GET", path)
        return self._response(path, {"site_url": site_url}, payload, status_code=status)


class DevelopmentSearchConsoleAdapter(SearchConsoleAdapter):
    """Offline adapter producing structurally identical, clearly-labelled data.

    Values are derived deterministically from the site URL and query text, so a
    run is reproducible. They are not measurements and every consumer is told
    so: the connection mode, the stored raw response, the normalised row's
    provenance and the payload notice all say ``synthetic``.
    """

    mode = IntegrationMode.DEVELOPMENT_ADAPTER

    def __init__(
        self,
        *,
        site_url: str = "https://demo.seo-engine.local/",
        seed_queries: list[str] | None = None,
    ) -> None:
        self.site_url = site_url
        self.seed_queries = seed_queries or [
            "dna testing lagos",
            "paternity test cost",
            "prenatal screening nigeria",
            "how accurate is a dna test",
            "book a dna test",
            "dna testing near me",
        ]

    def _deterministic(self, *parts: str, low: int, high: int) -> int:
        digest = hashlib.blake2b("|".join(parts).encode(), digest_size=8).digest()
        return low + int.from_bytes(digest, "big") % max(high - low, 1)

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            status=IntegrationStatus.CONNECTED,
            mode=self.mode,
            detail=(
                "Development adapter. No Google credentials are configured, so no real "
                "Search Console data is available."
            ),
        )

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("performance", "Synthetic performance rows", available=True),
            Capability("url_inspection", "Synthetic inspection verdicts", available=True),
            Capability("sitemaps", "Synthetic sitemap listing", available=True),
        ]

    async def disconnect(self) -> None:
        return None

    async def list_properties(self) -> ProviderResponse:
        payload = {
            "siteEntry": [
                {"siteUrl": self.site_url, "permissionLevel": "siteOwner"},
            ]
        }
        return self._response("/sites", {}, payload, status_code=200)

    async def query_performance(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        row_limit: int = 1000,
    ) -> ProviderResponse:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        days = max((end - start).days, 1)

        rows: list[dict[str, Any]] = []
        for index, query in enumerate(self.seed_queries):
            for offset in range(0, days, max(days // 7, 1)):
                day = start + timedelta(days=offset)
                impressions = self._deterministic(query, str(day), low=40, high=2000)
                clicks = max(0, impressions // self._deterministic(query, low=8, high=60))
                position = 3.0 + (self._deterministic(query, str(day), low=0, high=170) / 10.0)

                keys: list[str] = []
                for dimension in dimensions:
                    if dimension == "query":
                        keys.append(query)
                    elif dimension == "page":
                        keys.append(f"{site_url.rstrip('/')}/page-{index + 1}")
                    elif dimension == "date":
                        keys.append(day.isoformat())
                    elif dimension == "country":
                        keys.append("nga")
                    elif dimension == "device":
                        keys.append("MOBILE" if index % 2 else "DESKTOP")
                    else:
                        keys.append("unknown")

                rows.append(
                    {
                        "keys": keys,
                        "clicks": clicks,
                        "impressions": impressions,
                        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
                        "position": round(position, 2),
                    }
                )

        payload = {"rows": rows[:row_limit], "responseAggregationType": "byProperty"}
        params = {
            "site_url": site_url,
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
        }
        return self._response("/searchAnalytics/query", params, payload, status_code=200)

    async def inspect_url(self, *, site_url: str, page_url: str) -> ProviderResponse:
        indexed = self._deterministic(page_url, low=0, high=10) > 2
        payload = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS" if indexed else "NEUTRAL",
                    "coverageState": (
                        "Submitted and indexed" if indexed else "Discovered - currently not indexed"
                    ),
                    "robotsTxtState": "ALLOWED",
                    "indexingState": "INDEXING_ALLOWED",
                    "pageFetchState": "SUCCESSFUL",
                    "googleCanonical": page_url,
                    "userCanonical": page_url,
                }
            }
        }
        return self._response(
            "urlInspection/index:inspect",
            {"site_url": site_url, "page_url": page_url},
            payload,
            status_code=200,
        )

    async def list_sitemaps(self, *, site_url: str) -> ProviderResponse:
        payload = {
            "sitemap": [
                {
                    "path": f"{site_url.rstrip('/')}/sitemap.xml",
                    "isPending": False,
                    "isSitemapsIndex": False,
                    "type": "sitemap",
                    "warnings": "0",
                    "errors": "0",
                    "contents": [{"type": "web", "submitted": "24", "indexed": "20"}],
                }
            ]
        }
        return self._response("/sitemaps", {"site_url": site_url}, payload, status_code=200)


__all__ = [
    "API_BASE",
    "DevelopmentSearchConsoleAdapter",
    "GoogleSearchConsoleAdapter",
]
