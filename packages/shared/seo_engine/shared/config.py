"""Central application configuration.

Every runtime knob is read here exactly once and exposed as a typed settings
object.  Nothing in the codebase should read ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WorkflowEngineName = Literal["local", "temporal"]

#: Alternative spellings of the built-in provider names.
LLM_PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai_compatible",
    "none": "deterministic",
    "": "deterministic",
}


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

    # --- Language model (optional) ----------------------------------------
    # The platform is model-agnostic and runs completely without a model: every
    # analysis, decision and gate is deterministic, and the one stage that
    # benefits from a model (the content writer's prose) degrades to an honest
    # outline. Connecting a model is a choice of protocol, endpoint and model
    # name; nothing in the codebase assumes a particular vendor or model.
    #
    # * ``deterministic`` — no model (the default).
    # * ``openai_compatible`` — any endpoint speaking the Chat Completions
    #   protocol: hosted APIs and local servers alike. ``openai`` is an alias.
    # * ``anthropic`` — any model served through the Anthropic Messages API.
    # * any other name registered with ``seo_engine.shared.llm.register_provider``.
    llm_provider: str = "deterministic"
    llm_api_key: str | None = None
    # No default: the operator names the model they connected.
    llm_model: str | None = None
    # The endpoint. Required for a keyless local server; optional for a hosted
    # API (its public endpoint is used when unset).
    llm_base_url: str | None = None
    llm_max_output_tokens: int = 4096
    llm_timeout_seconds: int = 120
    # Sampling temperature. Unset sends none, so the model's own default applies
    # (some models reject the parameter outright).
    llm_temperature: float | None = None
    # Retries for transient provider failures (timeouts, 429, 5xx).
    llm_max_retries: int = 2
    # Operator-supplied prices, USD per million tokens, for the usage ledger.
    # Unset means the cost of a call is recorded as unknown, never as zero.
    llm_input_price_per_mtok: float | None = None
    llm_output_price_per_mtok: float | None = None

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
    # SERP observations (SerpApi-compatible). Without a key the SERP integration
    # runs its labelled development adapter.
    serp_api_key: str | None = None
    serp_api_base_url: str = "https://serpapi.com"

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
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    api_rate_limit_per_minute: int = 240
    repo_root: str | None = None

    @field_validator("api_cors_origins")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("llm_provider")
    @classmethod
    def _provider_name(cls, value: str) -> str:
        value = (value or "deterministic").strip().lower()
        return LLM_PROVIDER_ALIASES.get(value, value)

    @field_validator("llm_model", "llm_base_url", "llm_api_key")
    @classmethod
    def _blank_is_unset(cls, value: str | None) -> str | None:
        # ``LLM_MODEL=`` in an env file means "not set", not "a model called ''".
        return value.strip() or None if isinstance(value, str) else value

    @field_validator(
        "llm_temperature", "llm_input_price_per_mtok", "llm_output_price_per_mtok", mode="before"
    )
    @classmethod
    def _blank_number_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _model_is_named_when_a_provider_is(self) -> Settings:
        if self.llm_provider != "deterministic" and not self.llm_model:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider} needs LLM_MODEL: name the model you "
                "connected. There is no default model; set LLM_PROVIDER=deterministic to "
                "run without one."
            )
        return self

    def llm_configured(self) -> bool:
        """Whether an operator has connected a language model."""
        return self.llm_provider != "deterministic"

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
