"""Central application configuration.

Every runtime knob is read here exactly once and exposed as a typed settings
object.  Nothing in the codebase should read ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WorkflowEngineName = Literal["local", "temporal"]
LLMProviderName = Literal["anthropic", "openai", "deterministic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core infrastructure ----------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/seo_engine"
    redis_url: str = "redis://localhost:6379/0"

    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "seo-engine"
    workflow_engine: WorkflowEngineName = "local"

    # --- Security ----------------------------------------------------------
    jwt_secret: str = "insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60
    refresh_token_ttl_days: int = 14
    credential_encryption_key: str | None = None
    secret_provider: Literal["local", "env"] = "local"

    # --- LLM ---------------------------------------------------------------
    llm_provider: LLMProviderName = "deterministic"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_output_tokens: int = 4096
    llm_timeout_seconds: int = 120

    # --- Google ------------------------------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = (
        "http://localhost:8000/api/v1/integrations/oauth/google/callback"
    )
    gsc_scopes: str = "https://www.googleapis.com/auth/webmasters.readonly"
    ga4_scopes: str = "https://www.googleapis.com/auth/analytics.readonly"
    google_ads_developer_token: str | None = None

    # --- Third-party SEO data ---------------------------------------------
    ahrefs_api_key: str | None = None
    semrush_api_key: str | None = None

    # --- Object storage ----------------------------------------------------
    s3_endpoint: str | None = None
    s3_bucket: str = "seo-engine"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    # --- Crawler safeguards ------------------------------------------------
    crawler_user_agent: str = "SEOEngineBot/0.1 (+https://seo-engine.local/bot)"
    crawler_max_pages: int = 200
    crawler_max_depth: int = 4
    crawler_concurrency: int = 4
    crawler_requests_per_second: float = 2.0
    crawler_request_timeout_seconds: float = 20.0
    crawler_respect_robots: bool = True

    # --- Application -------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_cors_origins: str = "http://localhost:3000"
    api_rate_limit_per_minute: int = 240
    repo_root: str | None = None

    @field_validator("api_cors_origins")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def gsc_scope_list(self) -> list[str]:
        return [s.strip() for s in self.gsc_scopes.split(",") if s.strip()]

    @property
    def ga4_scope_list(self) -> list[str]:
        return [s.strip() for s in self.ga4_scopes.split(",") if s.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sync_database_url(self) -> str:
        """Alembic and psql-style tooling use the sync driver."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


_overrides: dict[str, object] = {}


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return Settings(**_overrides)  # type: ignore[arg-type]


def get_settings() -> Settings:
    return _cached_settings()


def override_settings(**values: object) -> None:
    """Test hook: replace settings values and invalidate the cache."""
    _overrides.update(values)
    _cached_settings.cache_clear()


def reset_settings() -> None:
    _overrides.clear()
    _cached_settings.cache_clear()


__all__ = ["Settings", "get_settings", "override_settings", "reset_settings"]
