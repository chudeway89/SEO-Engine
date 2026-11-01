"""Request-scoped dependencies: database session, principal, pagination.

Authentication is the provider abstraction from ``seo_engine.shared.security``;
the API never decodes a token itself. The principal that comes back carries the
tenant, and every repository the services build from it is tenant-scoped, so a
request cannot read across tenants no matter what identifiers it sends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from seo_engine.permissions.rbac import Principal
from seo_engine.shared.db import get_sessionmaker
from seo_engine.shared.errors import AuthenticationError
from seo_engine.shared.security import get_auth_provider
from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One session per request. Commits on success, rolls back on any error."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("authentication required: send a Bearer token", {})
    principal = await get_auth_provider().authenticate(credentials.credentials)
    # Stash for the audit middleware and rate limiter.
    request.state.principal = principal
    return principal


@dataclass(slots=True)
class Page:
    limit: int
    offset: int


def get_page(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> Page:
    return Page(limit=limit, offset=offset)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
PageDep = Annotated[Page, Depends(get_page)]

__all__ = [
    "Page",
    "PageDep",
    "PrincipalDep",
    "SessionDep",
    "get_page",
    "get_principal",
    "get_session",
]
