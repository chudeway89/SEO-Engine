"""Agent runtime lifecycle tests.

These assert that the runner enforces the mandated lifecycle and that no agent
can bypass it: capabilities, permissions, memory scopes, tool grants, result
validation, persistence and event emission.
"""

from __future__ import annotations

import uuid

import pytest
from seo_engine.agent_registry.registry import AgentRegistry, find_repo_root
from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.runner import AgentRunner, RunRequest
from seo_engine.domain.models.agents import AgentMessage, AgentOutput, AgentRun
from seo_engine.domain.models.observability import EventRecord
from seo_engine.domain.services import BrandService
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.agent import AgentContext, AgentManifest, ProposedAction
from seo_engine.schemas.enums import ContextChannel, EvidenceType, RiskLevel, Role
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import (
    AgentNotFoundError,
    NotFoundError,
    ResultValidationError,
)
from seo_engine.shared.untrusted import wrap_external
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry(find_repo_root() / "agents").load(force=True)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registry_discovers_agents_from_disk(registry: AgentRegistry) -> None:
    assert "BRD-001" in registry
    manifest = registry.manifest("BRD-001")
    assert manifest.name == "Brand Understanding Agent"
    assert "brand.understand" in manifest.capabilities


def test_registry_indexes_agents_by_capability(registry: AgentRegistry) -> None:
    assert "BRD-001" in [m.id for m in registry.find_by_capability("brand.understand")]


def test_registry_raises_for_an_unknown_agent(registry: AgentRegistry) -> None:
    with pytest.raises(AgentNotFoundError):
        registry.manifest("NOPE-999")


def test_manifest_on_disk_overrides_whatever_the_class_declares(
    registry: AgentRegistry,
) -> None:
    """An implementation cannot widen its own permissions in code."""
    agent = registry.get("BRD-001")
    assert agent.manifest.id == "BRD-001"
    assert agent.manifest.approval_required_for == []


async def test_registry_syncs_manifests_into_the_catalogue(
    session: AsyncSession, registry: AgentRegistry
) -> None:
    from seo_engine.domain.models.agents import AgentCapabilityRecord, AgentRecord

    synced = await registry.sync_to_database(session)
    assert synced == len(registry)

    found = await session.execute(select(AgentRecord).where(AgentRecord.agent_id == "BRD-001"))
    record = found.scalar_one()
    assert record.risk_level == "low"

    caps = await session.execute(
        select(AgentCapabilityRecord).where(AgentCapabilityRecord.agent_id == "BRD-001")
    )
    assert "brand.understand" in {c.capability for c in caps.scalars()}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
async def _brand_with_graph(session: AsyncSession, principal: Principal):
    service = BrandService(session, principal)
    brand = await service.create(
        name=f"Acme Diagnostics {uuid.uuid4().hex[:6]}", industry="healthcare"
    )
    await service.add_goal(
        brand.id, goal_type="growth", description="Increase qualified organic leads"
    )
    await service.add_service(
        brand.id, name="DNA testing", keywords=["dna test"], revenue_weight=2.0, priority=1
    )
    await service.add_audience(brand.id, name="Prospective parents", vocabulary=["paternity test"])
    await service.add_location(brand.id, name="Lagos", city="Lagos", country="NG")
    await service.add_competitor(brand.id, name="Rival", domain="rival.test")
    await service.add_competitor(brand.id, name="Other", domain="other.test")
    return brand, service


async def test_full_lifecycle_persists_run_messages_outputs_and_events(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    runner = AgentRunner(session, registry=registry)
    outcome = await runner.run(
        RunRequest(
            agent_id="BRD-001",
            objective="Understand the brand before planning organic growth",
            principal=principal,
            brand_id=brand.id,
            inputs={"brand_id": str(brand.id)},
            services={"brands": brand_service},
        )
    )

    assert outcome.result.status == "completed"
    assert outcome.result.summary
    assert outcome.evidence_refs, "the agent must record evidence"

    runs = await session.execute(select(AgentRun).where(AgentRun.id == outcome.run.id))
    run = runs.scalar_one()
    assert run.status == "completed"
    assert run.latency_ms is not None and run.latency_ms >= 0
    assert run.agent_version == "1.0.0"

    outputs = await session.execute(
        select(AgentOutput).where(AgentOutput.agent_run_id == outcome.run.id)
    )
    assert outputs.scalars().one().schema_name == "BrandUnderstandingOutput"

    events = await session.execute(
        select(EventRecord).where(EventRecord.aggregate_id == str(outcome.run.id))
    )
    types = {e.event_type for e in events.scalars()}
    assert {EventType.AGENT_RUN_STARTED, EventType.AGENT_RUN_COMPLETED} <= types


async def test_the_runner_grants_only_declared_tools(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    outcome = await AgentRunner(session, registry=registry).run(
        RunRequest(
            agent_id="BRD-001",
            objective="Understand the brand",
            principal=principal,
            brand_id=brand.id,
            inputs={"brand_id": str(brand.id)},
            services={"brands": brand_service},
        )
    )
    # BRD-001 declares only `memory`.
    assert set(outcome.context.tools) == {"memory"}
    assert "gsc" not in outcome.context.tools


async def test_an_unconnected_integration_marks_its_tool_unavailable(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    """Rule 1: never present absent data as available."""
    from seo_engine.agent_runtime.resolvers import ToolResolver

    _, _, principal = tenant_ctx
    manifest = registry.manifest("BRD-001").model_copy(update={"tools": ["memory", "gsc"]})
    handles = ToolResolver(available_integrations=set(), principal=principal).resolve(manifest)

    assert handles["gsc"].available is False
    assert "not connected" in (handles["gsc"].unavailable_reason or "")
    # Connected, and the tool becomes available.
    connected = ToolResolver(
        available_integrations={"google_search_console"}, principal=principal
    ).resolve(manifest)
    assert connected["gsc"].available is True


async def test_context_channels_are_structurally_separated(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    outcome = await AgentRunner(session, registry=registry).run(
        RunRequest(
            agent_id="BRD-001",
            objective="Understand the brand",
            principal=principal,
            brand_id=brand.id,
            inputs={"brand_id": str(brand.id)},
            services={"brands": brand_service},
            external_content=[
                ("competitor page", wrap_external("Some rival copy.", source="https://rival.test"))
            ],
        )
    )
    channels = [b.channel for b in outcome.context.blocks]
    assert ContextChannel.SYSTEM in channels
    assert ContextChannel.USER in channels
    assert ContextChannel.EXTERNAL_CONTENT in channels

    external = [b for b in outcome.context.blocks if b.channel == ContextChannel.EXTERNAL_CONTENT]
    assert all(b.trusted is False for b in external)
    assert "BEGIN_UNTRUSTED_EXTERNAL_CONTENT" in external[0].content


async def test_untrusted_page_text_is_not_copied_into_the_message_log(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)
    secret_marker = "UNIQUE-EXTERNAL-MARKER-9137"

    outcome = await AgentRunner(session, registry=registry).run(
        RunRequest(
            agent_id="BRD-001",
            objective="Understand the brand",
            principal=principal,
            brand_id=brand.id,
            inputs={"brand_id": str(brand.id)},
            services={"brands": brand_service},
            external_content=[("rival", wrap_external(secret_marker, source="https://rival.test"))],
        )
    )
    messages = await session.execute(
        select(AgentMessage).where(AgentMessage.agent_run_id == outcome.run.id)
    )
    rows = list(messages.scalars())
    external_rows = [m for m in rows if m.channel == ContextChannel.EXTERNAL_CONTENT.value]
    assert external_rows and all(m.is_untrusted for m in external_rows)
    assert all(secret_marker not in m.content for m in rows)


async def test_memory_is_written_and_retrievable_within_the_tenant(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    from seo_engine.memory.service import MemoryService

    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    await AgentRunner(session, registry=registry).run(
        RunRequest(
            agent_id="BRD-001",
            objective="Understand the brand",
            principal=principal,
            brand_id=brand.id,
            inputs={"brand_id": str(brand.id)},
            services={"brands": brand_service},
        )
    )
    memories = await MemoryService(session, principal.tenant_id).retrieve(brand_id=brand.id)
    assert [m.key for m in memories] == ["brand:profile"]
    assert memories[0].source_agent_id == "BRD-001"


async def test_a_failing_agent_records_the_failure_and_emits_an_event(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx

    with pytest.raises(NotFoundError):
        await AgentRunner(session, registry=registry).run(
            RunRequest(
                agent_id="BRD-001",
                objective="Understand a brand that does not exist",
                principal=principal,
                brand_id=uuid.uuid4(),
                inputs={"brand_id": str(uuid.uuid4())},
                services={"brands": BrandService(session, principal)},
            )
        )

    runs = await session.execute(select(AgentRun).where(AgentRun.agent_id == "BRD-001"))
    failed = [r for r in runs.scalars() if r.status == "failed"]
    assert failed, "the failed run must be recorded"
    assert failed[-1].error_code
    events = await session.execute(
        select(EventRecord).where(EventRecord.event_type == EventType.AGENT_RUN_FAILED)
    )
    assert events.scalars().first() is not None


# ---------------------------------------------------------------------------
# The runner cannot be bypassed
# ---------------------------------------------------------------------------
class _RogueAgent(BaseAgent):
    """Declares nothing, tries to publish content anyway."""

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        workspace.actions.append(ProposedAction(action_type="cms.publish", risk=RiskLevel.CRITICAL))
        return "Published the article."


async def test_an_agent_cannot_propose_an_action_it_does_not_declare(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    rogue = _RogueAgent()
    entry = registry.entry("BRD-001")
    entry._instance = rogue
    rogue.manifest = entry.manifest  # BRD-001 declares no actions at all

    try:
        with pytest.raises(ResultValidationError) as excinfo:
            await AgentRunner(session, registry=registry).run(
                RunRequest(
                    agent_id="BRD-001",
                    objective="Try to publish",
                    principal=principal,
                    brand_id=brand.id,
                    inputs={"brand_id": str(brand.id)},
                    services={"brands": brand_service},
                )
            )
        errors = " ".join(excinfo.value.details["errors"])
        assert "does not declare in its manifest" in errors
    finally:
        entry._instance = None


class _ChattyAgent(BaseAgent):
    """Leaks its private reasoning into the summary."""

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        workspace.observe(
            evidence_type=EvidenceType.BRAND,
            source="test",
            observation="Something was observed.",
        )
        return "Let me think about this step by step before answering."


async def test_chain_of_thought_in_a_result_is_rejected(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    """Rule 8: never expose hidden model reasoning."""
    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    entry = registry.entry("BRD-001")
    chatty = _ChattyAgent()
    chatty.manifest = entry.manifest
    entry._instance = chatty

    try:
        with pytest.raises(ResultValidationError) as excinfo:
            await AgentRunner(session, registry=registry).run(
                RunRequest(
                    agent_id="BRD-001",
                    objective="Understand the brand",
                    principal=principal,
                    brand_id=brand.id,
                    inputs={"brand_id": str(brand.id)},
                    services={"brands": brand_service},
                )
            )
        assert "private model reasoning" in " ".join(excinfo.value.details["errors"])
    finally:
        entry._instance = None


async def test_a_manifest_with_no_capabilities_cannot_run(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    from seo_engine.shared.errors import CapabilityDeniedError

    _, _, principal = tenant_ctx
    brand, brand_service = await _brand_with_graph(session, principal)

    entry = registry.entry("BRD-001")
    original = entry.manifest
    entry.manifest = AgentManifest.model_construct(**{**original.model_dump(), "capabilities": []})
    try:
        with pytest.raises(CapabilityDeniedError):
            await AgentRunner(session, registry=registry).run(
                RunRequest(
                    agent_id="BRD-001",
                    objective="Understand the brand",
                    principal=principal,
                    brand_id=brand.id,
                    inputs={"brand_id": str(brand.id)},
                    services={"brands": brand_service},
                )
            )
    finally:
        entry.manifest = original
        entry._instance = None


async def test_an_agent_cannot_exceed_the_permissions_of_the_user_who_ran_it(
    session: AsyncSession, tenant_ctx, registry: AgentRegistry
) -> None:
    from seo_engine.agent_runtime.resolvers import PermissionResolver, ToolResolver
    from seo_engine.schemas.agent import CapabilityGrant
    from seo_engine.schemas.enums import PermissionLevel

    tenant, user, _ = tenant_ctx
    viewer = Principal.build(
        user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.VIEWER
    )
    manifest = registry.manifest("BRD-001").model_copy(
        update={
            "capabilities": ["content.publish"],
            "tools": ["cms"],
            "permissions": [
                CapabilityGrant(capability="content.publish", permission=PermissionLevel.EXECUTE)
            ],
        }
    )
    # The manifest asks for EXECUTE; the viewer cannot publish, so it is denied.
    resolved = PermissionResolver().resolve(manifest, viewer)
    assert resolved.capabilities["content.publish"] == PermissionLevel.DENY

    # And the CMS tool the manifest declares is denied for the same reason.
    handles = ToolResolver(principal=viewer).resolve(manifest)
    assert handles["cms"].available is False
    assert "does not hold the required permission" in (handles["cms"].unavailable_reason or "")
