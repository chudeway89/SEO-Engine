"""Password hashing, token issuance and the authentication provider abstraction.

JWT is the initial implementation.  Production OAuth/OIDC plugs in behind
:class:`AuthProvider` without any caller changing, because callers only ever see
:class:`~seo_engine.permissions.rbac.Principal`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext
from seo_engine.shared.config import get_settings
from seo_engine.shared.errors import AuthenticationError, ValidationError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]

#: bcrypt truncates at 72 bytes; longer inputs are pre-hashed so that two long
#: passwords sharing a 72-byte prefix are not treated as equal.
_BCRYPT_MAX_BYTES = 72

MIN_PASSWORD_LENGTH = 12


def _prepare(password: str) -> str:
    if len(password.encode()) > _BCRYPT_MAX_BYTES:
        return hashlib.sha256(password.encode()).hexdigest()
    return password


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return _pwd_context.hash(_prepare(password))


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Still spend the work factor so absent users are not distinguishable
        # from wrong passwords by response time.
        _pwd_context.dummy_verify()
        return False
    try:
        return _pwd_context.verify(_prepare(password), password_hash)
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters",
            {"min_length": MIN_PASSWORD_LENGTH},
        )
    if password.lower() in _COMMON_PASSWORDS:
        raise ValidationError("password is too common", {})


_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "123456789012",
        "qwertyuiop12",
        "adminadmin12",
        "letmein12345",
        "welcome12345",
    }
)


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str
    token_type: TokenType
    session_id: str
    expires_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub": str(self.subject),
            "tid": str(self.tenant_id),
            "email": self.email,
            "role": self.role,
            "typ": self.token_type,
            "sid": self.session_id,
            "exp": int(self.expires_at.timestamp()),
            "iat": int(datetime.now(UTC).timestamp()),
            "iss": "seo-engine",
        }


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


def create_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    role: str,
    token_type: TokenType = "access",
    session_id: str | None = None,
    ttl: timedelta | None = None,
) -> str:
    settings = get_settings()
    if ttl is None:
        ttl = (
            timedelta(minutes=settings.access_token_ttl_minutes)
            if token_type == "access"
            else timedelta(days=settings.refresh_token_ttl_days)
        )
    claims = TokenClaims(
        subject=user_id,
        tenant_id=tenant_id,
        email=email,
        role=role,
        token_type=token_type,
        session_id=session_id or secrets.token_urlsafe(16),
        expires_at=datetime.now(UTC) + ttl,
    )
    return jwt.encode(claims.to_dict(), settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="seo-engine",
        )
    except JWTError as exc:
        raise AuthenticationError("invalid or expired token", {"reason": str(exc)}) from exc

    if expected_type and payload.get("typ") != expected_type:
        raise AuthenticationError(
            "token is not valid for this operation",
            {"expected": expected_type, "received": payload.get("typ")},
        )
    for claim in ("sub", "tid", "role", "email"):
        if claim not in payload:
            raise AuthenticationError("token is missing required claims", {"missing": claim})
    return payload


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------
class AuthProvider(ABC):
    """Authentication provider.  JWT now; OAuth/OIDC later, same interface."""

    name: str

    @abstractmethod
    async def authenticate(self, credential: str) -> Principal:  # noqa: F821
        """Turn a bearer credential into a principal, or raise."""

    @abstractmethod
    def issue(
        self, *, user_id: uuid.UUID, tenant_id: uuid.UUID, email: str, role: str
    ) -> IssuedTokens:
        """Mint a token pair for an already-authenticated user."""


class JWTAuthProvider(AuthProvider):
    name = "jwt"

    async def authenticate(self, credential: str) -> Principal:  # noqa: F821
        from seo_engine.permissions.rbac import Principal

        payload = decode_token(credential, expected_type="access")
        return Principal.build(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            email=payload["email"],
            role=payload["role"],
            session_id=payload.get("sid"),
        )

    def issue(
        self, *, user_id: uuid.UUID, tenant_id: uuid.UUID, email: str, role: str
    ) -> IssuedTokens:
        settings = get_settings()
        session_id = secrets.token_urlsafe(16)
        common = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "role": role,
            "session_id": session_id,
        }
        return IssuedTokens(
            access_token=create_token(**common, token_type="access"),  # type: ignore[arg-type]
            refresh_token=create_token(**common, token_type="refresh"),  # type: ignore[arg-type]
            token_type="Bearer",
            expires_in=settings.access_token_ttl_minutes * 60,
        )


_provider: AuthProvider | None = None


def get_auth_provider() -> AuthProvider:
    global _provider
    if _provider is None:
        _provider = JWTAuthProvider()
    return _provider


def set_auth_provider(provider: AuthProvider) -> None:
    global _provider
    _provider = provider


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def constant_time_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def new_idempotency_key(*parts: str) -> str:
    """Deterministic idempotency key so a retry cannot double-apply an action."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return f"idem_{digest[:40]}"


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "AuthProvider",
    "IssuedTokens",
    "JWTAuthProvider",
    "TokenClaims",
    "constant_time_compare",
    "create_token",
    "decode_token",
    "get_auth_provider",
    "hash_password",
    "new_idempotency_key",
    "set_auth_provider",
    "validate_password_strength",
    "verify_password",
]
