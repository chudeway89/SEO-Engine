"""Runtime resolvers: permissions, tools, memory and policy.

Each resolver answers one question about a run, and each one fails closed.  The
runner calls them in the order the specification mandates and never lets an
agent reach past them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from seo_engine.memory.service import MemoryService
from seo_engine.observability.logging import get_logger
from seo_engine.permissions.rbac import Principal
from seo_engine.policies.engine import PolicyEngine
from seo_engine.schemas.agent import (
    AgentManifest,
    MemoryContext,
    PermissionContext,
    PolicyContext,
    ToolHandle,
)
from seo_engine.schemas.enums import (
    AutomationPolicy,
    MemoryScope,
    MemoryType,
    PermissionLevel,
    RiskLevel,
)
from seo_engine.shared.errors import CapabilityDeniedError
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
class PermissionResolver:
    """Resolves the effective capability grants for one run.

    An agent's effective permission is the *intersection* of what its manifest
    declares and what the requesting principal holds.  An agent can therefore
    never act beyond the human who triggered it.
    """

    #: capability prefix → the RBAC permission a human needs to authorise it
    CAPABILITY_TO_PERMISSION: dict[str, str] = {
        "website.crawl": "crawl.run",
        "website.read": "website.read",
        "website.render": "crawl.run",
        "seo.audit": "website.read",
        "seo.keyword": "research.run",
        "seo.serp": "research.run",
        "seo.schema": "website.read",
        "seo.search": "research.run",
        "research": "research.run",
        "brand": "brand.read",
        "competitor": "research.run",
        "content.research": "content.read",
        "content.write": "content.draft",
        "content.edit": "content.draft",
        "content.evaluate": "content.read",
        "content.publish": "content.publish",
        "analytics": "analytics.read",
        "cms.read": "content.read",
        "cms.draft": "content.draft",
        "cms.publish": "content.publish",
        "ads": "action.approve",
        "gbp": "action.approve",
        "opportunity": "recommendation.read",
        "recommendation": "recommendation.read",
        "decision": "recommendation.read",
        "policy": "policy.read",
        "execution": "action.execute",
        "memory": "brand.read",
    }

    def resolve(self, manifest: AgentManifest, principal: Principal) -> PermissionContext:
        capabilities: dict[str, PermissionLevel] = {}
        for grant in manifest.permissions:
            required = self._required_permission(grant.capability)
            if required and not principal.has(required):
                # Downgrade rather than fail: a viewer can still run a read-only
                # analysis, they just cannot be granted EXECUTE through an agent.
                capabilities[grant.capability] = PermissionLevel.DENY
                continue
            capabilities[grant.capability] = grant.permission
        return PermissionContext(capabilities=capabilities, roles=[principal.role.value])

    def _required_permission(self, capability: str) -> str | None:
        for prefix, permission in sorted(
            self.CAPABILITY_TO_PERMISSION.items(), key=lambda kv: -len(kv[0])
        ):
            if capability.startswith(prefix):
                return permission
        return None

    def assert_capability(
        self,
        context_permissions: PermissionContext,
        capability: str,
        minimum: PermissionLevel = PermissionLevel.READ,
    ) -> None:
        if not context_permissions.allows(capability, minimum):
            raise CapabilityDeniedError(
                f"capability {capability!r} is not granted at {minimum.value} level",
                {"capability": capability, "required": minimum.value},
            )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    #: The RBAC permission the *human* who triggered the run must hold.  An
    #: agent can never reach a tool its operator could not use directly.
    required_permission: str | None = None
    #: Tools that need a live external connection declare it, so the resolver
    #: can mark them unavailable rather than let an agent invent data.
    requires_integration: str | None = None
    risk: RiskLevel = RiskLevel.LOW


#: The tool registry (Architecture Pack §68).  A tool absent from here cannot be
#: granted, however a manifest is written.
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "crawler": ToolSpec("crawler", "Fetch and parse pages from a website", "crawl.run"),
    "browser": ToolSpec("browser", "Render JavaScript-dependent pages", "crawl.run"),
    "search": ToolSpec("search", "Search the web for research and SERP data", "research.run"),
    "gsc": ToolSpec(
        "gsc",
        "Google Search Console performance, inspection and sitemaps",
        "analytics.read",
        requires_integration="google_search_console",
    ),
    "ga4": ToolSpec(
        "ga4",
        "Google Analytics 4 traffic, engagement and conversions",
        "analytics.read",
        requires_integration="google_analytics_4",
    ),
    "ahrefs": ToolSpec(
        "ahrefs",
        "Ahrefs keyword and backlink data",
        "research.run",
        requires_integration="ahrefs",
    ),
    "semrush": ToolSpec(
        "semrush",
        "Semrush keyword and competitor data",
        "research.run",
        requires_integration="semrush",
    ),
    "cms": ToolSpec("cms", "Create and update CMS drafts", "content.draft", risk=RiskLevel.MEDIUM),
    "llm": ToolSpec("llm", "Language model gateway", None),
    "memory": ToolSpec("memory", "Read and write agent memory", "brand.read"),
    "knowledge_graph": ToolSpec("knowledge_graph", "Entity and relationship graph", "brand.read"),
}


class ToolResolver:
    """Grants an agent exactly the tools its manifest declares — and no more.

    Two independent gates, reported distinctly because they mean different
    things to the user:

    * **denied** — the human who triggered the run lacks the permission, so the
      agent must not have it either;
    * **unavailable** — the tool exists and is permitted, but its integration is
      not connected, so there is genuinely no data. The agent is told to report
      that as a limitation rather than estimate anything (Rule 1, Rule 14).
    """

    def __init__(
        self,
        available_integrations: set[str] | None = None,
        principal: Principal | None = None,
    ) -> None:
        self.available_integrations = available_integrations or set()
        self.principal = principal

    def resolve(
        self, manifest: AgentManifest, permissions: PermissionContext | None = None
    ) -> dict[str, ToolHandle]:
        handles: dict[str, ToolHandle] = {}
        for name in manifest.tools:
            spec = TOOL_REGISTRY.get(name)
            if spec is None:
                log.warning("unknown_tool_requested", agent_id=manifest.id, tool=name)
                handles[name] = ToolHandle(
                    name=name,
                    permission=PermissionLevel.DENY,
                    available=False,
                    unavailable_reason="tool is not in the platform tool registry",
                )
                continue

            # Gate 1: the operator's own permission.
            if (
                spec.required_permission
                and self.principal is not None
                and not self.principal.has(spec.required_permission)
            ):
                handles[name] = ToolHandle(
                    name=name,
                    permission=PermissionLevel.DENY,
                    description=spec.description,
                    available=False,
                    unavailable_reason=(
                        "the requesting user does not hold the required permission "
                        f"({spec.required_permission})"
                    ),
                )
                continue

            # Gate 2: is the backing integration actually connected?
            available = True
            reason: str | None = None
            if (
                spec.requires_integration
                and spec.requires_integration not in self.available_integrations
            ):
                available = False
                reason = (
                    f"{spec.requires_integration} is not connected for this brand; "
                    "no data is available from it"
                )

            handles[name] = ToolHandle(
                name=name,
                permission=(
                    PermissionLevel.EXECUTE if spec.risk != RiskLevel.LOW else PermissionLevel.READ
                ),
                description=spec.description,
                available=available,
                unavailable_reason=reason,
            )
        return handles


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
class MemoryResolver:
    """Loads only the memory scopes an agent's manifest declares."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.service = MemoryService(session, tenant_id)

    async def resolve(
        self,
        manifest: AgentManifest,
        *,
        brand_id: uuid.UUID | None,
        mission_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> MemoryContext:
        scopes = manifest.memory_scopes
        if not scopes:
            return MemoryContext(scopes=[])

        brand_facts = await self.service.retrieve(
            scopes=scopes,
            brand_id=brand_id,
            memory_types=[MemoryType.BRAND_FACT, MemoryType.PREFERENCE],
            limit=limit,
        )
        historical = await self.service.retrieve(
            scopes=scopes,
            brand_id=brand_id,
            memory_types=[MemoryType.HISTORICAL, MemoryType.LEARNING],
            limit=limit,
        )
        outcomes = await self.service.retrieve(
            scopes=scopes,
            brand_id=brand_id,
            memory_types=[MemoryType.OUTCOME],
            limit=limit,
        )

        # A semantic pass surfaces anything topically relevant that the scope
        # filters alone would have missed.
        if query:
            for hit in await self.service.search_semantic(
                query, brand_id=brand_id, scopes=scopes, limit=limit
            ):
                bucket = (
                    brand_facts if hit.memory.memory_type == MemoryType.BRAND_FACT else historical
                )
                if all(m.id != hit.memory.id for m in bucket):
                    bucket.append(hit.memory)

        working: dict[str, Any] = {}
        if MemoryScope.TASK in scopes and task_id is not None:
            for item in await self.service.retrieve(
                scopes=[MemoryScope.TASK], task_id=task_id, limit=limit
            ):
                working[item.key] = item.content

        return MemoryContext(
            brand_facts=[_memory_dict(m) for m in brand_facts],
            historical=[_memory_dict(m) for m in historical],
            outcomes=[_memory_dict(m) for m in outcomes],
            working=working,
            scopes=list(scopes),
        )


def _memory_dict(memory: Any) -> dict[str, Any]:
    return {
        "key": memory.key,
        "content": memory.content,
        "confidence": memory.confidence,
        "source": memory.source,
        "conditions": memory.conditions,
        "structured": memory.structured,
    }


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
class PolicyResolver:
    """Builds the policy context an agent must respect."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.engine = PolicyEngine(session, tenant_id)

    async def resolve(
        self,
        manifest: AgentManifest,
        *,
        brand_id: uuid.UUID | None,
        automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED,
    ) -> PolicyContext:
        policies = await self.engine.policies_for(brand_id)
        rules: list[dict[str, Any]] = []
        for policy in policies:
            for rule in policy.rules or []:
                rules.append({"policy": policy.name, **rule})

        return PolicyContext(
            automation_policy=AutomationPolicy(automation_policy).value,
            risk_threshold=manifest.risk_level,
            approval_required_actions=list(manifest.approval_required_for),
            rules=rules,
        )


__all__ = [
    "TOOL_REGISTRY",
    "MemoryResolver",
    "PermissionResolver",
    "PolicyResolver",
    "ToolResolver",
    "ToolSpec",
]
