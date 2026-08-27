"""Tenant-safe core domain and in-memory development adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class AccessDeniedError(Exception):
    """Raised without disclosing whether another tenant owns a resource."""


class InvalidTransitionError(Exception):
    pass


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    user_id: UUID
    role: str
    request_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class TenantRecord:
    id: UUID
    tenant_id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Brand(TenantRecord):
    name: str = ""


class MissionState(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    MONITORING = "MONITORING"
    ADAPTING = "ADAPTING"
    ACHIEVED = "ACHIEVED"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class Mission(TenantRecord):
    brand_id: UUID = field(default_factory=uuid4)
    objective: str = ""
    state: MissionState = MissionState.CREATED


class TaskState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Task(TenantRecord):
    mission_id: UUID = field(default_factory=uuid4)
    title: str = ""
    dependencies: frozenset[UUID] = frozenset()
    state: TaskState = TaskState.PENDING


@dataclass(frozen=True)
class DomainEvent(TenantRecord):
    event_type: str = ""
    entity_id: UUID = field(default_factory=uuid4)
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence(TenantRecord):
    evidence_type: str = "OBSERVATION"
    source: str = ""
    observation: str = ""
    confidence: float = 1.0


class InMemoryRepository:
    """Explicitly tenant-scoped adapter; production persistence will implement the same boundary."""

    def __init__(self) -> None:
        self.brands: dict[UUID, Brand] = {}
        self.missions: dict[UUID, Mission] = {}
        self.tasks: dict[UUID, Task] = {}
        self.events: list[DomainEvent] = []
        self.evidence: dict[UUID, Evidence] = {}

    @staticmethod
    def _owned(ctx: TenantContext, record: TenantRecord | None) -> TenantRecord:
        if record is None or record.tenant_id != ctx.tenant_id:
            raise AccessDeniedError("resource is not accessible")
        return record

    def add_brand(self, ctx: TenantContext, name: str) -> Brand:
        if not name.strip():
            raise ValueError("brand name is required")
        brand = Brand(id=uuid4(), tenant_id=ctx.tenant_id, name=name.strip())
        self.brands[brand.id] = brand
        self._event(ctx, "brand.created", brand.id, {"name": brand.name})
        return brand

    def get_brand(self, ctx: TenantContext, brand_id: UUID) -> Brand:
        return self._owned(ctx, self.brands.get(brand_id))  # type: ignore[return-value]

    def add_mission(self, ctx: TenantContext, brand_id: UUID, objective: str) -> Mission:
        self.get_brand(ctx, brand_id)
        if not objective.strip():
            raise ValueError("mission objective is required")
        mission = Mission(
            id=uuid4(), tenant_id=ctx.tenant_id, brand_id=brand_id, objective=objective.strip()
        )
        self.missions[mission.id] = mission
        self._event(ctx, "mission.created", mission.id, {"objective": mission.objective})
        return mission

    def add_task(
        self, ctx: TenantContext, mission_id: UUID, title: str, dependencies: set[UUID] | None = None
    ) -> Task:
        self._owned(ctx, self.missions.get(mission_id))
        deps = frozenset(dependencies or ())
        for dependency in deps:
            task = self._owned(ctx, self.tasks.get(dependency))
            if not isinstance(task, Task) or task.mission_id != mission_id:
                raise ValueError("dependencies must belong to the same mission")
        created = Task(
            id=uuid4(), tenant_id=ctx.tenant_id, mission_id=mission_id, title=title, dependencies=deps
        )
        self.tasks[created.id] = created
        return created

    def ready_tasks(self, ctx: TenantContext, mission_id: UUID) -> list[Task]:
        self._owned(ctx, self.missions.get(mission_id))
        completed = {
            task.id
            for task in self.tasks.values()
            if task.tenant_id == ctx.tenant_id and task.state == TaskState.COMPLETED
        }
        return [
            task
            for task in self.tasks.values()
            if task.tenant_id == ctx.tenant_id
            and task.mission_id == mission_id
            and task.state == TaskState.PENDING
            and task.dependencies <= completed
        ]

    def complete_task(self, ctx: TenantContext, task_id: UUID) -> Task:
        task = self._owned(ctx, self.tasks.get(task_id))
        assert isinstance(task, Task)
        if task not in self.ready_tasks(ctx, task.mission_id):
            raise InvalidTransitionError("task dependencies are incomplete")
        completed = Task(**{**task.__dict__, "state": TaskState.COMPLETED})
        self.tasks[task.id] = completed
        self._event(ctx, "task.completed", task.id, {})
        return completed

    def add_evidence(
        self, ctx: TenantContext, evidence_type: str, source: str, observation: str, confidence: float
    ) -> Evidence:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        item = Evidence(
            id=uuid4(), tenant_id=ctx.tenant_id, evidence_type=evidence_type,
            source=source, observation=observation, confidence=confidence,
        )
        self.evidence[item.id] = item
        return item

    def get_evidence(self, ctx: TenantContext, evidence_id: UUID) -> Evidence:
        return self._owned(ctx, self.evidence.get(evidence_id))  # type: ignore[return-value]

    def _event(self, ctx: TenantContext, kind: str, entity_id: UUID, payload: dict[str, object]) -> None:
        self.events.append(DomainEvent(
            id=uuid4(), tenant_id=ctx.tenant_id, event_type=kind,
            entity_id=entity_id, payload=payload,
        ))
