"""Result validation.

Built before any agent exists, so no agent can be written that bypasses it.
The runner calls :meth:`ResultValidator.validate` on every result; a failure is
an agent failure, not a warning.

The rules encoded here are the specification's invariants, not style
preferences:

* Rule 7 — every recommendation cites evidence or declares itself a hypothesis;
* Rule 8 — nothing that looks like private model reasoning may be exposed;
* Rule 14 — no fabricated external metrics;
* §64 — high-risk recommendations must require approval;
* an agent may only propose actions it declares, and only cite evidence it
  actually produced or received.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from seo_engine.schemas.agent import AgentContext, AgentManifest, AgentResult
from seo_engine.schemas.enums import RiskLevel
from seo_engine.shared.errors import ResultValidationError

#: Phrases that indicate an agent is leaking its private reasoning into a
#: user-facing field.  Observations, evidence and conclusions are welcome;
#: narrated deliberation is not.
CHAIN_OF_THOUGHT_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(let me think|let's think|thinking step[- ]by[- ]step)\b", re.I),
    re.compile(r"\b(chain[- ]of[- ]thought|my (internal )?(reasoning|thought process))\b", re.I),
    re.compile(r"\b(first,? I (will|should|need to) (consider|think|reason))\b", re.I),
    re.compile(r"<(thinking|scratchpad|reasoning)>", re.I),
    re.compile(r"\bstep 1:.{0,80}\bstep 2:", re.I | re.S),
)

#: Fields an agent writes that a user will read.
USER_FACING_FIELDS = ("summary", "limitations")

RISK_REQUIRING_APPROVAL = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class ResultValidator:
    """Validates an :class:`AgentResult` against the manifest and the context."""

    def validate(
        self,
        result: AgentResult,
        *,
        manifest: AgentManifest,
        context: AgentContext,
        raise_on_error: bool = True,
    ) -> ValidationReport:
        report = ValidationReport()

        self._check_identity(result, manifest, context, report)
        self._check_no_chain_of_thought(result, report)
        self._check_evidence(result, report)
        self._check_recommendations(result, context, report)
        self._check_actions(result, manifest, report)
        self._check_approval(result, report)
        self._check_confidence(result, report)
        self._check_security_flags(result, context, report)

        if raise_on_error and not report.ok:
            raise ResultValidationError(
                "agent result failed validation",
                {
                    "agent_id": result.agent_id,
                    "task_id": str(result.task_id),
                    "errors": report.errors,
                    "warnings": report.warnings,
                },
            )
        return report

    # ------------------------------------------------------------------
    def _check_identity(
        self,
        result: AgentResult,
        manifest: AgentManifest,
        context: AgentContext,
        report: ValidationReport,
    ) -> None:
        if result.agent_id != manifest.id:
            report.error(
                f"result claims agent_id {result.agent_id!r} but was produced by {manifest.id!r}"
            )
        if result.task_id != context.task_id:
            report.error("result task_id does not match the task it was dispatched for")

    def _check_no_chain_of_thought(self, result: AgentResult, report: ValidationReport) -> None:
        """Rule 8: expose conclusions, never private reasoning."""
        blobs: list[tuple[str, str]] = [("summary", result.summary)]
        blobs += [(f"limitations[{i}]", text) for i, text in enumerate(result.limitations)]
        blobs += [(f"findings[{i}].detail", f.detail) for i, f in enumerate(result.findings)]
        blobs += [
            (f"recommendations[{i}].reason", r.reason) for i, r in enumerate(result.recommendations)
        ]

        for label, text in blobs:
            if not text:
                continue
            for pattern in CHAIN_OF_THOUGHT_MARKERS:
                if pattern.search(text):
                    report.error(
                        f"{label} appears to expose private model reasoning "
                        f"(matched {pattern.pattern!r})"
                    )
                    break

    def _check_evidence(self, result: AgentResult, report: ValidationReport) -> None:
        ids = [e.id for e in result.evidence]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            report.error(f"duplicate evidence ids: {sorted(duplicates)}")

        for item in result.evidence:
            if item.is_inference and item.confidence > 0.95:
                report.warn(
                    f"evidence {item.id} is an inference but claims confidence "
                    f"{item.confidence}; inferences should not be near-certain"
                )

    def _check_recommendations(
        self, result: AgentResult, context: AgentContext, report: ValidationReport
    ) -> None:
        # Evidence the agent produced, plus evidence the runtime handed it.
        available = {e.id for e in result.evidence} | {e.id for e in context.evidence}

        for index, rec in enumerate(result.recommendations):
            label = f"recommendations[{index}]"

            # The schema already enforces evidence-or-hypothesis; this catches
            # the subtler failure of citing evidence that does not exist.
            unknown = [ref for ref in rec.evidence_ids if ref not in available]
            if unknown:
                report.error(f"{label} cites evidence that was never produced: {unknown}")

            if rec.is_hypothesis and rec.confidence > 0.6:
                report.error(
                    f"{label} is an unevidenced hypothesis but claims confidence "
                    f"{rec.confidence}; cap hypothesis confidence at 0.6"
                )
            if rec.effort <= 0:
                report.error(f"{label} has non-positive effort, which breaks prioritisation")

    def _check_actions(
        self, result: AgentResult, manifest: AgentManifest, report: ValidationReport
    ) -> None:
        declared = set(manifest.autonomous_actions) | set(manifest.approval_required_for)
        for index, action in enumerate(result.actions):
            # An empty declaration is a deny-list of everything, not a wildcard.
            if action.action_type not in declared:
                report.error(
                    f"actions[{index}] proposes {action.action_type!r}, which "
                    f"{manifest.id} does not declare in its manifest"
                )

    def _check_approval(self, result: AgentResult, report: ValidationReport) -> None:
        """§64: a high-risk recommendation must ask for approval."""
        risky = [r for r in result.recommendations if r.risk in RISK_REQUIRING_APPROVAL]
        risky_actions = [a for a in result.actions if a.risk in RISK_REQUIRING_APPROVAL]
        if (risky or risky_actions) and not result.requires_approval:
            report.error(
                "result contains high-risk items but does not set requires_approval; "
                f"risky recommendations={len(risky)}, risky actions={len(risky_actions)}"
            )
        if result.status == "requires_approval" and not result.requires_approval:
            report.error("status is requires_approval but requires_approval is False")

    def _check_confidence(self, result: AgentResult, report: ValidationReport) -> None:
        if result.status != "completed":
            return
        if result.confidence >= 0.9 and not result.evidence:
            report.error(
                "a result claiming confidence >= 0.9 must cite at least one piece of evidence"
            )
        if not result.evidence and not result.limitations:
            report.warn(
                "result has neither evidence nor stated limitations; say what you could not see"
            )

    def _check_security_flags(
        self, result: AgentResult, context: AgentContext, report: ValidationReport
    ) -> None:
        """A detected injection attempt must be reported, never swallowed."""
        detected = context.injection_flags
        if detected and not result.security_flags:
            report.error(
                "the agent context contained suspected prompt injection but the "
                "result reports no security flags"
            )


__all__ = [
    "CHAIN_OF_THOUGHT_MARKERS",
    "USER_FACING_FIELDS",
    "ResultValidator",
    "ValidationReport",
]
