"""The Agent Runner.

This is the only way an agent ever executes.  The lifecycle is fixed:

    Task → load agent → validate capabilities → build context →
    resolve permissions → resolve memory → resolve tools → execute →
    validate result → persist → emit event

Every step is mandatory.  A failure at any step fails the run, records why, and
emits an event; nothing is silently skipped, and no partial result is treated as
success.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from seo_engine.agent_registry.registry import AgentRegistry, get_registry
from seo_engine.agent_runtime.context import AgentContextBuilder
from seo_engine.agent_runtime.resolvers import (
    MemoryResolver,
    PermissionResolver,
    PolicyResolver,
    ToolResolver,
)
from seo_engine.agent_runtime.validator import ResultValidator
from seo_engine.domain.models.agents import AgentMessage, AgentOutput, AgentRun
from seo_engine.domain.repositories import repository_for
from seo_engine.events.bus import emit
from seo_engine.evidence.collector import EvidenceCollector
from seo_engine.observability.logging import get_logger, log_context
from seo_engine.observability.metrics import counter, observe
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.agent import AgentContext, AgentManifest, AgentResult
from seo_engine.schemas.enums import AutomationPolicy, ContextChannel, TaskStatus
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import (
    AgentExecutionError,
    CapabilityDeniedError,
    SEOEngineError,
)
from seo_engine.shared.ids import new_ref, utcnow
from seo_engine.shared.untrusted import UntrustedContent
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

AgentRunRepository = repository_for(AgentRun)
AgentMessageRepository = repository_for(AgentMessage)
AgentOutputRepository = repository_for(AgentOutput)


@dataclass(slots=True)
class RunRequest:
    """Everything needed to dispatch one agent run."""

    agent_id: str
    objective: str
    principal: Principal
    task_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    mission_id: uuid.UUID | None = None
    workflow_id: str | None = None
    correlation_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    external_content: list[tuple[str, UntrustedContent]] = field(default_factory=list)
    tool_outputs: list[tuple[str, str, str]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    services: dict[str, Any] = field(default_factory=dict)
    available_integrations: set[str] = field(default_factory=set)
    automation_policy: AutomationPolicy | str = AutomationPolicy.APPROVAL_REQUIRED
    memory_query: str | None = None
    inherited_evidence_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunOutcome:
    result: AgentResult
    run: AgentRun
    context: AgentContext
    evidence_refs: list[str]
    validation_warnings: list[str] = field(default_factory=list)


class AgentRunner:
    """Executes agents through the mandated lifecycle."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: AgentRegistry | None = None,
        validator: ResultValidator | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or get_registry()
        self.validator = validator or ResultValidator()

    # ------------------------------------------------------------------
    async def run(self, request: RunRequest) -> RunOutcome:
        principal = request.principal
        tenant_id = principal.tenant_id
        correlation_id = request.correlation_id or new_ref("corr")
        run_id = uuid.uuid4()
        task_id = request.task_id or uuid.uuid4()

        with log_context(
            correlation_id=correlation_id,
            agent_run_id=str(run_id),
            agent_id=request.agent_id,
            tenant_id=str(tenant_id),
            task_id=str(task_id),
        ):
            # 1. Load the agent.
            manifest = self.registry.manifest(request.agent_id)
            agent = self.registry.get(request.agent_id)

            run_record = await self._open_run(
                request, manifest, run_id=run_id, task_id=task_id, correlation_id=correlation_id
            )
            await emit(
                self.session,
                EventType.AGENT_RUN_STARTED,
                tenant_id=tenant_id,
                brand_id=request.brand_id,
                aggregate_type="agent_run",
                aggregate_id=str(run_record.id),
                actor_type="agent",
                actor_id=manifest.id,
                correlation_id=correlation_id,
                payload={"objective": request.objective, "task_id": str(task_id)},
            )

            started = time.perf_counter()
            try:
                # 2-7. Validate capabilities, resolve everything, build context.
                context = await self._build_context(
                    request,
                    manifest,
                    run_id=run_record.id,
                    task_id=task_id,
                    correlation_id=correlation_id,
                )
                await self._record_messages(run_record, context)

                # 8. Execute.
                result = await agent.execute(context)
                if not isinstance(result, AgentResult):
                    raise AgentExecutionError(
                        f"agent {manifest.id} returned {type(result).__name__}, not AgentResult",
                        {"agent_id": manifest.id},
                    )

                # 9. Validate the result.
                report = self.validator.validate(result, manifest=manifest, context=context)

                # 10. Persist.
                evidence_refs = await self._persist(run_record, result, request, manifest, context)
                latency_ms = int((time.perf_counter() - started) * 1000)
                self._close_run(run_record, result, latency_ms)
                await self.session.flush()

                # 11. Emit.
                counter("agent_runs_total", agent_id=manifest.id, status=result.status)
                observe("agent_latency_ms", latency_ms, agent_id=manifest.id)
                await emit(
                    self.session,
                    EventType.AGENT_RUN_COMPLETED,
                    tenant_id=tenant_id,
                    brand_id=request.brand_id,
                    aggregate_type="agent_run",
                    aggregate_id=str(run_record.id),
                    actor_type="agent",
                    actor_id=manifest.id,
                    correlation_id=correlation_id,
                    payload={
                        "status": result.status,
                        "confidence": result.confidence,
                        "recommendations": len(result.recommendations),
                        "evidence": len(evidence_refs),
                        "latency_ms": latency_ms,
                    },
                )
                if result.security_flags:
                    await emit(
                        self.session,
                        EventType.PROMPT_INJECTION_DETECTED,
                        tenant_id=tenant_id,
                        brand_id=request.brand_id,
                        aggregate_type="agent_run",
                        aggregate_id=str(run_record.id),
                        actor_type="agent",
                        actor_id=manifest.id,
                        correlation_id=correlation_id,
                        payload={"flags": result.security_flags},
                    )

                log.info(
                    "agent_run_completed",
                    status=result.status,
                    confidence=result.confidence,
                    latency_ms=latency_ms,
                )
                return RunOutcome(
                    result=result,
                    run=run_record,
                    context=context,
                    evidence_refs=evidence_refs,
                    validation_warnings=report.warnings,
                )

            except Exception as exc:
                latency_ms = int((time.perf_counter() - started) * 1000)
                await self._fail_run(
                    run_record, exc, latency_ms, request, correlation_id=correlation_id
                )
                raise

    # ------------------------------------------------------------------
    async def _open_run(
        self,
        request: RunRequest,
        manifest: AgentManifest,
        *,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
        correlation_id: str,
    ) -> AgentRun:
        repo = AgentRunRepository(self.session, request.principal.tenant_id)
        record = repo.add(
            AgentRun(
                id=run_id,
                agent_id=manifest.id,
                agent_version=manifest.version,
                task_id=task_id,
                brand_id=request.brand_id,
                mission_id=request.mission_id,
                workflow_id=request.workflow_id,
                correlation_id=correlation_id,
                status=TaskStatus.RUNNING.value,
                objective=request.objective,
                inputs=_jsonable(request.inputs),
                started_at=utcnow(),
            )
        )
        await self.session.flush()
        return record

    async def _build_context(
        self,
        request: RunRequest,
        manifest: AgentManifest,
        *,
        run_id: uuid.UUID,
        task_id: uuid.UUID,
        correlation_id: str,
    ) -> AgentContext:
        tenant_id = request.principal.tenant_id

        # 2. Validate capabilities: the manifest must declare at least one.
        if not manifest.capabilities:
            raise CapabilityDeniedError(
                f"agent {manifest.id} declares no capabilities and cannot run",
                {"agent_id": manifest.id},
            )

        # 4. Permissions — the intersection of manifest and principal.
        permissions = PermissionResolver().resolve(manifest, request.principal)

        # 5. Memory — only the declared scopes.
        memory = await MemoryResolver(self.session, tenant_id).resolve(
            manifest,
            brand_id=request.brand_id,
            mission_id=request.mission_id,
            task_id=task_id,
            query=request.memory_query or request.objective,
        )

        # 6. Tools — only the declared tools, marked unavailable where honest.
        tools = ToolResolver(request.available_integrations, principal=request.principal).resolve(
            manifest, permissions
        )

        # Policy context.
        policy = await PolicyResolver(self.session, tenant_id).resolve(
            manifest,
            brand_id=request.brand_id,
            automation_policy=request.automation_policy,
        )

        # Inherited evidence from upstream agents in the same mission.
        collector = EvidenceCollector(
            self.session,
            tenant_id,
            brand_id=request.brand_id,
            agent_id=manifest.id,
            agent_run_id=run_id,
        )
        inherited = await collector.load(request.inherited_evidence_refs)

        builder = AgentContextBuilder(
            manifest=manifest,
            tenant_id=tenant_id,
            task_id=task_id,
            run_id=run_id,
            correlation_id=correlation_id,
            objective=request.objective,
            brand_id=request.brand_id,
            project_id=request.project_id,
            mission_id=request.mission_id,
        )
        builder.add_user_instruction(request.objective)
        if policy.rules:
            builder.add_developer_policy(
                "Actions matching these rules require the stated handling:\n"
                + "\n".join(
                    f"- {r.get('policy')}: {r.get('reason', 'see policy')}"
                    for r in policy.rules[:20]
                )
            )
        for label, content, tool in request.tool_outputs:
            builder.add_tool_output(label, content, tool=tool)
        for label, external in request.external_content:
            builder.add_external(label, external)

        services = dict(request.services)
        services.setdefault("evidence", collector)
        services.setdefault("memory", MemoryResolver(self.session, tenant_id).service)

        return (
            builder.with_inputs(request.inputs)
            .with_memory(memory)
            .with_evidence(inherited)
            .with_tools(tools)
            .with_permissions(permissions)
            .with_policy(policy)
            .with_constraints(list(request.constraints))
            .with_services(services)
            .build()
        )

    async def _record_messages(self, run: AgentRun, context: AgentContext) -> None:
        """Persist the observable channels only — never private reasoning."""
        repo = AgentMessageRepository(self.session, run.tenant_id)
        for index, block in enumerate(context.blocks):
            repo.add(
                AgentMessage(
                    agent_run_id=run.id,
                    sequence=index,
                    channel=block.channel.value,
                    label=block.label,
                    # External content is recorded by reference and findings,
                    # not by pasting a full untrusted page into our own tables.
                    content=(
                        f"[{len(block.content)} chars of untrusted external content]"
                        if block.channel == ContextChannel.EXTERNAL_CONTENT
                        else block.content[:20_000]
                    ),
                    is_untrusted=not block.trusted,
                    metadata_json=block.metadata,
                )
            )
        await self.session.flush()

    async def _persist(
        self,
        run: AgentRun,
        result: AgentResult,
        request: RunRequest,
        manifest: AgentManifest,
        context: AgentContext,
    ) -> list[str]:
        collector: EvidenceCollector = context.services["evidence"]
        await collector.persist(result.evidence)

        outputs = AgentOutputRepository(self.session, run.tenant_id)
        outputs.add(
            AgentOutput(
                agent_run_id=run.id,
                output_type="result",
                payload=result.model_dump(mode="json"),
                schema_name=manifest.output_schema,
                is_valid=True,
            )
        )
        await self.session.flush()
        return [e.id for e in result.evidence]

    def _close_run(self, run: AgentRun, result: AgentResult, latency_ms: int) -> None:
        run.status = result.status
        run.summary = result.summary
        run.confidence = result.confidence
        run.synthesis_mode = result.synthesis_mode.value
        run.limitations = result.limitations
        run.security_flags = result.security_flags
        run.tools_used = sorted(result.outputs.get("tools_used", []))
        run.memory_scopes = [s.value for s in result.outputs.get("memory_scopes", [])]
        run.latency_ms = latency_ms
        run.completed_at = utcnow()

    async def _fail_run(
        self,
        run: AgentRun,
        exc: Exception,
        latency_ms: int,
        request: RunRequest,
        *,
        correlation_id: str,
    ) -> None:
        code = exc.code if isinstance(exc, SEOEngineError) else type(exc).__name__
        run.status = TaskStatus.FAILED.value
        run.error_code = code
        run.error_message = str(exc)[:4000]
        run.latency_ms = latency_ms
        run.completed_at = utcnow()
        await self.session.flush()

        counter("agent_failures_total", agent_id=run.agent_id, error=code)
        log.error("agent_run_failed", error_code=code, error=str(exc))
        await emit(
            self.session,
            EventType.AGENT_RUN_FAILED,
            tenant_id=run.tenant_id,
            brand_id=request.brand_id,
            aggregate_type="agent_run",
            aggregate_id=str(run.id),
            actor_type="agent",
            actor_id=run.agent_id,
            correlation_id=correlation_id,
            payload={"error_code": code, "error": str(exc)[:500]},
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


__all__ = ["AgentRunner", "RunOutcome", "RunRequest"]
