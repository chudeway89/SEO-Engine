"""API envelope contracts.

Every response is ``{"data": ..., "meta": ..., "request_id": ...}`` and every
error is ``{"error": {...}, "request_id": ...}``.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
    request_id: str


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


__all__ = ["Envelope", "ErrorBody", "ErrorEnvelope", "PageMeta"]
