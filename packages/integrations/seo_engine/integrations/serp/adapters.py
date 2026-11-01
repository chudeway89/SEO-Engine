"""SERP adapters.

``SerpApiAdapter`` calls a SerpApi-compatible endpoint and returns the observed
results page. ``DevelopmentSERPAdapter`` returns a structurally identical page
built deterministically from the query, so the research pipeline can run with
no key configured. Its domains are ``*.example`` and its payload, the stored raw
response and every normalised row are labelled synthetic: nothing it returns is
an observation of a real results page.

Both feed the same normaliser, :func:`normalise_serp`, so the code that turns a
results page into competitors, questions and features is exercised identically
in both modes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from seo_engine.integrations.base import Capability, HealthStatus, ProviderResponse, SERPAdapter
from seo_engine.schemas.enums import DataProvenance, IntegrationMode, IntegrationStatus
from seo_engine.schemas.search import SERPResultItem, SERPSnapshot
from seo_engine.shared.errors import CredentialError, IntegrationError
from seo_engine.shared.ids import utcnow

#: Raw payload key → the SERP feature it evidences. Presence of the key in an
#: observed page is the evidence; nothing is inferred about how the feature
#: ranks or what it cites.
FEATURE_KEYS: dict[str, str] = {
    "answer_box": "featured_snippet",
    "related_questions": "people_also_ask",
    "local_results": "local_pack",
    "local_map": "local_pack",
    "knowledge_graph": "knowledge_panel",
    "top_stories": "top_stories",
    "shopping_results": "shopping",
    "immersive_products": "shopping",
    "inline_videos": "video",
    "video_results": "video",
    "inline_images": "images",
    "images_results": "images",
    "ads": "paid_ads",
    "ai_overview": "ai_overview",
    "related_searches": "related_searches",
}

#: SerpApi reports an empty page this way, with a 200. It is a result, not a fault.
_NO_RESULTS_MARKER = "hasn't returned any results"


@dataclass(slots=True)
class NormalisedSERP:
    snapshot: SERPSnapshot
    questions: list[str] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def normalise_serp(
    payload: dict[str, Any],
    *,
    query: str,
    provider: str,
    mode: IntegrationMode,
    country: str | None = None,
    device: str = "desktop",
) -> NormalisedSERP:
    """Turn a SerpApi-shaped page into a ``SERPSnapshot`` plus its questions."""
    provenance = (
        DataProvenance.SYNTHETIC_DEMO
        if mode is IntegrationMode.DEVELOPMENT_ADAPTER
        else DataProvenance.OBSERVED
    )

    error = str(payload.get("error") or "")
    if error and _NO_RESULTS_MARKER not in error:
        return NormalisedSERP(
            snapshot=SERPSnapshot(
                query=query,
                country=country,
                device=device,
                observed_at=utcnow(),
                provider=provider,
                provenance=provenance,
                available=False,
                unavailable_reason=error[:500],
            )
        )

    results: list[SERPResultItem] = []
    for item in payload.get("organic_results") or []:
        link = item.get("link")
        if not link:
            continue
        results.append(
            SERPResultItem(
                position=int(item.get("position") or len(results) + 1),
                url=link,
                title=item.get("title"),
                snippet=item.get("snippet"),
                domain=_domain(link),
                result_type="organic",
            )
        )
    for item in payload.get("ads") or []:
        link = item.get("link")
        if not link:
            continue
        results.append(
            SERPResultItem(
                position=int(item.get("position") or 0),
                url=link,
                title=item.get("title"),
                snippet=item.get("description"),
                domain=_domain(link),
                result_type="paid",
            )
        )

    features = sorted({feature for key, feature in FEATURE_KEYS.items() if payload.get(key)})
    questions = [
        str(q["question"]).strip()
        for q in payload.get("related_questions") or []
        if isinstance(q, dict) and q.get("question")
    ]
    related = [
        str(r["query"]).strip()
        for r in payload.get("related_searches") or []
        if isinstance(r, dict) and r.get("query")
    ]

    return NormalisedSERP(
        snapshot=SERPSnapshot(
            query=query,
            country=country,
            device=device,
            observed_at=utcnow(),
            provider=provider,
            provenance=provenance,
            results=results,
            features=features,
            available=True,
        ),
        questions=questions,
        related_searches=related,
    )


class SerpApiAdapter(SERPAdapter):
    """Production adapter for a SerpApi-compatible search endpoint."""

    mode = IntegrationMode.PRODUCTION

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://serpapi.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _get(self, path: str, params: dict[str, Any]) -> tuple[dict[str, Any], int]:
        client = await self._http()
        response = await client.get(
            f"{self.base_url}{path}", params={**params, "api_key": self._api_key}
        )
        if response.status_code in {401, 403}:
            raise CredentialError(
                "the SERP provider rejected the API key",
                {"status": response.status_code, "path": path},
            )
        if response.status_code == 429:
            raise IntegrationError(
                "the SERP provider rate-limited the request",
                {"status": 429, "path": path, "retryable": True},
            )
        if response.status_code >= 400:
            raise IntegrationError(
                "the SERP provider returned an error",
                {"status": response.status_code, "path": path, "body": response.text[:500]},
            )
        return response.json(), response.status_code

    async def connect(self) -> HealthStatus:
        return await self.health_check()

    async def health_check(self) -> HealthStatus:
        try:
            await self._get("/account.json", {})
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
            detail="SERP provider reachable with the configured key.",
        )

    async def capabilities(self) -> list[Capability]:
        return [Capability("search", "Observed organic and paid results for a query")]

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(
        self,
        *,
        query: str,
        country: str | None = None,
        language: str | None = None,
        device: str = "desktop",
        num: int = 10,
    ) -> ProviderResponse:
        # The key is added inside _get and deliberately absent from the params
        # that are stored with the raw response.
        params: dict[str, Any] = {"engine": "google", "q": query, "num": num, "device": device}
        if country:
            params["gl"] = country.lower()
        if language:
            params["hl"] = language.lower()
        payload, status = await self._get("/search.json", params)
        return self._response("search", params, payload, status_code=status)


class DevelopmentSERPAdapter(SERPAdapter):
    """Offline adapter returning a labelled, structurally identical results page.

    Result domains are ``synthetic-result-N.example``: they cannot be mistaken
    for real competitors, and the SERP-driven agents report them as synthetic.
    """

    mode = IntegrationMode.DEVELOPMENT_ADAPTER

    def _number(self, *parts: str, low: int, high: int) -> int:
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
                "Development adapter. No SERP API key is configured, so no real results "
                "pages are available; every page returned is synthetic."
            ),
        )

    async def capabilities(self) -> list[Capability]:
        return [Capability("search", "Synthetic results pages for pipeline testing")]

    async def disconnect(self) -> None:
        return None

    async def search(
        self,
        *,
        query: str,
        country: str | None = None,
        language: str | None = None,
        device: str = "desktop",
        num: int = 10,
    ) -> ProviderResponse:
        q = " ".join(query.lower().split())
        domain_pool = [f"synthetic-result-{i}.example" for i in range(1, 9)]
        organic = []
        for position in range(1, min(num, 8) + 1):
            domain = domain_pool[self._number(q, str(position), low=0, high=len(domain_pool))]
            slug = "-".join(q.split())[:60] or "result"
            organic.append(
                {
                    "position": position,
                    "title": f"{q.title()} — synthetic result {position}",
                    "link": f"https://{domain}/{slug}-{position}",
                    "snippet": "Synthetic development snippet. Not an observed result.",
                }
            )

        payload: dict[str, Any] = {
            "synthetic": True,
            "search_parameters": {"q": query, "device": device, "gl": country, "hl": language},
            "organic_results": organic,
            "related_searches": [
                {"query": f"{q} cost"},
                {"query": f"{q} near me"},
                {"query": f"best {q}"},
            ],
        }
        question_like = q.split(" ", 1)[0] in {"how", "what", "why", "when", "is", "can", "does"}
        if question_like or self._number(q, "paa", low=0, high=3) > 0:
            payload["related_questions"] = [
                {"question": f"What is {q}?"},
                {"question": f"How much does {q} cost?"},
                {"question": f"How long does {q} take?"},
            ]
        if question_like:
            payload["answer_box"] = {"type": "synthetic"}
        if "near me" in q or self._number(q, "local", low=0, high=4) == 0:
            payload["local_results"] = {"places": [{"title": "Synthetic local result"}]}

        params = {"engine": "google", "q": query, "num": num, "device": device}
        return self._response("search", params, payload)


__all__ = [
    "FEATURE_KEYS",
    "DevelopmentSERPAdapter",
    "NormalisedSERP",
    "SerpApiAdapter",
    "normalise_serp",
]
