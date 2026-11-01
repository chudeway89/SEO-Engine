"""Google Analytics 4 adapters (Admin API for discovery, Data API for reports)."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

import httpx
from seo_engine.integrations.base import (
    AnalyticsAdapter,
    Capability,
    HealthStatus,
    ProviderResponse,
)
from seo_engine.integrations.google.oauth import OAuthTokens, refresh_access_token
from seo_engine.schemas.enums import IntegrationMode, IntegrationStatus
from seo_engine.shared.errors import CredentialError, IntegrationError

DATA_API = "https://analyticsdata.googleapis.com/v1beta"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"

#: Event names commonly configured as a qualified lead. Used only to *flag* an
#: event for the user's review — the platform never decides on its own that an
#: event represents a qualified lead.
LIKELY_LEAD_EVENTS = frozenset(
    {
        "generate_lead",
        "qualified_lead",
        "form_submit",
        "contact_form_submit",
        "book_appointment",
        "request_quote",
        "enquiry_submitted",
    }
)


class GoogleAnalyticsAdapter(AnalyticsAdapter):
    """Production adapter for the GA4 Data and Admin APIs."""

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
        self, method: str, url: str, *, json: dict | None = None, params: dict | None = None
    ) -> tuple[dict[str, Any], int]:
        client = await self._http()
        response = await client.request(
            method, url, headers=await self._authorised(), json=json, params=params
        )
        if response.status_code in {401, 403}:
            raise CredentialError(
                "Analytics rejected the credentials for this request",
                {"status": response.status_code},
            )
        if response.status_code >= 400:
            raise IntegrationError(
                "Analytics returned an error",
                {"status": response.status_code, "body": response.text[:500]},
            )
        return response.json(), response.status_code

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        try:
            payload, _ = await self._request("GET", f"{ADMIN_API}/accountSummaries")
        except CredentialError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.EXPIRED, mode=self.mode, detail=exc.message
            )
        except IntegrationError as exc:
            return HealthStatus(
                healthy=False, status=IntegrationStatus.ERROR, mode=self.mode, detail=exc.message
            )
        return HealthStatus(
            healthy=True,
            status=IntegrationStatus.CONNECTED,
            mode=self.mode,
            detail=f"{len(payload.get('accountSummaries', []))} account(s) available",
            checked_scopes=self.tokens.scopes,
        )

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("traffic", "Sessions, users and engagement by landing page"),
            Capability("conversions", "Conversion events and their values"),
            Capability("channels", "Traffic split by default channel group"),
        ]

    async def disconnect(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def list_properties(self) -> ProviderResponse:
        payload, status = await self._request("GET", f"{ADMIN_API}/accountSummaries")
        return self._response("/accountSummaries", {}, payload, status_code=status)

    async def run_report(
        self,
        *,
        property_id: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        metrics: list[str],
        limit: int = 1000,
    ) -> ProviderResponse:
        body = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "dimensions": [{"name": d} for d in dimensions],
            "metrics": [{"name": m} for m in metrics],
            "limit": limit,
        }
        url = f"{DATA_API}/properties/{property_id}:runReport"
        payload, status = await self._request("POST", url, json=body)
        return self._response(
            f"properties/{property_id}:runReport", body, payload, status_code=status
        )

    async def conversion_events(
        self, *, property_id: str, start_date: str, end_date: str
    ) -> ProviderResponse:
        return await self.run_report(
            property_id=property_id,
            start_date=start_date,
            end_date=end_date,
            dimensions=["eventName", "landingPage", "sessionDefaultChannelGroup"],
            metrics=["eventCount", "conversions", "eventValue"],
        )


class DevelopmentAnalyticsAdapter(AnalyticsAdapter):
    """Offline adapter producing structurally identical, clearly-labelled data."""

    mode = IntegrationMode.DEVELOPMENT_ADAPTER

    def __init__(
        self, *, property_id: str = "000000000", landing_pages: list[str] | None = None
    ) -> None:
        self.property_id = property_id
        self.landing_pages = landing_pages or [
            "/",
            "/services/dna-testing",
            "/services/prenatal-screening",
            "/guides/dna-testing",
            "/contact",
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
                "Analytics data is available."
            ),
        )

    async def capabilities(self) -> list[Capability]:
        return [
            Capability("traffic", "Synthetic sessions and engagement"),
            Capability("conversions", "Synthetic conversion events"),
        ]

    async def disconnect(self) -> None:
        return None

    async def list_properties(self) -> ProviderResponse:
        payload = {
            "accountSummaries": [
                {
                    "account": "accounts/000000",
                    "displayName": "SEO Engine demo account",
                    "propertySummaries": [
                        {
                            "property": f"properties/{self.property_id}",
                            "displayName": "Demo property (synthetic)",
                        }
                    ],
                }
            ]
        }
        return self._response("/accountSummaries", {}, payload, status_code=200)

    async def run_report(
        self,
        *,
        property_id: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        metrics: list[str],
        limit: int = 1000,
    ) -> ProviderResponse:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        days = max((end - start).days, 1)

        rows: list[dict[str, Any]] = []
        for page in self.landing_pages:
            for offset in range(0, days, max(days // 7, 1)):
                day = start + timedelta(days=offset)
                sessions = self._deterministic(page, str(day), low=20, high=900)
                users = int(sessions * 0.8)
                engaged = int(sessions * 0.55)
                conversions = max(0, sessions // self._deterministic(page, low=20, high=90))

                values: list[dict[str, str]] = []
                for dimension in dimensions:
                    if dimension == "landingPage":
                        values.append({"value": page})
                    elif dimension == "date":
                        values.append({"value": day.isoformat().replace("-", "")})
                    elif dimension == "sessionDefaultChannelGroup":
                        values.append({"value": "Organic Search"})
                    elif dimension == "eventName":
                        values.append({"value": "generate_lead"})
                    else:
                        values.append({"value": "unknown"})

                metric_values: list[dict[str, str]] = []
                for metric in metrics:
                    lookup = {
                        "sessions": sessions,
                        "totalUsers": users,
                        "newUsers": int(users * 0.6),
                        "engagedSessions": engaged,
                        "engagementRate": round(engaged / sessions, 4) if sessions else 0.0,
                        "averageSessionDuration": 92.5,
                        "conversions": conversions,
                        "totalRevenue": conversions * 120.0,
                        "eventCount": conversions * 2,
                        "eventValue": conversions * 120.0,
                    }
                    metric_values.append({"value": str(lookup.get(metric, 0))})

                rows.append({"dimensionValues": values, "metricValues": metric_values})

        payload = {
            "dimensionHeaders": [{"name": d} for d in dimensions],
            "metricHeaders": [{"name": m} for m in metrics],
            "rows": rows[:limit],
            "rowCount": len(rows[:limit]),
        }
        params = {
            "property_id": property_id,
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "metrics": metrics,
        }
        return self._response(
            f"properties/{property_id}:runReport", params, payload, status_code=200
        )

    async def conversion_events(
        self, *, property_id: str, start_date: str, end_date: str
    ) -> ProviderResponse:
        return await self.run_report(
            property_id=property_id,
            start_date=start_date,
            end_date=end_date,
            dimensions=["eventName", "landingPage", "sessionDefaultChannelGroup"],
            metrics=["eventCount", "conversions", "eventValue"],
        )


__all__ = [
    "ADMIN_API",
    "DATA_API",
    "LIKELY_LEAD_EVENTS",
    "DevelopmentAnalyticsAdapter",
    "GoogleAnalyticsAdapter",
]
