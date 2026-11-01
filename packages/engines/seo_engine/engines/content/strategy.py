"""The content roadmap.

Turns content gap decisions into a sequenced plan. The ordering rules are the
strategy, and they are deliberately conservative:

1. **Fix before you add.** CONSOLIDATE and UPDATE work on pages that already
   exist is scheduled before any CREATE: a new page competing with an unfixed
   one only adds to the problem.
2. **Business value first.** Within a phase, topics are ordered by commercial
   intent and by whether they serve a service the customer actually sells.
3. **Capacity is real.** The plan never schedules more pieces in a month than
   the stated capacity; the overflow is reported as a backlog, not crammed in.
4. **DO_NOTHING is a decision.** Topics that do not justify content are counted
   and listed with their reason, not silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.intent import intent_commercial_value
from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.schemas.enums import ContentDecision
from seo_engine.schemas.search import IntentDistribution

PHASE_ORDER: dict[ContentDecision, int] = {
    ContentDecision.CONSOLIDATE: 0,
    ContentDecision.REDIRECT: 0,
    ContentDecision.UPDATE: 1,
    ContentDecision.CREATE: 2,
}

PRIORITY_FORMULA = (
    "priority = 0.45 * commercial intent value + 0.30 * service alignment "
    "+ 0.25 * gap confidence (each 0-100); fix-first phases precede creation."
)


@dataclass(slots=True)
class RoadmapItem:
    topic: str
    decision: ContentDecision
    month: int
    priority: float
    service: str | None
    target_url: str | None
    cluster_id: str | None
    rationale: str
    evidence_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "decision": self.decision.value,
            "month": self.month,
            "priority": self.priority,
            "service": self.service,
            "target_url": self.target_url,
            "cluster_id": self.cluster_id,
            "rationale": self.rationale,
            "evidence_ids": self.evidence_ids,
        }


@dataclass(slots=True)
class Roadmap:
    items: list[RoadmapItem] = field(default_factory=list)
    backlog: list[RoadmapItem] = field(default_factory=list)
    not_pursued: list[dict[str, str]] = field(default_factory=list)
    months: int = 6
    capacity_per_month: int = 4

    def as_dict(self) -> dict[str, Any]:
        return {
            "months": self.months,
            "capacity_per_month": self.capacity_per_month,
            "items": [i.as_dict() for i in self.items],
            "backlog": [i.as_dict() for i in self.backlog],
            "not_pursued": self.not_pursued,
            "priority_formula": PRIORITY_FORMULA,
        }


def _service_alignment(
    topic: str, services: list[tuple[str, list[str]]]
) -> tuple[float, str | None]:
    tokens = content_tokens(topic)
    best, name = 0.0, None
    for service_name, terms in services:
        service_tokens = content_tokens(" ".join([service_name, *terms]))
        if not service_tokens or not tokens:
            continue
        overlap = len(tokens & service_tokens) / len(tokens)
        if overlap > best:
            best, name = overlap, service_name
    return round(best * 100, 1), name if best >= 0.34 else None


def build_roadmap(
    gaps: list[dict[str, Any]],
    *,
    services: list[tuple[str, list[str]]],
    months: int = 6,
    capacity_per_month: int = 4,
) -> Roadmap:
    """Sequence the content gap decisions into a capacity-bounded plan."""
    roadmap = Roadmap(months=months, capacity_per_month=capacity_per_month)
    candidates: list[RoadmapItem] = []

    for gap in gaps:
        decision = ContentDecision(gap.get("decision", ContentDecision.DO_NOTHING))
        topic = str(gap.get("topic") or "")
        if not topic:
            continue
        if decision is ContentDecision.DO_NOTHING:
            roadmap.not_pursued.append(
                {"topic": topic, "reason": str(gap.get("decision_reason") or "")}
            )
            continue
        intent = IntentDistribution(**(gap.get("intent") or {}))
        commercial = intent_commercial_value(intent)
        alignment, service = _service_alignment(topic, services)
        confidence = float(gap.get("confidence") or 0.5) * 100
        priority = round(0.45 * commercial + 0.30 * alignment + 0.25 * confidence, 1)
        candidates.append(
            RoadmapItem(
                topic=topic,
                decision=decision,
                month=0,
                priority=priority,
                service=service,
                target_url=gap.get("target_url"),
                cluster_id=gap.get("cluster_id"),
                rationale=(
                    f"{decision.value.replace('_', ' ').capitalize()}: "
                    f"{gap.get('decision_reason') or 'see the content gap decision'} "
                    + (f"Serves the '{service}' service. " if service else "")
                    + f"Primary intent {intent.primary.value}."
                ).strip(),
                evidence_ids=list(gap.get("evidence_ids") or []),
            )
        )

    candidates.sort(key=lambda i: (PHASE_ORDER.get(i.decision, 3), -i.priority, i.topic))
    slots = months * capacity_per_month
    for index, item in enumerate(candidates):
        if index < slots:
            item.month = index // capacity_per_month + 1
            roadmap.items.append(item)
        else:
            roadmap.backlog.append(item)
    return roadmap


__all__ = ["PRIORITY_FORMULA", "Roadmap", "RoadmapItem", "build_roadmap"]
