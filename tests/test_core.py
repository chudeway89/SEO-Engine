from uuid import uuid4

import pytest

from seo_engine.core import (
    AccessDeniedError,
    InMemoryRepository,
    InvalidTransitionError,
    TaskState,
    TenantContext,
)


def context(tenant_id=None):
    return TenantContext(tenant_id=tenant_id or uuid4(), user_id=uuid4(), role="OWNER")


def test_cross_tenant_access_is_denied_without_resource_disclosure():
    repository = InMemoryRepository()
    owner, attacker = context(), context()
    brand = repository.add_brand(owner, "Example")
    mission = repository.add_mission(owner, brand.id, "Improve organic acquisition")
    evidence = repository.add_evidence(owner, "CRAWL_RESULT", "https://example.test", "404", 1)

    for operation in (
        lambda: repository.get_brand(attacker, brand.id),
        lambda: repository.add_mission(attacker, brand.id, "steal"),
        lambda: repository.add_task(attacker, mission.id, "steal"),
        lambda: repository.get_evidence(attacker, evidence.id),
    ):
        with pytest.raises(AccessDeniedError, match="resource is not accessible"):
            operation()


def test_task_dependencies_gate_completion():
    repository = InMemoryRepository()
    ctx = context()
    mission = repository.add_mission(ctx, repository.add_brand(ctx, "Acme").id, "Audit site")
    crawl = repository.add_task(ctx, mission.id, "Crawl")
    analyse = repository.add_task(ctx, mission.id, "Analyse", {crawl.id})

    assert repository.ready_tasks(ctx, mission.id) == [crawl]
    with pytest.raises(InvalidTransitionError):
        repository.complete_task(ctx, analyse.id)
    assert repository.complete_task(ctx, crawl.id).state == TaskState.COMPLETED
    assert repository.ready_tasks(ctx, mission.id) == [analyse]


def test_events_are_tenant_scoped_and_append_oriented():
    repository = InMemoryRepository()
    ctx = context()
    brand = repository.add_brand(ctx, "Acme")
    repository.add_mission(ctx, brand.id, "Audit")
    assert [(event.tenant_id, event.event_type) for event in repository.events] == [
        (ctx.tenant_id, "brand.created"),
        (ctx.tenant_id, "mission.created"),
    ]
