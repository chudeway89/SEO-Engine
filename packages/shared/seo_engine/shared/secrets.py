"""Secret management abstraction.

Provider credentials never sit in ordinary database columns as plaintext.  The
database stores a *reference* plus, for the local provider, a Fernet-encrypted
payload.  A KMS or vault backend implements the same interface and stores only
the reference.
"""

from __future__ import annotations

import base64
import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from seo_engine.shared.config import get_settings
from seo_engine.shared.errors import CredentialError
from seo_engine.shared.ids import new_ref


class SecretProvider(ABC):
    name: str

    @abstractmethod
    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        """Return ``(credential_ref, stored_material)``."""

    @abstractmethod
    def decrypt(self, credential_ref: str, stored_material: str | None) -> dict[str, Any]:
        """Recover the payload."""


class LocalFernetSecretProvider(SecretProvider):
    """Development / single-node default.

    Encrypts with a Fernet key from ``CREDENTIAL_ENCRYPTION_KEY``.  If the key is
    absent the provider refuses to operate in production and derives a key from
    ``JWT_SECRET`` elsewhere, so development works without extra setup but a
    production deployment cannot silently run with a guessable key.
    """

    name = "local"

    def __init__(self, key: str | None = None) -> None:
        settings = get_settings()
        material = key or settings.credential_encryption_key
        if not material:
            if settings.is_production:
                raise CredentialError(
                    "CREDENTIAL_ENCRYPTION_KEY must be set in production",
                    {"provider": self.name},
                )
            material = base64.urlsafe_b64encode(
                hashlib.sha256(settings.jwt_secret.encode()).digest()
            ).decode()
        try:
            self._fernet = Fernet(material)
        except (ValueError, TypeError) as exc:
            raise CredentialError(
                "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key",
                {"hint": "generate with Fernet.generate_key()"},
            ) from exc

    def encrypt(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        blob = self._fernet.encrypt(json.dumps(payload, sort_keys=True).encode()).decode()
        return new_ref("cred"), blob

    def decrypt(self, credential_ref: str, stored_material: str | None) -> dict[str, Any]:
        if not stored_material:
            raise CredentialError(
                "no stored credential material for this reference",
                {"credential_ref": credential_ref},
            )
        try:
            return json.loads(self._fernet.decrypt(stored_material.encode()).decode())
        except (InvalidToken, ValueError) as exc:
            raise CredentialError(
                "stored credential could not be decrypted",
                {"credential_ref": credential_ref},
            ) from exc


_provider: SecretProvider | None = None


def get_secret_provider() -> SecretProvider:
    global _provider
    if _provider is None:
        _provider = LocalFernetSecretProvider()
    return _provider


def set_secret_provider(provider: SecretProvider | None) -> None:
    global _provider
    _provider = provider


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Shape-preserving redaction for logs and API responses."""
    from seo_engine.observability.logging import REDACTED_KEYS

    return {
        key: ("[redacted]" if key.lower() in REDACTED_KEYS else value)
        for key, value in payload.items()
    }


__all__ = [
    "LocalFernetSecretProvider",
    "SecretProvider",
    "get_secret_provider",
    "redact",
    "set_secret_provider",
]
