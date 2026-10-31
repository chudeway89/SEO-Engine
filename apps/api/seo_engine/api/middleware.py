"""HTTP middleware: request ids, access logging, security headers, rate limits.

The rate limiter is a real in-process sliding window keyed by the authenticated
tenant (or the client address before authentication). The platform is a modular
monolith (ADR-0001), so one process owns its own limits; when the API is ever
scaled horizontally the same interface moves to Redis — the middleware is the
seam, not the algorithm.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque

from seo_engine.observability.logging import get_logger, log_context
from seo_engine.shared.config import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = get_logger(__name__)

#: Paths that are never rate limited and never need auth.
EXEMPT_PATHS = {"/healthz", "/readyz", "/api/v1/openapi.json", "/docs", "/redoc"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns the request id, logs the access line, sets security headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = f"req_{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        started = time.perf_counter()

        with log_context(request_id=request_id, path=request.url.path, method=request.method):
            response = await call_next(request)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            principal = getattr(request.state, "principal", None)
            log.info(
                "http_request",
                status=response.status_code,
                latency_ms=elapsed_ms,
                tenant_id=str(principal.tenant_id) if principal else None,
            )

        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers.setdefault("cache-control", "no-store")
        return response


class SlidingWindowLimiter:
    """Timestamps per key within the window; honest, O(events in window)."""

    def __init__(self, limit_per_minute: int, window_seconds: float = 60.0) -> None:
        self.limit = limit_per_minute
        self.window = window_seconds
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str, now: float | None = None) -> tuple[bool, int, float]:
        """Returns (allowed, remaining, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            retry_after = max(0.0, events[0] + self.window - now)
            return False, 0, retry_after
        events.append(now)
        # Opportunistic cleanup so abandoned keys do not accumulate forever.
        if len(self._events) > 10_000:
            for stale in [k for k, v in self._events.items() if not v]:
                del self._events[stale]
        return True, self.limit - len(events), 0.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: SlidingWindowLimiter | None = None) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowLimiter(get_settings().api_rate_limit_per_minute)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # Authentication happens in the route dependencies, after middleware, so
        # the principal is not known yet. Key on the credential itself (hashed —
        # the token must not sit in memory as a dict key), falling back to the
        # client address for anonymous traffic.
        authorization = request.headers.get("authorization")
        if authorization:
            key = "cred:" + hashlib.sha256(authorization.encode()).hexdigest()[:32]
        else:
            client = request.client.host if request.client else "unknown"
            key = f"addr:{client}"

        allowed, remaining, retry_after = self.limiter.check(key)
        if not allowed:
            request_id = getattr(request.state, "request_id", "")
            log.warning("rate_limited", key=key)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "too many requests; slow down and retry",
                        "details": {"retry_after_seconds": round(retry_after, 1)},
                    },
                    "request_id": request_id,
                },
                headers={"retry-after": str(max(1, int(retry_after)))},
            )

        response = await call_next(request)
        response.headers["x-ratelimit-limit"] = str(self.limiter.limit)
        response.headers["x-ratelimit-remaining"] = str(remaining)
        return response


__all__ = [
    "EXEMPT_PATHS",
    "RateLimitMiddleware",
    "RequestContextMiddleware",
    "SlidingWindowLimiter",
]
