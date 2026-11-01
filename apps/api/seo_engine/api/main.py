"""The API application.

A thin transport over the domain services. Routes carry no agent logic and no
SQL; they authenticate, authorise, call a service or dispatch work, and wrap the
result in the one response envelope. Everything consequential — tenancy, RBAC,
policies, approvals, audit — lives below this layer and is tested there.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root, set_registry
from seo_engine.api.errors import install_error_handlers
from seo_engine.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from seo_engine.api.routers import (
    agents,
    auth,
    brands,
    content,
    decisions,
    health,
    missions,
    platform,
    search,
    tenants,
    websites,
)
from seo_engine.observability.logging import configure_logging, get_logger
from seo_engine.shared.config import get_settings
from seo_engine.shared.db import dispose_engine

log = get_logger(__name__)

API_DESCRIPTION = """\
SEO Engine — an agentic SEO and digital growth operating system.

Conventions:

* every success is `{"data": ..., "meta": {...}, "request_id": "req_..."}`;
* every failure is `{"error": {"code", "message", "details"}, "request_id"}`;
* authentication is a Bearer token from `/api/v1/auth/login`;
* long work (crawls, missions) returns **202** with identifiers to poll —
  nothing slow runs inside a request;
* metrics carry provenance. A figure the platform could not measure is `null`
  with a stated reason, never an estimate.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    registry = AgentRegistry(find_repo_root() / "agents").load()
    set_registry(registry)
    log.info(
        "api_started",
        environment=settings.environment,
        agents=len(registry.ids()),
        workflow_engine=settings.workflow_engine,
    )
    yield
    await dispose_engine()
    log.info("api_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SEO Engine API",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware runs in reverse registration order: context first, then CORS,
    # then the rate limit — so even rejected requests carry a request id.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["authorization", "content-type"],
    )
    app.add_middleware(RequestContextMiddleware)

    install_error_handlers(app)

    app.include_router(health.router)
    for router in (
        auth.router,
        tenants.router,
        brands.router,
        websites.router,
        search.router,
        missions.router,
        agents.router,
        decisions.router,
        content.router,
        platform.router,
    ):
        app.include_router(router, prefix="/api/v1")

    return app


app = create_app()

__all__ = ["app", "create_app"]
