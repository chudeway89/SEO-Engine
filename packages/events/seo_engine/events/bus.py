"""Internal event bus.

Implementation follows the Build Specification §33: a PostgreSQL event store as
the durable record, with in-process subscribers for reaction.  Redis pub/sub can
be layered on for cross-process fan-out without changing publishers, and Kafka
is explicitly *not* introduced in the MVP.

Events are append-only and always tenant-stamped.  A handler failure never
breaks the publisher: the event is already durable, and the failure is recorded.
"""

from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from seo_engine.domain.models.observability import EventRecord
from seo_engine.observability.logging import get_logger
from seo_engine.observability.metrics import counter
from seo_engine.schemas.events import DomainEvent
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

EventHandler = Callable[[DomainEvent], Awaitable[None] | None]


class EventBus:
    """Publishes domain events and dispatches them to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._wildcard: list[EventHandler] = []

    # -- subscription ----------------------------------------------------
    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._wildcard.append(handler)

    def handlers_for(self, event_type: str) -> list[EventHandler]:
        return [*self._handlers.get(event_type, []), *self._wildcard]

    def clear(self) -> None:
        self._handlers.clear()
        self._wildcard.clear()

    # -- publication -----------------------------------------------------
    async def publish(
        self,
        session: AsyncSession,
        event: DomainEvent,
        *,
        dispatch: bool = True,
    ) -> EventRecord:
        """Persist the event, then dispatch it.

        Persistence happens first and unconditionally: the event store is the
        system of record, and a handler bug must not lose history.
        """
        record = EventRecord(
            event_ref=event.event_id,
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            brand_id=event.brand_id,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            entity_id=event.entity_id,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
            schema_version=event.schema_version,
            occurred_at=event.timestamp,
            published=False,
        )
        session.add(record)
        await session.flush()

        counter("events_published_total", event_type=event.event_type)

        if dispatch:
            await self._dispatch(event)
            record.published = True

        return record

    async def _dispatch(self, event: DomainEvent) -> None:
        for handler in self.handlers_for(event.event_type):
            name = getattr(handler, "__name__", repr(handler))
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                counter(
                    "event_handler_failures_total",
                    event_type=event.event_type,
                    handler=name,
                )
                log.error(
                    "event_handler_failed",
                    event_type=event.event_type,
                    event_id=event.event_id,
                    handler=name,
                    error=str(exc),
                )


_bus = EventBus()


def get_event_bus() -> EventBus:
    return _bus


async def emit(
    session: AsyncSession,
    event_type: str,
    *,
    tenant_id: Any,
    brand_id: Any = None,
    aggregate_type: str = "system",
    aggregate_id: str | None = None,
    entity_id: str | None = None,
    actor_type: str = "system",
    actor_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> EventRecord:
    """Convenience publisher used across the domain services."""
    from seo_engine.shared.ids import new_ref

    event = DomainEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        brand_id=brand_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        correlation_id=correlation_id or new_ref("corr"),
        causation_id=causation_id,
        payload=payload or {},
    )
    return await _bus.publish(session, event)


__all__ = ["EventBus", "EventHandler", "emit", "get_event_bus"]
