"""Agent contracts: manifest, context, result.

Every agent in the platform is described by a manifest, receives an
:class:`AgentContext` and returns an :class:`AgentResult`.  No agent is allowed
to run outside this contract — see ``seo_engine.agent_runtime.runner``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from seo_engine.schemas.enums import (
    ContextChannel,
    MemoryScope,
    PermissionLevel,
    RiskLevel,
    SynthesisMode,
)
from seo_engine.schemas.evidence import EvidenceRecord


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
class ModelPolicy(BaseModel):
    """How the model gateway should serve this agent."""

    reasoning: Literal["low", "medium", "high"] = "medium"
    temperature: float = Field(ge=0.0, le=2.0, default=0.2)
    max_output_tokens: int = Field(gt=0, default=4096)
    deterministic_fallback: bool = Field(
        default=True,
        description=(
            "When true the agent can complete without an LLM provider, using its "
            "deterministic path.  Outputs are labelled synthesis_mode=deterministic."
        ),
    )


class CapabilityGrant(BaseModel):
    capability: str
    permission: PermissionLevel = PermissionLevel.READ


class AgentManifest(BaseModel):
    """Declarative description of an agent.  Loaded from ``manifest.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Z]{3,5}-\d{3}$")
    name: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str
    module: str = Field(
        default="agent.py",
        description="Python file inside the agent directory that exposes `AGENT`.",
    )

    capabilities: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    memory_scopes: list[MemoryScope] = Field(default_factory=list)

    risk_level: RiskLevel = RiskLevel.LOW

    input_schema: str
    output_schema: str

    autonomous_actions: list[str] = Field(default_factory=list)
    approval_required_for: list[str] = Field(default_factory=list)

    permissions: list[CapabilityGrant] = Field(default_factory=list)
    model_policy: ModelPolicy = Field(default_factory=ModelPolicy)

    prompt: str | None = Field(
        default=None, description="Prompt registry key, e.g. `agents/seo/keyword-intelligence`."
    )
    tags: list[str] = Field(default_factory=list)

    @field_validator("capabilities", "tools", "autonomous_actions", "approval_required_for")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate entries are not allowed")
        return value

    @model_validator(mode="after")
    def _permissions_cover_capabilities(self) -> AgentManifest:
        granted = {p.capability for p in self.permissions}
        missing = [c for c in self.capabilities if c not in granted]
        # Capabilities without an explicit grant default to READ.
        for capability in missing:
            self.permissions.append(
                CapabilityGrant(capability=capability, permission=PermissionLevel.READ)
            )
        return self

    def permission_for(self, capability: str) -> PermissionLevel:
        for grant in self.permissions:
            if grant.capability == capability:
                return grant.permission
        return PermissionLevel.DENY

    def requires_approval_for(self, action_type: str) -> bool:
        return action_type in self.approval_required_for

    def may_act_autonomously(self, action_type: str) -> bool:
        return action_type in self.autonomous_actions


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
class ContextBlock(BaseModel):
    """One structurally separated section of an agent's context.

    Channels are never concatenated into a single undifferentiated instruction
    stream; the model gateway renders each channel with its own framing.
    """

    channel: ContextChannel
    label: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    trusted: bool = True

    @model_validator(mode="after")
    def _external_is_untrusted(self) -> ContextBlock:
        if self.channel == ContextChannel.EXTERNAL_CONTENT and self.trusted:
            raise ValueError("external content blocks must be marked untrusted")
        return self


class MemoryContext(BaseModel):
    brand_facts: list[dict[str, Any]] = Field(default_factory=list)
    historical: list[dict[str, Any]] = Field(default_factory=list)
    outcomes: list[dict[str, Any]] = Field(default_factory=list)
    working: dict[str, Any] = Field(default_factory=dict)
    scopes: list[MemoryScope] = Field(default_factory=list)


class ToolHandle(BaseModel):
    """A tool the runtime resolved and granted to this run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    permission: PermissionLevel
    description: str = ""
    available: bool = True
    unavailable_reason: str | None = None


class PermissionContext(BaseModel):
    capabilities: dict[str, PermissionLevel] = Field(default_factory=dict)
    roles: list[str] = Field(default_factory=list)

    def allows(self, capability: str, minimum: PermissionLevel) -> bool:
        order = [
            PermissionLevel.DENY,
            PermissionLevel.READ,
            PermissionLevel.PROPOSE,
            PermissionLevel.EXECUTE,
            PermissionLevel.AUTONOMOUS,
        ]
        current = self.capabilities.get(capability, PermissionLevel.DENY)
        return order.index(current) >= order.index(minimum)


class PolicyContext(BaseModel):
    automation_policy: str = "approval_required"
    risk_threshold: RiskLevel = RiskLevel.MEDIUM
    approval_required_actions: list[str] = Field(default_factory=list)
    rules: list[dict[str, Any]] = Field(default_factory=list)


class BudgetContext(BaseModel):
    max_llm_calls: int | None = None
    max_tool_calls: int | None = None
    max_cost_usd: float | None = None


class AgentContext(BaseModel):
    """Everything an agent is allowed to know for one run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tenant_id: UUID
    brand_id: UUID | None = None
    project_id: UUID | None = None
    mission_id: UUID | None = None
    task_id: UUID
    run_id: UUID
    correlation_id: str

    agent_id: str
    objective: str
    inputs: dict[str, Any] = Field(default_factory=dict)

    blocks: list[ContextBlock] = Field(default_factory=list)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    tools: dict[str, ToolHandle] = Field(default_factory=dict)
    permissions: PermissionContext = Field(default_factory=PermissionContext)
    policy: PolicyContext = Field(default_factory=PolicyContext)
    constraints: list[str] = Field(default_factory=list)
    budget: BudgetContext | None = None

    #: Services handed to the agent.  Agents never touch the database directly
    #: (Build Specification rule 4) — they call domain services from here.
    services: dict[str, Any] = Field(default_factory=dict, exclude=True)

    def block(self, channel: ContextChannel) -> list[ContextBlock]:
        return [b for b in self.blocks if b.channel == channel]

    def service(self, name: str) -> Any:
        from seo_engine.shared.errors import AgentExecutionError

        if name not in self.services:
            raise AgentExecutionError(
                f"agent {self.agent_id} requested unavailable service '{name}'",
                {"agent_id": self.agent_id, "service": name},
            )
        return self.services[name]

    def tool(self, name: str) -> ToolHandle:
        from seo_engine.shared.errors import CapabilityDeniedError

        handle = self.tools.get(name)
        if handle is None:
            raise CapabilityDeniedError(
                f"agent {self.agent_id} is not granted tool '{name}'",
                {"agent_id": self.agent_id, "tool": name},
            )
        return handle

    def has_tool(self, name: str) -> bool:
        handle = self.tools.get(name)
        return bool(handle and handle.available)

    @property
    def injection_flags(self) -> list[dict[str, Any]]:
        flags: list[dict[str, Any]] = []
        for blk in self.blocks:
            findings = blk.metadata.get("injection_findings") or []
            if findings:
                flags.append(
                    {"label": blk.label, "source": blk.metadata.get("source"), "findings": findings}
                )
        return flags


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
class Finding(BaseModel):
    """An observation an agent made, with the evidence that supports it."""

    key: str
    title: str
    detail: str = ""
    severity: str = "info"
    data: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class ProposedRecommendation(BaseModel):
    """A recommendation as produced by an agent, before persistence."""

    type: str
    title: str
    problem: str
    opportunity: str
    reason: str
    business_impact: float = Field(ge=0, le=10, default=5)
    seo_impact: float = Field(ge=0, le=10, default=5)
    effort: float = Field(ge=1, le=10, default=5)
    risk: RiskLevel = RiskLevel.LOW
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    strategic_fit: float = Field(ge=0.0, le=1.0, default=0.7)
    expected_outcome: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    is_hypothesis: bool = Field(
        default=False,
        description="Set when the recommendation has no supporting evidence.",
    )
    proposed_action: dict[str, Any] | None = None
    target_entity_type: str | None = None
    target_entity_id: str | None = None
    dependencies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_or_hypothesis(self) -> ProposedRecommendation:
        if not self.evidence_ids and not self.is_hypothesis:
            raise ValueError("a recommendation must cite evidence or be marked is_hypothesis=True")
        return self


class ProposedAction(BaseModel):
    action_type: str
    target: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.LOW
    idempotency_key: str | None = None


class NextTask(BaseModel):
    agent_id: str
    objective: str
    task_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    priority: str = "normal"


class AgentResult(BaseModel):
    """The only shape an agent may return."""

    model_config = ConfigDict(use_enum_values=False)

    task_id: UUID
    agent_id: str
    status: Literal["completed", "failed", "requires_approval", "blocked"] = "completed"
    summary: str

    findings: list[Finding] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    recommendations: list[ProposedRecommendation] = Field(default_factory=list)
    actions: list[ProposedAction] = Field(default_factory=list)
    next_tasks: list[NextTask] = Field(default_factory=list)

    outputs: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)

    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    limitations: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    synthesis_mode: SynthesisMode = SynthesisMode.DETERMINISTIC
    security_flags: list[dict[str, Any]] = Field(default_factory=list)

    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("summary")
    @classmethod
    def _summary_present(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("agent result summary must not be empty")
        return value.strip()


__all__ = [
    "AgentContext",
    "AgentManifest",
    "AgentResult",
    "BudgetContext",
    "CapabilityGrant",
    "ContextBlock",
    "Finding",
    "MemoryContext",
    "ModelPolicy",
    "NextTask",
    "PermissionContext",
    "PolicyContext",
    "ProposedAction",
    "ProposedRecommendation",
    "SourceReference",
    "ToolHandle",
]

from seo_engine.schemas.evidence import SourceReference  # noqa: E402  (re-export)
