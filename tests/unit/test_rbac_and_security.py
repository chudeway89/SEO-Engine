"""RBAC, password handling and token contract tests."""

from __future__ import annotations

import itertools
import uuid
from datetime import timedelta

import pytest
from seo_engine.permissions.rbac import (
    ALL_PERMISSIONS,
    P_ACTION_APPROVE,
    P_ACTION_EXECUTE,
    P_BRAND_READ,
    P_BRAND_WRITE,
    P_CONTENT_PUBLISH,
    P_POLICY_WRITE,
    P_USER_MANAGE,
    ROLE_PERMISSIONS,
    Principal,
    permissions_for,
)
from seo_engine.schemas.enums import Role
from seo_engine.shared.errors import (
    AuthenticationError,
    PermissionDeniedError,
    TenantIsolationError,
    ValidationError,
)
from seo_engine.shared.secrets import LocalFernetSecretProvider
from seo_engine.shared.security import (
    create_token,
    decode_token,
    hash_password,
    new_idempotency_key,
    verify_password,
)


def _principal(role: Role, tenant_id: uuid.UUID | None = None) -> Principal:
    return Principal.build(
        user_id=uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        email="user@example.test",
        role=role,
    )


# --- RBAC -------------------------------------------------------------------
def test_owner_holds_every_permission() -> None:
    assert ROLE_PERMISSIONS[Role.OWNER] == ALL_PERMISSIONS


def test_roles_are_monotonically_more_privileged() -> None:
    order = [Role.VIEWER, Role.ANALYST, Role.EDITOR, Role.STRATEGIST, Role.ADMIN, Role.OWNER]
    for lower, higher in itertools.pairwise(order):
        assert permissions_for(lower) <= permissions_for(higher), f"{lower} ⊄ {higher}"


@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (Role.VIEWER, P_BRAND_WRITE),
        (Role.VIEWER, P_ACTION_APPROVE),
        (Role.ANALYST, P_CONTENT_PUBLISH),
        (Role.EDITOR, P_BRAND_WRITE),
        (Role.EDITOR, P_ACTION_APPROVE),
        (Role.STRATEGIST, P_ACTION_EXECUTE),
        (Role.STRATEGIST, P_POLICY_WRITE),
        (Role.STRATEGIST, P_USER_MANAGE),
    ],
)
def test_role_is_denied_permissions_above_its_level(role: Role, permission: str) -> None:
    principal = _principal(role)
    assert not principal.has(permission)
    with pytest.raises(PermissionDeniedError):
        principal.require(permission)


def test_viewer_can_read() -> None:
    _principal(Role.VIEWER).require(P_BRAND_READ)


def test_require_any_accepts_a_single_match() -> None:
    _principal(Role.EDITOR).require_any(P_BRAND_WRITE, P_BRAND_READ)


def test_require_tenant_blocks_a_foreign_tenant() -> None:
    principal = _principal(Role.OWNER)
    principal.require_tenant(principal.tenant_id)
    with pytest.raises(TenantIsolationError):
        principal.require_tenant(uuid.uuid4())


def test_nobody_may_grant_a_role_above_their_own() -> None:
    """Privilege escalation guard."""
    admin = _principal(Role.ADMIN)
    admin.require_rank_over(Role.STRATEGIST)
    with pytest.raises(PermissionDeniedError, match="higher than your own"):
        admin.require_rank_over(Role.OWNER)


def test_a_role_may_grant_its_own_level() -> None:
    _principal(Role.ADMIN).require_rank_over(Role.ADMIN)


# --- Passwords --------------------------------------------------------------
def test_password_round_trip() -> None:
    digest = hash_password("correct horse battery staple")
    assert digest != "correct horse battery staple"
    assert verify_password("correct horse battery staple", digest)
    assert not verify_password("wrong password entirely", digest)


def test_missing_hash_never_verifies() -> None:
    assert verify_password("anything at all", None) is False


def test_short_passwords_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least"):
        hash_password("short")


def test_long_passwords_beyond_bcrypt_limit_stay_distinct() -> None:
    """bcrypt truncates at 72 bytes; pre-hashing keeps long passwords distinct."""
    prefix = "a" * 72
    digest = hash_password(prefix + "ONE")
    assert verify_password(prefix + "ONE", digest)
    assert not verify_password(prefix + "TWO", digest)


# --- Tokens -----------------------------------------------------------------
def _token(**overrides) -> str:
    payload = {
        "user_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "email": "user@example.test",
        "role": Role.EDITOR.value,
    }
    payload.update(overrides)
    return create_token(**payload)


def test_access_token_round_trip() -> None:
    token = _token()
    claims = decode_token(token, expected_type="access")
    assert claims["role"] == Role.EDITOR.value
    assert claims["iss"] == "seo-engine"


def test_refresh_token_is_rejected_where_an_access_token_is_required() -> None:
    token = _token(token_type="refresh")
    with pytest.raises(AuthenticationError, match="not valid for this operation"):
        decode_token(token, expected_type="access")


def test_expired_token_is_rejected() -> None:
    token = _token(ttl=timedelta(seconds=-10))
    with pytest.raises(AuthenticationError):
        decode_token(token)


def test_tampered_token_is_rejected() -> None:
    token = _token()
    head, payload, signature = token.split(".")
    forged = f"{head}.{payload}.{signature[:-4]}AAAA"
    with pytest.raises(AuthenticationError):
        decode_token(forged)


def test_token_signed_with_another_secret_is_rejected() -> None:
    from seo_engine.shared.config import override_settings

    token = _token()
    override_settings(jwt_secret="a-completely-different-secret")
    try:
        with pytest.raises(AuthenticationError):
            decode_token(token)
    finally:
        override_settings(jwt_secret="test-secret-not-for-production")


# --- Secrets ----------------------------------------------------------------
def test_credentials_round_trip_and_are_not_stored_in_clear() -> None:
    provider = LocalFernetSecretProvider()
    ref, material = provider.encrypt({"refresh_token": "super-secret-value"})
    assert material is not None
    assert "super-secret-value" not in material
    assert provider.decrypt(ref, material) == {"refresh_token": "super-secret-value"}


def test_corrupted_credential_material_is_rejected() -> None:
    from seo_engine.shared.errors import CredentialError

    provider = LocalFernetSecretProvider()
    ref, _ = provider.encrypt({"a": "b"})
    with pytest.raises(CredentialError):
        provider.decrypt(ref, "not-a-valid-fernet-token")


def test_idempotency_key_is_deterministic_and_scoped() -> None:
    assert new_idempotency_key("action", "1") == new_idempotency_key("action", "1")
    assert new_idempotency_key("action", "1") != new_idempotency_key("action", "2")


# --- Log redaction ----------------------------------------------------------
def test_secret_shaped_keys_are_redacted() -> None:
    from seo_engine.shared.secrets import redact

    cleaned = redact({"api_key": "sk-live-123", "brand": "Acme", "refresh_token": "x"})
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["refresh_token"] == "[redacted]"
    assert cleaned["brand"] == "Acme"
