"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter, Request
from seo_engine.api.envelope import envelope
from seo_engine.shared.config import get_settings
from seo_engine.shared.db import get_sessionmaker
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    """The process is up. Says nothing about its dependencies."""
    return envelope(
        {"status": "ok", "environment": get_settings().environment},
        request_id=getattr(request.state, "request_id", ""),
    )


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    """The process can serve traffic: the database answers."""
    database = "ok"
    try:
        maker = get_sessionmaker()
        async with maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        database = f"unavailable: {type(exc).__name__}"

    ready = database == "ok"
    return envelope(
        {"status": "ready" if ready else "degraded", "checks": {"database": database}},
        request_id=getattr(request.state, "request_id", ""),
    )
