"""Domain error hierarchy.

These map deterministically onto the API error contract:

    {"error": {"code": ..., "message": ..., "details": {}}, "request_id": ...}
"""

from __future__ import annotations

from typing import Any


class SEOEngineError(Exception):
    """Base class for every error the platform raises deliberately."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(SEOEngineError):
    code = "VALIDATION_ERROR"
    http_status = 422


class NotFoundError(SEOEngineError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(SEOEngineError):
    code = "CONFLICT"
    http_status = 409


class AuthenticationError(SEOEngineError):
    code = "UNAUTHENTICATED"
    http_status = 401


class AuthorizationError(SEOEngineError):
    code = "FORBIDDEN"
    http_status = 403


class TenantIsolationError(AuthorizationError):
    """Raised whenever a caller reaches for a resource in another tenant.

    This is deliberately its own type so that security tests can assert on it
    and so that it can be alerted on separately in production.
    """

    code = "TENANT_ISOLATION_VIOLATION"
    http_status = 404  # do not confirm the existence of another tenant's resource


class PermissionDeniedError(AuthorizationError):
    code = "PERMISSION_DENIED"


class CapabilityDeniedError(AuthorizationError):
    """An agent attempted to use a capability or tool it does not declare."""

    code = "CAPABILITY_DENIED"


class PolicyViolationError(SEOEngineError):
    code = "POLICY_VIOLATION"
    http_status = 403


class ApprovalRequiredError(SEOEngineError):
    code = "APPROVAL_REQUIRED"
    http_status = 409


class RateLimitedError(SEOEngineError):
    code = "RATE_LIMITED"
    http_status = 429


class IntegrationError(SEOEngineError):
    code = "INTEGRATION_ERROR"
    http_status = 502


class IntegrationNotConnectedError(IntegrationError):
    code = "INTEGRATION_NOT_CONNECTED"
    http_status = 409


class CredentialError(IntegrationError):
    code = "CREDENTIAL_ERROR"
    http_status = 401


class AgentExecutionError(SEOEngineError):
    code = "AGENT_EXECUTION_ERROR"
    http_status = 500


class AgentNotFoundError(NotFoundError):
    code = "AGENT_NOT_FOUND"


class ResultValidationError(AgentExecutionError):
    code = "AGENT_RESULT_INVALID"


class CrawlError(SEOEngineError):
    code = "CRAWL_ERROR"
    http_status = 502


class ConfigurationError(SEOEngineError):
    """The deployment is configured for something it cannot actually do.

    Raised rather than degrading silently: a caller who configured durable
    orchestration must not be handed best-effort orchestration instead.
    """

    code = "CONFIGURATION_ERROR"
    http_status = 503


class NonRetryableError(SEOEngineError):
    """Marker mixin base: retry helpers must never re-attempt these."""

    code = "NON_RETRYABLE"


NON_RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    ConfigurationError,
    ValidationError,
    AuthenticationError,
    AuthorizationError,
    PermissionDeniedError,
    CapabilityDeniedError,
    TenantIsolationError,
    PolicyViolationError,
    ApprovalRequiredError,
    CredentialError,
    NotFoundError,
    NonRetryableError,
)


__all__ = [
    "NON_RETRYABLE_ERRORS",
    "AgentExecutionError",
    "AgentNotFoundError",
    "ApprovalRequiredError",
    "AuthenticationError",
    "AuthorizationError",
    "CapabilityDeniedError",
    "ConflictError",
    "CrawlError",
    "CredentialError",
    "IntegrationError",
    "IntegrationNotConnectedError",
    "NonRetryableError",
    "NotFoundError",
    "PermissionDeniedError",
    "PolicyViolationError",
    "RateLimitedError",
    "ResultValidationError",
    "SEOEngineError",
    "TenantIsolationError",
    "ValidationError",
]
