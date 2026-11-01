"""The response envelope.

Every successful response is::

    {"data": ..., "meta": {...}, "request_id": "req_..."}

and every failure is::

    {"error": {"code": ..., "message": ..., "details": {...}}, "request_id": "req_..."}

One shape, always. Clients never have to guess whether a field is at the top
level or nested, and the request id is present on both paths so a user can quote
it and an operator can find the exact run in the logs.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageMeta(BaseModel):
    limit: int
    offset: int
    count: int
    total: int | None = Field(
        default=None,
        description="Absent when counting would cost more than the caller asked for.",
    )
    has_more: bool = False


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    request_id: str = ""


def envelope(data: Any, *, meta: dict[str, Any] | None = None, request_id: str = "") -> dict:
    return {"data": data, "meta": meta or {}, "request_id": request_id}


def page_meta(
    items: list[Any], *, limit: int, offset: int, total: int | None = None
) -> dict[str, Any]:
    return PageMeta(
        limit=limit,
        offset=offset,
        count=len(items),
        total=total,
        has_more=len(items) == limit,
    ).model_dump()


__all__ = [
    "Envelope",
    "ErrorBody",
    "ErrorEnvelope",
    "PageMeta",
    "envelope",
    "page_meta",
]
