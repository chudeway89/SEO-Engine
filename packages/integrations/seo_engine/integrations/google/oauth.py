"""Google OAuth 2.0 authorisation-code flow.

Shared by Search Console, Analytics, Ads and Business Profile. Refresh tokens
never touch an ordinary database column — they go through the secret provider,
and only the reference plus encrypted material is stored.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from seo_engine.shared.config import get_settings
from seo_engine.shared.errors import CredentialError, IntegrationError, ValidationError
from seo_engine.shared.ids import utcnow

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


@dataclass(slots=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: Any
    scopes: list[str]
    account_email: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": self.scopes,
            "account_email": self.account_email,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OAuthTokens:
        from datetime import datetime

        expires = payload.get("expires_at")
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=datetime.fromisoformat(expires) if expires else None,
            scopes=payload.get("scopes", []),
            account_email=payload.get("account_email"),
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # Refresh a minute early rather than racing the expiry.
        return utcnow() >= self.expires_at - timedelta(seconds=60)


def build_authorisation_url(*, scopes: list[str], state: str | None = None) -> tuple[str, str]:
    """Return ``(url, state)``.  ``state`` must be echoed back and verified."""
    settings = get_settings()
    if not settings.google_oauth_configured():
        raise ValidationError(
            "Google OAuth is not configured; set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
            {"provider": "google"},
        )
    state = state or secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        # offline + consent is what actually yields a refresh token.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}", state


async def exchange_code(code: str, *, client: httpx.AsyncClient | None = None) -> OAuthTokens:
    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code >= 400:
            raise CredentialError(
                "Google rejected the authorisation code",
                {"status": response.status_code, "body": response.text[:500]},
            )
        data = response.json()
        tokens = OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=utcnow() + timedelta(seconds=int(data.get("expires_in", 3600))),
            scopes=str(data.get("scope", "")).split(),
        )
        tokens.account_email = await _fetch_account_email(client, tokens.access_token)
        return tokens
    finally:
        if owns_client:
            await client.aclose()


async def refresh_access_token(
    tokens: OAuthTokens, *, client: httpx.AsyncClient | None = None
) -> OAuthTokens:
    if not tokens.refresh_token:
        raise CredentialError(
            "no refresh token is stored for this connection; it must be reconnected",
            {},
        )
    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "refresh_token": tokens.refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code >= 400:
            # A revoked grant is not retryable; the user must reconnect.
            raise CredentialError(
                "Google refused to refresh the access token; the grant may have been revoked",
                {"status": response.status_code},
            )
        data = response.json()
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=tokens.refresh_token,
            expires_at=utcnow() + timedelta(seconds=int(data.get("expires_in", 3600))),
            scopes=str(data.get("scope", "")).split() or tokens.scopes,
            account_email=tokens.account_email,
        )
    finally:
        if owns_client:
            await client.aclose()


async def revoke(tokens: OAuthTokens, *, client: httpx.AsyncClient | None = None) -> None:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        await client.post(
            REVOKE_ENDPOINT, data={"token": tokens.refresh_token or tokens.access_token}
        )
    except httpx.HTTPError as exc:  # pragma: no cover - best effort
        raise IntegrationError("failed to revoke the Google token", {"error": str(exc)}) from exc
    finally:
        if owns_client:
            await client.aclose()


async def _fetch_account_email(client: httpx.AsyncClient, access_token: str) -> str | None:
    try:
        response = await client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code == 200:
            return response.json().get("email")
    except httpx.HTTPError:  # pragma: no cover - informational only
        pass
    return None


__all__ = [
    "AUTH_ENDPOINT",
    "TOKEN_ENDPOINT",
    "OAuthTokens",
    "build_authorisation_url",
    "exchange_code",
    "refresh_access_token",
    "revoke",
]
