"""Provider adapter contracts.

Every external platform implements :class:`ProviderAdapter`. Two adapters exist
per provider:

* a **production adapter** that talks to the real API, and
* a **development adapter** used when no credentials are configured.

The development adapter is not a lie dressed as data. It is labelled
``IntegrationMode.DEVELOPMENT_ADAPTER`` on the connection, on every raw response
it stores, on every normalised row it produces (``provenance=synthetic_demo``)
and in the ``notice`` field of every payload it returns. Rule 1 is that the
architecture must be real even when the credentials are absent — not that
absent data may be quietly invented.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from seo_engine.schemas.enums import IntegrationMode, IntegrationProvider, IntegrationStatus

DEVELOPMENT_NOTICE = (
    "SYNTHETIC DEVELOPMENT DATA — this response came from SEO Engine's development "
    "adapter because no credentials are configured for this provider. It is "
    "structurally identical to the real response so the pipeline can be exercised, "
    "but the values are not measurements of anything and must never be presented as "
    "real performance."
)


@dataclass(slots=True)
class HealthStatus:
    healthy: bool
    status: IntegrationStatus
    mode: IntegrationMode
    detail: str = ""
    checked_scopes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "status": self.status.value,
            "mode": self.mode.value,
            "detail": self.detail,
            "scopes": self.checked_scopes,
        }


@dataclass(slots=True)
class Capability:
    name: str
    description: str
    available: bool = True
    reason: str | None = None


@dataclass(slots=True)
class ProviderResponse:
    """A provider payload plus everything needed to store it honestly."""

    endpoint: str
    request_params: dict[str, Any]
    payload: dict[str, Any]
    mode: IntegrationMode
    status_code: int | None = None
    notice: str | None = None

    @property
    def is_synthetic(self) -> bool:
        return self.mode is IntegrationMode.DEVELOPMENT_ADAPTER


class ProviderAdapter(ABC):
    """The interface every integration implements."""

    provider: IntegrationProvider
    mode: IntegrationMode

    @abstractmethod
    async def connect(self) -> HealthStatus: ...

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...

    @abstractmethod
    async def capabilities(self) -> list[Capability]: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    # ------------------------------------------------------------------
    def _response(
        self,
        endpoint: str,
        params: dict[str, Any],
        payload: dict[str, Any],
        *,
        status_code: int | None = None,
    ) -> ProviderResponse:
        return ProviderResponse(
            endpoint=endpoint,
            request_params=params,
            payload=payload,
            mode=self.mode,
            status_code=status_code,
            notice=DEVELOPMENT_NOTICE if self.mode is IntegrationMode.DEVELOPMENT_ADAPTER else None,
        )


class SearchConsoleAdapter(ProviderAdapter):
    """Google Search Console."""

    provider = IntegrationProvider.GOOGLE_SEARCH_CONSOLE

    @abstractmethod
    async def list_properties(self) -> ProviderResponse: ...

    @abstractmethod
    async def query_performance(
        self,
        *,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        row_limit: int = 1000,
    ) -> ProviderResponse: ...

    @abstractmethod
    async def inspect_url(self, *, site_url: str, page_url: str) -> ProviderResponse: ...

    @abstractmethod
    async def list_sitemaps(self, *, site_url: str) -> ProviderResponse: ...


class AnalyticsAdapter(ProviderAdapter):
    """Google Analytics 4."""

    provider = IntegrationProvider.GOOGLE_ANALYTICS_4

    @abstractmethod
    async def list_properties(self) -> ProviderResponse: ...

    @abstractmethod
    async def run_report(
        self,
        *,
        property_id: str,
        start_date: str,
        end_date: str,
        dimensions: list[str],
        metrics: list[str],
        limit: int = 1000,
    ) -> ProviderResponse: ...

    @abstractmethod
    async def conversion_events(
        self, *, property_id: str, start_date: str, end_date: str
    ) -> ProviderResponse: ...


class CMSAdapter(ProviderAdapter):
    """Content management systems.

    Deliberately draft-first: ``create_draft`` and ``update_draft`` are separate
    from ``publish``, so the common path never publishes as a side effect.
    """

    @abstractmethod
    async def create_draft(
        self, *, title: str, body_markdown: str, slug: str, metadata: dict[str, Any]
    ) -> ProviderResponse: ...

    @abstractmethod
    async def update_draft(
        self, *, external_id: str, title: str, body_markdown: str, metadata: dict[str, Any]
    ) -> ProviderResponse: ...

    @abstractmethod
    async def publish(self, *, external_id: str) -> ProviderResponse: ...

    @abstractmethod
    async def get_content(self, *, external_id: str) -> ProviderResponse: ...


__all__ = [
    "DEVELOPMENT_NOTICE",
    "AnalyticsAdapter",
    "CMSAdapter",
    "Capability",
    "HealthStatus",
    "ProviderAdapter",
    "ProviderResponse",
    "SearchConsoleAdapter",
]
