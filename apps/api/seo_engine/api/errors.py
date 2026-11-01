"""Exception handling.

Every error the API returns is a deliberate one. A domain error maps to its
declared code and status; anything unexpected becomes a 500 whose body says only
that something failed, while the full detail goes to the log under the same
request id. Internal messages, stack traces and SQL never reach a client.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from seo_engine.observability.logging import get_logger
from seo_engine.shared.errors import SEOEngineError, TenantIsolationError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = get_logger(__name__)


def _body(code: str, message: str, details: dict, request_id: str) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id,
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SEOEngineError)
    async def _domain_error(request: Request, exc: SEOEngineError) -> JSONResponse:
        # A cross-tenant attempt is a security event, not a routine 403.
        if isinstance(exc, TenantIsolationError):
            log.error(
                "tenant_isolation_violation",
                path=request.url.path,
                request_id=_request_id(request),
                details=exc.details,
            )
        return JSONResponse(
            status_code=exc.http_status,
            content=_body(exc.code, exc.message, exc.details, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_body(
                "VALIDATION_ERROR",
                "the request body or parameters are not valid",
                {
                    "fields": [
                        {
                            "location": list(error.get("loc", [])),
                            "message": error.get("msg", ""),
                            "type": error.get("type", ""),
                        }
                        for error in exc.errors()[:25]
                    ]
                },
                _request_id(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMITED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(
                codes.get(exc.status_code, "HTTP_ERROR"),
                str(exc.detail),
                {},
                _request_id(request),
            ),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception(
            "unhandled_api_error",
            path=request.url.path,
            method=request.method,
            request_id=_request_id(request),
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_body(
                "INTERNAL_ERROR",
                "the request could not be completed",
                {},
                _request_id(request),
            ),
        )


__all__ = ["install_error_handlers"]
