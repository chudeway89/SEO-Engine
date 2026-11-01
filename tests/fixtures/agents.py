"""A harness for running agents through the real Agent Runtime in tests.

Each call goes through ``AgentRunner`` exactly as a mission stage would —
capabilities, permissions, memory, tools, validation, persistence and events —
with the standard service container. The only substitution is the network: the
crawler reaches the in-process demo site instead of the internet, with the rate
limit lifted so tests stay fast.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from seo_engine.agent_runtime.runner import AgentRunner, RunOutcome, RunRequest
from seo_engine.domain.services.integration import IntegrationService
from seo_engine.engines.crawler.crawler import WebsiteCrawler
from seo_engine.permissions.rbac import Principal
from seo_engine.workflows.services import build_services
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AgentHarness:
    session: AsyncSession
    principal: Principal
    brand_id: uuid.UUID
    website_id: uuid.UUID | None
    client: Any
    extra: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def crawler_factory(self, config: Any) -> WebsiteCrawler:
        return WebsiteCrawler(
            config.model_copy(update={"requests_per_second": 50.0}), client=self.client
        )

    async def run(self, agent_id: str, inputs: dict[str, Any] | None = None) -> RunOutcome:
        payload = {"brand_id": str(self.brand_id)}
        if self.website_id is not None:
            payload["website_id"] = str(self.website_id)
        payload.update(inputs or {})
        connected = await IntegrationService(self.session, self.principal).connected_providers(
            self.brand_id
        )
        outcome = await AgentRunner(self.session).run(
            RunRequest(
                agent_id=agent_id,
                objective=f"test run of {agent_id}",
                principal=self.principal,
                brand_id=self.brand_id,
                inputs=payload,
                services=build_services(
                    self.session,
                    self.principal,
                    extra={"crawler_factory": self.crawler_factory, **self.extra},
                ),
                available_integrations=connected,
                inherited_evidence_refs=list(self.evidence_refs),
            )
        )
        self.evidence_refs += outcome.evidence_refs
        self.outputs[agent_id] = dict(outcome.result.outputs)
        return outcome

    async def crawl(self, *, max_pages: int = 30) -> RunOutcome:
        return await self.run("SEO-001", {"max_pages": max_pages, "max_depth": 3})

    async def research_keywords(self) -> RunOutcome:
        return await self.run("SEO-003", {"max_keywords": 200})


__all__ = ["AgentHarness"]
