"""Role-based access control.

Roles are tenant-scoped and map to explicit permission strings.  ``Principal``
is the authenticated caller as every service sees it; nothing downstream reads
a raw JWT.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from seo_engine.schemas.enums import Role
from seo_engine.shared.errors import PermissionDeniedError, TenantIsolationError

# ---------------------------------------------------------------------------
# Permission catalogue
# ---------------------------------------------------------------------------
P_BRAND_READ = "brand.read"
P_BRAND_WRITE = "brand.write"
P_WEBSITE_READ = "website.read"
P_WEBSITE_WRITE = "website.write"
P_CRAWL_RUN = "crawl.run"
P_RESEARCH_RUN = "research.run"
P_CONTENT_READ = "content.read"
P_CONTENT_DRAFT = "content.draft"
P_CONTENT_PUBLISH = "content.publish"
P_RECOMMENDATION_READ = "recommendation.read"
P_RECOMMENDATION_DECIDE = "recommendation.decide"
P_ACTION_READ = "action.read"
P_ACTION_APPROVE = "action.approve"
P_ACTION_EXECUTE = "action.execute"
P_MISSION_READ = "mission.read"
P_MISSION_WRITE = "mission.write"
P_MISSION_RUN = "mission.run"
P_ANALYTICS_READ = "analytics.read"
P_INTEGRATION_READ = "integration.read"
P_INTEGRATION_CONNECT = "integration.connect"
P_POLICY_READ = "policy.read"
P_POLICY_WRITE = "policy.write"
P_AUDIT_READ = "audit.read"
P_TENANT_MANAGE = "tenant.manage"
P_USER_MANAGE = "user.manage"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        P_BRAND_READ,
        P_BRAND_WRITE,
        P_WEBSITE_READ,
        P_WEBSITE_WRITE,
        P_CRAWL_RUN,
        P_RESEARCH_RUN,
        P_CONTENT_READ,
        P_CONTENT_DRAFT,
        P_CONTENT_PUBLISH,
        P_RECOMMENDATION_READ,
        P_RECOMMENDATION_DECIDE,
        P_ACTION_READ,
        P_ACTION_APPROVE,
        P_ACTION_EXECUTE,
        P_MISSION_READ,
        P_MISSION_WRITE,
        P_MISSION_RUN,
        P_ANALYTICS_READ,
        P_INTEGRATION_READ,
        P_INTEGRATION_CONNECT,
        P_POLICY_READ,
        P_POLICY_WRITE,
        P_AUDIT_READ,
        P_TENANT_MANAGE,
        P_USER_MANAGE,
    }
)

_READ_ONLY: frozenset[str] = frozenset(
    {
        P_BRAND_READ,
        P_WEBSITE_READ,
        P_CONTENT_READ,
        P_RECOMMENDATION_READ,
        P_ACTION_READ,
        P_MISSION_READ,
        P_ANALYTICS_READ,
        P_INTEGRATION_READ,
        P_POLICY_READ,
    }
)

_ANALYST: frozenset[str] = _READ_ONLY | {P_CRAWL_RUN, P_RESEARCH_RUN, P_AUDIT_READ}

_EDITOR: frozenset[str] = _ANALYST | {P_CONTENT_DRAFT, P_MISSION_READ}

_STRATEGIST: frozenset[str] = _EDITOR | {
    P_BRAND_WRITE,
    P_WEBSITE_WRITE,
    P_RECOMMENDATION_DECIDE,
    P_MISSION_WRITE,
    P_MISSION_RUN,
    P_ACTION_APPROVE,
    P_CONTENT_PUBLISH,
}

_ADMIN: frozenset[str] = _STRATEGIST | {
    P_ACTION_EXECUTE,
    P_INTEGRATION_CONNECT,
    P_POLICY_WRITE,
    P_USER_MANAGE,
}

#: Role → permissions.  Deliberately explicit rather than computed, so a
#: privilege change is a visible diff in code review.
ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.VIEWER: _READ_ONLY,
    Role.ANALYST: _ANALYST,
    Role.EDITOR: _EDITOR,
    Role.STRATEGIST: _STRATEGIST,
    Role.ADMIN: _ADMIN,
    Role.OWNER: ALL_PERMISSIONS,
}

ROLE_RANK: dict[Role, int] = {
    Role.OWNER: 0,
    Role.ADMIN: 10,
    Role.STRATEGIST: 20,
    Role.EDITOR: 30,
    Role.ANALYST: 40,
    Role.VIEWER: 50,
}


def permissions_for(role: Role | str) -> frozenset[str]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, as every domain service sees it."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: Role
    permissions: frozenset[str] = field(default_factory=frozenset)
    session_id: str | None = None
    is_service_account: bool = False

    @classmethod
    def build(
        cls,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        email: str,
        role: Role | str,
        session_id: str | None = None,
        is_service_account: bool = False,
    ) -> Principal:
        resolved = Role(role)
        return cls(
            user_id=user_id,
            tenant_id=tenant_id,
            email=email,
            role=resolved,
            permissions=permissions_for(resolved),
            session_id=session_id,
            is_service_account=is_service_account,
        )

    # -- checks ----------------------------------------------------------
    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if not self.has(p)]
        if missing:
            raise PermissionDeniedError(
                "the authenticated user lacks the required permission",
                {"required": sorted(permissions), "missing": missing, "role": self.role.value},
            )

    def require_any(self, *permissions: str) -> None:
        if not any(self.has(p) for p in permissions):
            raise PermissionDeniedError(
                "the authenticated user lacks any of the required permissions",
                {"required_any": sorted(permissions), "role": self.role.value},
            )

    def require_tenant(self, tenant_id: uuid.UUID) -> None:
        """Guard every cross-tenant reference before it reaches the database."""
        if tenant_id != self.tenant_id:
            raise TenantIsolationError(
                "resource does not belong to the authenticated tenant",
                {"principal_tenant": str(self.tenant_id), "requested_tenant": str(tenant_id)},
            )

    def outranks(self, other: Role | str) -> bool:
        return ROLE_RANK[self.role] < ROLE_RANK[Role(other)]

    def require_rank_over(self, other: Role | str) -> None:
        """Stop privilege escalation: nobody may grant a role above their own."""
        target = Role(other)
        if ROLE_RANK[self.role] > ROLE_RANK[target]:
            raise PermissionDeniedError(
                "cannot assign a role higher than your own",
                {"your_role": self.role.value, "target_role": target.value},
            )


__all__ = [
    "ALL_PERMISSIONS",
    "P_ACTION_APPROVE",
    "P_ACTION_EXECUTE",
    "P_ACTION_READ",
    "P_ANALYTICS_READ",
    "P_AUDIT_READ",
    "P_BRAND_READ",
    "P_BRAND_WRITE",
    "P_CONTENT_DRAFT",
    "P_CONTENT_PUBLISH",
    "P_CONTENT_READ",
    "P_CRAWL_RUN",
    "P_INTEGRATION_CONNECT",
    "P_INTEGRATION_READ",
    "P_MISSION_READ",
    "P_MISSION_RUN",
    "P_MISSION_WRITE",
    "P_POLICY_READ",
    "P_POLICY_WRITE",
    "P_RECOMMENDATION_DECIDE",
    "P_RECOMMENDATION_READ",
    "P_RESEARCH_RUN",
    "P_TENANT_MANAGE",
    "P_USER_MANAGE",
    "P_WEBSITE_READ",
    "P_WEBSITE_WRITE",
    "ROLE_PERMISSIONS",
    "ROLE_RANK",
    "Principal",
    "permissions_for",
]
