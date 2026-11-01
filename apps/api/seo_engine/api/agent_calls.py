"""Running an agent on behalf of an API request.

A route that needs an agent's work runs it through the Agent Runtime exactly as
a mission stage would — the same capability, permission, memory, tool and
result checks, with the same audited run record — never by calling the agent or
its engine directly.
"""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.agent_runtime.runner import AgentRunner, RunOutcome, RunRequest
from seo_engine.domain.services.integration import IntegrationService
from seo_engine.permissions.rbac import Principal
from seo_engine.workflows.services import build_services
from sqlalchemy.ext.asyncio import AsyncSession


async def run_agent(
    session: AsyncSession,
    principal: Principal,
    *,
    agent_id: str,
    brand_id: uuid.UUID,
    objective: str,
    inputs: dict[str, Any] | None = None,
) -> RunOutcome:
    connected = await IntegrationService(session, principal).connected_providers(brand_id)
    return await AgentRunner(session).run(
        RunRequest(
            agent_id=agent_id,
            objective=objective,
            principal=principal,
            brand_id=brand_id,
            inputs={"brand_id": str(brand_id), **(inputs or {})},
            services=build_services(session, principal),
            available_integrations=connected,
        )
    )


def run_summary(outcome: RunOutcome, output_key: str) -> dict[str, Any]:
    """The user-facing part of a run: what it concluded, never how it deliberated."""
    result = outcome.result
    return {
        "agent_id": outcome.run.agent_id,
        "agent_run_id": str(outcome.run.id),
        "status": result.status,
        "summary": result.summary,
        "output": result.outputs.get(output_key, {}),
        "limitations": result.limitations,
    }


__all__ = ["run_agent", "run_summary"]
