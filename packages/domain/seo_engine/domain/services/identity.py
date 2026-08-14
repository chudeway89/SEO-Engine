"""Identity and tenancy service.

Registration, login, membership and role management.  Every method that touches
another user's record checks the caller's rank first, so a role can never be
escalated beyond the caller's own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from seo_engine.domain.models.identity import Tenant, TenantUser, User
from seo_engine.observability.audit import record_audit
from seo_engine.permissions.rbac import P_USER_MANAGE, Principal
from seo_engine.schemas.enums import Role, TenantStatus, UserStatus
from seo_engine.shared.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from seo_engine.shared.ids import utcnow
from seo_engine.shared.security import (
    IssuedTokens,
    decode_token,
    get_auth_provider,
    hash_password,
    verify_password,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "org"


@dataclass(slots=True)
class RegistrationResult:
    user: User
    tenant: Tenant
    membership: TenantUser
    tokens: IssuedTokens


class IdentityService:
    """Owns users, tenants and memberships."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- registration ----------------------------------------------------
    async def register(
        self,
        *,
        email: str,
        password: str,
        name: str,
        organisation_name: str,
    ) -> RegistrationResult:
        """Create a user, their first tenant, and an owner membership."""
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValidationError("a valid email address is required", {"email": email})
        if not name.strip():
            raise ValidationError("name is required", {})

        existing = await self.session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("an account with that email already exists", {"email": email})

        user = User(
            email=email,
            name=name.strip(),
            password_hash=hash_password(password),
            auth_provider="password",
            status=UserStatus.ACTIVE,
        )
        self.session.add(user)

        tenant = Tenant(
            name=organisation_name.strip() or f"{name}'s organisation",
            slug=await self._unique_slug(slugify(organisation_name or name)),
            status=TenantStatus.ACTIVE,
        )
        self.session.add(tenant)
        await self.session.flush()

        membership = TenantUser(
            tenant_id=tenant.id, user_id=user.id, role=Role.OWNER, is_default=True
        )
        self.session.add(membership)
        await self.session.flush()

        tokens = get_auth_provider().issue(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.OWNER.value
        )

        await record_audit(
            self.session,
            tenant_id=tenant.id,
            action="user.register",
            resource_type="user",
            resource_id=str(user.id),
            actor_type="user",
            actor_id=str(user.id),
            actor_label=user.email,
            reason="self-service registration",
            after_state={"email": user.email, "tenant": tenant.slug, "role": Role.OWNER.value},
        )
        return RegistrationResult(user=user, tenant=tenant, membership=membership, tokens=tokens)

    async def _unique_slug(self, base: str) -> str:
        candidate = base
        suffix = 1
        while True:
            found = await self.session.execute(select(Tenant).where(Tenant.slug == candidate))
            if found.scalar_one_or_none() is None:
                return candidate
            suffix += 1
            candidate = f"{base}-{suffix}"

    # -- login -----------------------------------------------------------
    async def login(
        self, *, email: str, password: str, tenant_slug: str | None = None
    ) -> tuple[User, Tenant, IssuedTokens]:
        email = email.strip().lower()
        result = await self.session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        # Always run the verification so a missing user and a wrong password
        # cost the same and cannot be distinguished by timing.
        if not verify_password(password, user.password_hash if user else None):
            raise AuthenticationError("invalid email or password", {})
        assert user is not None

        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError("this account is not active", {"status": user.status})

        membership = await self._resolve_membership(user.id, tenant_slug)
        tenant = await self.session.get(Tenant, membership.tenant_id)
        if tenant is None or tenant.status != TenantStatus.ACTIVE:
            raise AuthenticationError("the organisation is not active", {})

        user.last_login_at = utcnow()
        tokens = get_auth_provider().issue(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=membership.role
        )
        await record_audit(
            self.session,
            tenant_id=tenant.id,
            action="user.login",
            resource_type="user",
            resource_id=str(user.id),
            actor_type="user",
            actor_id=str(user.id),
            actor_label=user.email,
        )
        return user, tenant, tokens

    async def _resolve_membership(self, user_id: uuid.UUID, tenant_slug: str | None) -> TenantUser:
        statement = select(TenantUser).where(TenantUser.user_id == user_id)
        if tenant_slug:
            statement = statement.join(Tenant, Tenant.id == TenantUser.tenant_id).where(
                Tenant.slug == tenant_slug
            )
        else:
            statement = statement.order_by(TenantUser.is_default.desc(), TenantUser.created_at)
        result = await self.session.execute(statement.limit(1))
        membership = result.scalar_one_or_none()
        if membership is None:
            raise AuthenticationError("no organisation membership for this account", {})
        return membership

    async def refresh(self, refresh_token: str) -> IssuedTokens:
        payload = decode_token(refresh_token, expected_type="refresh")
        user = await self.session.get(User, uuid.UUID(payload["sub"]))
        if user is None or user.status != UserStatus.ACTIVE:
            raise AuthenticationError("account is no longer active", {})
        membership = await self._membership(uuid.UUID(payload["tid"]), uuid.UUID(payload["sub"]))
        # The role is re-read rather than trusted from the token, so a
        # revocation takes effect on the next refresh.
        return get_auth_provider().issue(
            user_id=user.id,
            tenant_id=membership.tenant_id,
            email=user.email,
            role=membership.role,
        )

    async def _membership(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> TenantUser:
        result = await self.session.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            raise AuthenticationError("membership has been revoked", {})
        return membership

    # -- membership management -------------------------------------------
    async def list_members(self, principal: Principal) -> list[tuple[TenantUser, User]]:
        result = await self.session.execute(
            select(TenantUser, User)
            .join(User, User.id == TenantUser.user_id)
            .where(TenantUser.tenant_id == principal.tenant_id)
            .order_by(User.email)
        )
        return list(result.all())  # type: ignore[arg-type]

    async def invite_member(
        self, principal: Principal, *, email: str, name: str, role: Role | str
    ) -> TenantUser:
        principal.require(P_USER_MANAGE)
        principal.require_rank_over(role)

        email = email.strip().lower()
        result = await self.session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                name=name.strip() or email,
                status=UserStatus.INVITED,
                auth_provider="password",
            )
            self.session.add(user)
            await self.session.flush()

        existing = await self.session.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == principal.tenant_id, TenantUser.user_id == user.id
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("that user is already a member", {"email": email})

        membership = TenantUser(tenant_id=principal.tenant_id, user_id=user.id, role=Role(role))
        self.session.add(membership)
        await self.session.flush()

        await record_audit(
            self.session,
            tenant_id=principal.tenant_id,
            action="tenant.invite_member",
            resource_type="tenant_user",
            resource_id=str(membership.id),
            actor_id=str(principal.user_id),
            actor_label=principal.email,
            after_state={"email": email, "role": Role(role).value},
        )
        return membership

    async def change_role(
        self, principal: Principal, *, user_id: uuid.UUID, role: Role | str
    ) -> TenantUser:
        principal.require(P_USER_MANAGE)
        principal.require_rank_over(role)

        membership = await self._membership(principal.tenant_id, user_id)
        principal.require_rank_over(membership.role)

        if membership.role == Role.OWNER and Role(role) != Role.OWNER:
            owners = await self.session.execute(
                select(func.count())
                .select_from(TenantUser)
                .where(
                    TenantUser.tenant_id == principal.tenant_id,
                    TenantUser.role == Role.OWNER,
                )
            )
            if int(owners.scalar_one()) <= 1:
                raise ValidationError("a tenant must retain at least one owner", {})

        before = membership.role
        membership.role = Role(role)
        await self.session.flush()

        await record_audit(
            self.session,
            tenant_id=principal.tenant_id,
            action="tenant.change_role",
            resource_type="tenant_user",
            resource_id=str(membership.id),
            actor_id=str(principal.user_id),
            actor_label=principal.email,
            before_state={"role": before},
            after_state={"role": membership.role},
        )
        return membership

    async def get_tenant(self, principal: Principal) -> Tenant:
        tenant = await self.session.get(Tenant, principal.tenant_id)
        if tenant is None:  # pragma: no cover - implies a deleted tenant on a live token
            raise NotFoundError("tenant not found", {})
        return tenant


__all__ = ["IdentityService", "RegistrationResult", "slugify"]
