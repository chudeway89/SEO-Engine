"""Identifier helpers.

Primary keys are UUIDv4.  Human-facing references (evidence, recommendations,
actions) additionally carry a short prefixed reference so support and logs can
talk about ``rec_9f3a21`` rather than a full UUID.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def new_ref(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def new_correlation_id() -> str:
    return new_ref("corr")


def new_request_id() -> str:
    return new_ref("req")


def utcnow() -> datetime:
    return datetime.now(UTC)


def coerce_uuid(value: object, *, field: str = "id") -> uuid.UUID:
    from seo_engine.shared.errors import ValidationError

    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:  # pragma: no cover - trivial
        raise ValidationError(f"{field} is not a valid identifier", {field: str(value)}) from exc


__all__ = [
    "coerce_uuid",
    "new_correlation_id",
    "new_id",
    "new_ref",
    "new_request_id",
    "utcnow",
]
