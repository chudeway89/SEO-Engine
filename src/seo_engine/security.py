"""Authentication and external-input security primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    pass


class TrustClass(StrEnum):
    SYSTEM = "SYSTEM"
    APPLICATION_POLICY = "APPLICATION_POLICY"
    USER_INPUT = "USER_INPUT"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    UNTRUSTED_EXTERNAL_CONTENT = "UNTRUSTED_EXTERNAL_CONTENT"


@dataclass(frozen=True)
class TrustedContent:
    value: str
    trust_class: TrustClass
    source: str

    @classmethod
    def external(cls, value: str, source: str) -> TrustedContent:
        return cls(value=value, trust_class=TrustClass.UNTRUSTED_EXTERNAL_CONTENT, source=source)

    def as_model_data(self) -> str:
        return (
            f"<{self.trust_class.value} source={json.dumps(self.source)}>\n"
            f"{self.value}\n</{self.trust_class.value}>"
        )


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hash_password(password, salt=base64.urlsafe_b64decode(salt)).split("$", 2)[2]
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def sign_token(claims: dict[str, object], secret: str, ttl_seconds: int = 3600) -> str:
    if len(secret) < 32:
        raise ValueError("token secret must contain at least 32 characters")
    payload = {**claims, "exp": int(time.time()) + ttl_seconds}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_token(token: str, secret: str) -> dict[str, object]:
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("invalid token")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(claims, dict) or int(claims.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired token")
        return claims
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid token") from exc


def validate_public_url(url: str, resolver=socket.getaddrinfo) -> str:
    """Validate scheme, credentials, port and every resolved destination before a fetch."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise UnsafeURLError("only credential-free HTTP(S) URLs are allowed")
    if parsed.port not in {None, 80, 443}:
        raise UnsafeURLError("non-standard ports are not allowed")
    try:
        addresses = {item[4][0] for item in resolver(parsed.hostname, parsed.port or 443)}
    except OSError as exc:
        raise UnsafeURLError("host cannot be resolved") from exc
    if not addresses:
        raise UnsafeURLError("host cannot be resolved")
    for raw in addresses:
        address = ipaddress.ip_address(raw)
        if not address.is_global:
            raise UnsafeURLError("destination is not public")
    return url
