"""Base class for agents.

Agents subclass :class:`BaseAgent` and implement :meth:`BaseAgent.run`.  The
base class supplies the bookkeeping every agent would otherwise repeat —
evidence access, security-flag propagation, limitation tracking and result
assembly — so that individual agents contain analysis, not plumbing.

It deliberately does *not* let an agent skip anything the runner enforces: the
runner still validates whatever comes back.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from seo_engine.evidence.collector import EvidenceCollector
from seo_engine.schemas.agent import (
    AgentContext,
    AgentManifest,
    AgentResult,
    Finding,
    NextTask,
    ProposedAction,
    ProposedRecommendation,
)
from seo_engine.schemas.enums import SynthesisMode
from seo_engine.schemas.evidence import EvidenceRecord
from seo_engine.shared.ids import utcnow


class AgentWorkspace:
    """Scratch space for one run: findings, evidence, limitations, flags."""

    def __init__(self, context: AgentContext) -> None:
        self.context = context
        self.findings: list[Finding] = []
        self.recommendations: list[ProposedRecommendation] = []
        self.actions: list[ProposedAction] = []
        self.next_tasks: list[NextTask] = []
        self.limitations: list[str] = []
        self.outputs: dict[str, Any] = {}
        self.metrics: dict[str, float] = {}
        self.tools_used: set[str] = set()
        self._security_flags: list[dict[str, Any]] = []

    # -- evidence ---------------------------------------------------------
    @property
    def evidence_collector(self) -> EvidenceCollector:
        return self.context.service("evidence")

    def observe(self, **kwargs: Any) -> EvidenceRecord:
        return self.evidence_collector.observe(**kwargs)

    def infer(self, **kwargs: Any) -> EvidenceRecord:
        return self.evidence_collector.infer(**kwargs)

    @property
    def evidence(self) -> list[EvidenceRecord]:
        return self.evidence_collector.collected

    # -- findings ---------------------------------------------------------
    def find(
        self,
        key: str,
        title: str,
        *,
        detail: str = "",
        severity: str = "info",
        data: dict[str, Any] | None = None,
        evidence: list[EvidenceRecord] | None = None,
    ) -> Finding:
        finding = Finding(
            key=key,
            title=title,
            detail=detail,
            severity=severity,
            data=data or {},
            evidence_ids=[e.id for e in (evidence or [])],
        )
        self.findings.append(finding)
        return finding

    def recommend(self, recommendation: ProposedRecommendation) -> ProposedRecommendation:
        self.recommendations.append(recommendation)
        return recommendation

    def limitation(self, text: str) -> None:
        if text not in self.limitations:
            self.limitations.append(text)

    def note_unavailable_tool(self, tool: str) -> bool:
        """Record honestly that a tool was unavailable.  Returns availability."""
        handle = self.context.tools.get(tool)
        if handle is None:
            self.limitation(f"The {tool} tool was not granted to this agent.")
            return False
        if not handle.available:
            self.limitation(
                f"{tool} was unavailable: {handle.unavailable_reason}. "
                "No data from it is included, and nothing has been estimated in its place."
            )
            return False
        self.tools_used.add(tool)
        return True

    # -- security ---------------------------------------------------------
    def collect_security_flags(self) -> list[dict[str, Any]]:
        """Propagate any injection attempt the context builder detected."""
        flags = list(self._security_flags)
        for flag in self.context.injection_flags:
            flags.append(
                {
                    "type": "prompt_injection_attempt",
                    "source": flag.get("source"),
                    "label": flag.get("label"),
                    "patterns": [f["pattern"] for f in flag.get("findings", [])],
                    "handling": (
                        "The content was treated strictly as data. No instruction "
                        "inside it was followed."
                    ),
                }
            )
        return flags

    def flag(self, **flag: Any) -> None:
        self._security_flags.append(flag)


class BaseAgent(ABC):
    """Every agent in the platform derives from this."""

    #: Set by the registry from the on-disk manifest.  An implementation cannot
    #: widen its own permissions by overriding it.
    manifest: AgentManifest

    synthesis_mode: SynthesisMode = SynthesisMode.DETERMINISTIC

    @abstractmethod
    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        """Do the work and return a plain-language summary."""

    async def execute(self, context: AgentContext) -> AgentResult:
        started = utcnow()
        workspace = AgentWorkspace(context)

        summary = await self.run(context, workspace)

        security_flags = workspace.collect_security_flags()
        if security_flags and not any(
            "injection" in limitation.lower() for limitation in workspace.limitations
        ):
            workspace.limitation(
                "Content retrieved during this run attempted to issue instructions. "
                "It was treated as data only and is reported as a security finding."
            )

        outputs = dict(workspace.outputs)
        outputs["tools_used"] = sorted(workspace.tools_used)
        outputs["memory_scopes"] = list(context.memory.scopes)

        return AgentResult(
            task_id=context.task_id,
            agent_id=self.manifest.id,
            status="completed",
            summary=summary,
            findings=workspace.findings,
            evidence=workspace.evidence,
            recommendations=workspace.recommendations,
            actions=workspace.actions,
            next_tasks=workspace.next_tasks,
            outputs=outputs,
            metrics=workspace.metrics,
            confidence=self.confidence(workspace),
            limitations=workspace.limitations,
            requires_approval=self.requires_approval(workspace),
            synthesis_mode=self.synthesis_mode,
            security_flags=security_flags,
            started_at=started,
            completed_at=utcnow(),
        )

    # -- overridable heuristics -------------------------------------------
    def confidence(self, workspace: AgentWorkspace) -> float:
        """Confidence grounded in what was actually observed.

        More observed evidence raises it; stated limitations lower it.  An agent
        with no evidence at all cannot claim more than 0.4.
        """
        observed = sum(1 for e in workspace.evidence if e.is_observation)
        if observed == 0:
            base = 0.4
        else:
            base = min(0.55 + 0.05 * observed, 0.92)
        penalty = min(0.05 * len(workspace.limitations), 0.3)
        return round(max(0.1, base - penalty), 2)

    def requires_approval(self, workspace: AgentWorkspace) -> bool:
        from seo_engine.agent_runtime.validator import RISK_REQUIRING_APPROVAL

        if any(r.risk in RISK_REQUIRING_APPROVAL for r in workspace.recommendations):
            return True
        if any(a.risk in RISK_REQUIRING_APPROVAL for a in workspace.actions):
            return True
        return any(a.action_type in self.manifest.approval_required_for for a in workspace.actions)


__all__ = ["AgentWorkspace", "BaseAgent"]
