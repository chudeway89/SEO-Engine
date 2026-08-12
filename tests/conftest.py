"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest
from seo_engine.shared.config import override_settings, reset_settings


@pytest.fixture(scope="session", autouse=True)
def _test_settings() -> None:
    override_settings(
        environment="test",
        jwt_secret="test-secret-not-for-production",
        llm_provider="deterministic",
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/seo_engine",
        ),
    )
    yield
    reset_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
