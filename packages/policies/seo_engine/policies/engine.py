"""Policy engine.

Policies are evaluated **before** any consequential action, and the decision is
recorded on the action so the audit trail shows which rule applied.

A rule is data, not code:

    {
      "when": {"action": "publish_content", "category": "medical"},
      "require": {"human_approval": true},
      "reason": "medical content requires clinical review"
    }

Matching supports equality, membership (``{"in": [...]}``) and numeric
comparison (``">20"``, ``"<=1000"``), which covers the specification's examples
including the Google Ads budget threshold.

Default posture is deny-by-approval: if nothing matches, a consequential action
still needs approval unless the tenant's automation policy explicitly allows it
and the risk is low.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from seo_engine.domain.models.decision import Policy
from seo_engine.domain.repositories import repository_for
from seo_engine.schemas.enums import (
    HIGH_RISK_CATEGORIES,
    ActionType,
    AutomationPolicy,
    RiskCategory,
    RiskLevel,
)
from sqlalchemy.ext.asyncio import AsyncSession

PolicyRepository = repository_for(Policy)

_COMPARISON = re.compile(r"^(>=|<=|>|<|==|!=)\s*(-?\d+(?:\.\d+)?)$")

RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

#: Approval matrix (Architecture Pack §19).  ``True`` means approval required.
#: Actions absent from this table fall through to the risk threshold check.
APPROVAL_MATRIX: dict[str, dict[RiskLevel, bool | str]] = {
    ActionType.CONTENT_CREATE: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: False,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.METADATA_UPDATE: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: "policy",
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.INTERNAL_LINK_ADD: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: "policy",
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.SCHEMA_UPDATE: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: "policy",
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.CMS_CREATE_DRAFT: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: False,
        RiskLevel.HIGH: "policy",
        RiskLevel.CRITICAL: True,
    },
    ActionType.CMS_PUBLISH: {
        RiskLevel.LOW: "policy",
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.CMS_UPDATE_DRAFT: {
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: False,
        RiskLevel.HIGH: "policy",
        RiskLevel.CRITICAL: True,
    },
    ActionType.REDIRECT_CREATE: {
        RiskLevel.LOW: True,
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.PAGE_DELETE: {
        RiskLevel.LOW: True,
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.ADS_CAMPAIGN_CREATE: {
        RiskLevel.LOW: True,
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
    ActionType.ADS_BUDGET_CHANGE: {
        RiskLevel.LOW: True,
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    },
}


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str
    matched_rules: list[dict[str, Any]] = field(default_factory=list)
    policy_names: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "matched_rules": self.matched_rules,
            "policies": self.policy_names,
            "risk": self.risk.value,
        }


@dataclass(slots=True)
class ActionRequest:
    """Everything the policy engine needs to judge a proposed action."""

    action_type: str
    risk: RiskLevel = RiskLevel.LOW
    category: RiskCategory | str = RiskCategory.GENERAL
    brand_id: uuid.UUID | None = None
    agent_id: str | None = None
    automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED
    attributes: dict[str, Any] = field(default_factory=dict)

    def as_facts(self) -> dict[str, Any]:
        return {
            "action": self.action_type,
            "action_type": self.action_type,
            "risk": RiskLevel(self.risk).value,
            "category": RiskCategory(self.category).value,
            "agent_id": self.agent_id,
            "automation_policy": AutomationPolicy(self.automation_policy).value,
            **self.attributes,
        }


def _matches(condition: Any, fact: Any) -> bool:
    """Match one condition value against one fact."""
    if isinstance(condition, dict):
        if "in" in condition:
            return fact in condition["in"]
        if "not_in" in condition:
            return fact not in condition["not_in"]
        if "any" in condition:
            values = fact if isinstance(fact, list | tuple | set) else [fact]
            return any(v in condition["any"] for v in values)
        return False
    if isinstance(condition, str):
        comparison = _COMPARISON.match(condition.strip())
        if comparison:
            operator, raw = comparison.groups()
            if fact is None:
                return False
            try:
                left, right = float(fact), float(raw)
            except (TypeError, ValueError):
                return False
            return {
                ">": left > right,
                ">=": left >= right,
                "<": left < right,
                "<=": left <= right,
                "==": left == right,
                "!=": left != right,
            }[operator]
    if isinstance(condition, list):
        return fact in condition
    return condition == fact


def rule_matches(rule: dict[str, Any], facts: dict[str, Any]) -> bool:
    when = rule.get("when") or {}
    if not when:
        return False
    return all(_matches(value, facts.get(key)) for key, value in when.items())


class PolicyEngine:
    """Evaluates tenant policies plus the built-in approval matrix."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.repo = PolicyRepository(session, tenant_id)

    async def policies_for(self, brand_id: uuid.UUID | None) -> list[Policy]:
        rows = await self.repo.list(Policy.enabled.is_(True), order_by=Policy.priority)
        return [p for p in rows if p.brand_id is None or p.brand_id == brand_id]

    async def evaluate(self, request: ActionRequest) -> PolicyDecision:
        facts = request.as_facts()
        risk = RiskLevel(request.risk)
        category = RiskCategory(request.category)
        matched: list[dict[str, Any]] = []
        policy_names: list[str] = []

        allowed = True
        requires_approval: bool | None = None
        reasons: list[str] = []

        # 1. Tenant-configured rules, highest priority first.
        for policy in await self.policies_for(request.brand_id):
            for rule in policy.rules or []:
                if not rule_matches(rule, facts):
                    continue
                matched.append({"policy": policy.name, "rule": rule})
                if policy.name not in policy_names:
                    policy_names.append(policy.name)
                require = rule.get("require") or {}
                if require.get("deny"):
                    allowed = False
                    reasons.append(rule.get("reason") or f"blocked by policy {policy.name}")
                if "human_approval" in require:
                    raw = require["human_approval"]
                    if raw == "automation_policy":
                        # The rule defers to the tenant's own automation setting
                        # (the "Policy" cells of the approval matrix).
                        value = _automation_requires_approval(request.automation_policy)
                        reasons.append(
                            f"policy {policy.name} defers to the tenant automation policy "
                            f"({AutomationPolicy(request.automation_policy).value})"
                        )
                    else:
                        value = bool(raw)
                        if value:
                            reasons.append(
                                rule.get("reason")
                                or f"policy {policy.name} requires human approval"
                            )
                    # The most restrictive matching rule wins.
                    requires_approval = (
                        value if requires_approval is None else (requires_approval or value)
                    )

        # 2. High-risk content categories always need a human (§56).
        if category in HIGH_RISK_CATEGORIES and _is_content_action(request.action_type):
            requires_approval = True
            reasons.append(f"{category.value} content requires human approval")

        # 3. The built-in approval matrix.
        if requires_approval is None:
            matrix = APPROVAL_MATRIX.get(request.action_type)
            if matrix is not None:
                verdict = matrix.get(risk, True)
                if verdict == "policy":
                    requires_approval = _automation_requires_approval(request.automation_policy)
                    reasons.append(
                        f"approval determined by the tenant automation policy "
                        f"({AutomationPolicy(request.automation_policy).value})"
                    )
                else:
                    requires_approval = bool(verdict)
                    if requires_approval:
                        reasons.append(
                            f"the approval matrix requires approval for {request.action_type} "
                            f"at {risk.value} risk"
                        )

        # 4. Default posture: anything unrecognised and non-trivial needs a human.
        if requires_approval is None:
            requires_approval = RISK_ORDER[risk] > RISK_ORDER[
                RiskLevel.LOW
            ] or _automation_requires_approval(request.automation_policy)
            reasons.append(
                "no policy matched; defaulting to the safe posture for an "
                f"unrecognised {risk.value}-risk action"
            )

        # 5. Manual automation policy means nothing runs unattended, ever.
        if AutomationPolicy(request.automation_policy) == AutomationPolicy.MANUAL:
            requires_approval = True
            reasons.append("the brand's automation policy is manual")

        return PolicyDecision(
            allowed=allowed,
            requires_approval=bool(requires_approval),
            reason="; ".join(dict.fromkeys(reasons)) or "permitted by policy",
            matched_rules=matched,
            policy_names=policy_names,
            risk=risk,
        )

    async def seed_default_policies(self, *, brand_id: uuid.UUID | None = None) -> list[Policy]:
        """Install the system policies described in the specification."""
        defaults: list[dict[str, Any]] = [
            {
                "name": "publishing-policy",
                "scope": "content",
                "description": "Human review for regulated content categories.",
                "priority": 10,
                "rules": [
                    {
                        "when": {
                            "action": ActionType.CMS_PUBLISH.value,
                            "category": {"in": [c.value for c in HIGH_RISK_CATEGORIES]},
                        },
                        "require": {"human_approval": True},
                        "reason": "regulated content requires qualified human review",
                    },
                    {
                        # Scoped to low risk: a medium- or high-risk publish falls
                        # through to the approval matrix, which requires a human.
                        "when": {
                            "action": ActionType.CMS_PUBLISH.value,
                            "category": RiskCategory.GENERAL.value,
                            "risk": RiskLevel.LOW.value,
                        },
                        "require": {"human_approval": "automation_policy"},
                        "reason": "general low-risk content follows the tenant automation policy",
                    },
                ],
            },
            {
                "name": "paid-media-policy",
                "scope": "google_ads",
                "description": "No autonomous ad spend; thresholds require approval.",
                "priority": 5,
                "rules": [
                    {
                        "when": {
                            "action": ActionType.ADS_BUDGET_CHANGE.value,
                            "increase_percent": ">20",
                        },
                        "require": {"human_approval": True},
                        "reason": "budget increases above 20% require approval",
                    },
                    {
                        "when": {"action": ActionType.ADS_CAMPAIGN_CREATE.value},
                        "require": {"human_approval": True},
                        "reason": "campaign creation always requires approval during the MVP",
                    },
                ],
            },
            {
                "name": "destructive-change-policy",
                "scope": "website",
                "description": "Deletions and redirects always require a human.",
                "priority": 1,
                "rules": [
                    {
                        "when": {"action": ActionType.PAGE_DELETE.value},
                        "require": {"human_approval": True},
                        "reason": "page deletion is not reversible from within the platform",
                    },
                    {
                        "when": {"action": ActionType.REDIRECT_CREATE.value},
                        "require": {"human_approval": True},
                        "reason": "redirects change site architecture",
                    },
                ],
            },
        ]

        created: list[Policy] = []
        for spec in defaults:
            existing = await self.repo.find_one(Policy.name == spec["name"])
            if existing is not None:
                created.append(existing)
                continue
            created.append(
                self.repo.add(
                    Policy(
                        name=spec["name"],
                        scope=spec["scope"],
                        brand_id=brand_id,
                        description=spec["description"],
                        rules=spec["rules"],
                        priority=spec["priority"],
                        is_system=True,
                    )
                )
            )
        await self.session.flush()
        return created


def _is_content_action(action_type: str) -> bool:
    return action_type.startswith("content.") or action_type.startswith("cms.")


def _automation_requires_approval(policy: AutomationPolicy | str) -> bool:
    resolved = AutomationPolicy(policy)
    return resolved in {
        AutomationPolicy.MANUAL,
        AutomationPolicy.APPROVAL_REQUIRED,
        AutomationPolicy.ASSISTED,
    }


__all__ = [
    "APPROVAL_MATRIX",
    "RISK_ORDER",
    "ActionRequest",
    "PolicyDecision",
    "PolicyEngine",
    "rule_matches",
]
