"""Audit logging.

Rule 6: every consequential action must be auditable.  An audit entry answers
*who, what, when, why, using which evidence, under which policy, with which
tool, and what happened afterwards* (Architecture Pack P6).
"""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.domain.models.observability import AuditLog
from seo_engine.observability.logging import current_log_context, get_logger
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


async def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_type: str = "user",
    actor_id: str | None = None,
    actor_label: str | None = None,
    brand_id: uuid.UUID | None = None,
    outcome: str = "success",
    reason: str = "",
    evidence_refs: list[str] | None = None,
    policy_ref: str | None = None,
    tool: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Write one audit entry.  Never raises into the caller's happy path."""
    context = current_log_context()
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        brand_id=brand_id,
        outcome=outcome,
        reason=reason,
        evidence_refs=evidence_refs or [],
        policy_ref=policy_ref,
        tool=tool,
        request_id=context.get("request_id"),
        correlation_id=context.get("correlation_id"),
        ip_address=ip_address,
        user_agent=user_agent,
        before_state=_safe(before_state),
        after_state=_safe(after_state),
        metadata_json=metadata or {},
    )
    session.add(entry)
    await session.flush()
    log.info(
        "audit",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        actor_id=actor_id,
    )
    return entry


def _safe(state: dict[str, Any] | None) -> dict[str, Any]:
    if not state:
        return {}
    from seo_engine.shared.secrets import redact

    return redact({k: _jsonable(v) for k, v in state.items()})


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


__all__ = ["record_audit"]
