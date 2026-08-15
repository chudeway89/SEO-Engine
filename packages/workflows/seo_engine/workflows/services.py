"""The service container handed to an agent run.

Agents never touch the database (Build Specification §6). They receive domain
services, and every one of those services is constructed with the *principal*,
so a service call carries the same tenant and permission checks a user request
would. There is no back door: a service built here cannot read another tenant's
rows even if an agent asked it to.
"""

from __future__ import annotations

from typing import Any

from seo_engine.domain.services import BrandService
from seo_engine.domain.services.decision import DecisionService
from seo_engine.domain.services.integration import IntegrationService
from seo_engine.domain.services.mission import MissionService
from seo_engine.domain.services.search import SearchService
from seo_engine.domain.services.website import WebsiteService
from seo_engine.permissions.rbac import Principal
from sqlalchemy.ext.asyncio import AsyncSession


def build_services(
    session: AsyncSession,
    principal: Principal,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The standard service set available to a mission agent."""
    services: dict[str, Any] = {
        "brands": BrandService(session, principal),
        "websites": WebsiteService(session, principal),
        "search": SearchService(session, principal),
        "decisions": DecisionService(session, principal),
        "integrations": IntegrationService(session, principal),
        "missions": MissionService(session, principal),
    }
    services.update(extra or {})
    return services


__all__ = ["build_services"]
