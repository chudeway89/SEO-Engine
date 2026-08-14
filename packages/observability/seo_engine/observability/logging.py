"""Structured logging with request/correlation context.

Every log line carries whichever of these identifiers are in scope:
``request_id``, ``correlation_id``, ``tenant_id``, ``brand_id``, ``task_id``,
``agent_run_id``, ``workflow_id``.  They are held in context variables so that
code deep in a call stack never has to thread them through by hand.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

import structlog

# Default is None rather than {} so the sentinel can never be mutated in place.
_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "seo_engine_log_context", default=None
)

#: Keys that must never appear in a log line, however they were passed in.
REDACTED_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "llm_api_key",
        "client_secret",
        "jwt_secret",
        "authorization",
        "credential",
        "encrypted_payload",
        "secret",
    }
)

_REDACTED = "[redacted]"


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in REDACTED_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _merge_context(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, value in (_LOG_CONTEXT.get() or {}).items():
        event_dict.setdefault(key, value)
    return event_dict


_configured = False


def configure_logging(level: str = "INFO", *, json_output: bool | None = None) -> None:
    """Configure structlog once per process."""
    global _configured
    if _configured:
        return

    from seo_engine.shared.config import get_settings

    settings = get_settings()
    if json_output is None:
        json_output = settings.environment in {"staging", "production"}

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _merge_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> Any:
    configure_logging()
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------
def bind_log_context(**values: Any) -> Token[dict[str, Any] | None]:
    current = dict(_LOG_CONTEXT.get() or {})
    current.update({k: v for k, v in values.items() if v is not None})
    return _LOG_CONTEXT.set(current)


def reset_log_context(token: Token[dict[str, Any] | None]) -> None:
    _LOG_CONTEXT.reset(token)


def current_log_context() -> dict[str, Any]:
    return dict(_LOG_CONTEXT.get() or {})


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    token = bind_log_context(**values)
    try:
        yield
    finally:
        reset_log_context(token)


__all__ = [
    "REDACTED_KEYS",
    "bind_log_context",
    "configure_logging",
    "current_log_context",
    "get_logger",
    "log_context",
    "reset_log_context",
]
