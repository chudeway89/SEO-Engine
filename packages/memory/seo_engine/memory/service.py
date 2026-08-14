"""Memory service: store, retrieve, semantic search, update, forget.

Memory is strictly tenant-scoped.  Every query runs through
:class:`TenantScopedRepository`, and :meth:`MemoryService.search_semantic`
additionally re-asserts the tenant predicate on the raw vector query, because a
hand-written SQL path is exactly where isolation bugs hide.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from seo_engine.domain.models.memory import Memory, MemoryEmbedding
from seo_engine.domain.repositories import repository_for
from seo_engine.memory.embedding import get_embedder
from seo_engine.observability.logging import get_logger
from seo_engine.schemas.enums import MemoryScope, MemoryType
from seo_engine.shared.errors import ValidationError
from seo_engine.shared.ids import utcnow
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

MemoryRepository = repository_for(Memory)
EmbeddingRepository = repository_for(MemoryEmbedding)

#: Working memory is short-lived by design (Architecture Pack §22).
DEFAULT_TTL: dict[MemoryType, timedelta | None] = {
    MemoryType.WORKING: timedelta(days=2),
    MemoryType.BRAND_FACT: None,
    MemoryType.HISTORICAL: timedelta(days=365),
    MemoryType.OUTCOME: None,
    MemoryType.LEARNING: None,
    MemoryType.PREFERENCE: None,
}


@dataclass(slots=True)
class MemoryHit:
    memory: Memory
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.memory.id),
            "key": self.memory.key,
            "content": self.memory.content,
            "scope": self.memory.scope,
            "type": self.memory.memory_type,
            "confidence": self.memory.confidence,
            "source": self.memory.source,
            "structured": self.memory.structured,
            "conditions": self.memory.conditions,
            "relevance": round(self.score, 4),
            "created_at": self.memory.created_at.isoformat() if self.memory.created_at else None,
        }


class MemoryService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.repo = MemoryRepository(session, tenant_id)
        self.embeddings = EmbeddingRepository(session, tenant_id)
        self.embedder = get_embedder()

    # -- write -----------------------------------------------------------
    async def store(
        self,
        *,
        key: str,
        content: str,
        scope: MemoryScope | str = MemoryScope.BRAND,
        memory_type: MemoryType | str = MemoryType.BRAND_FACT,
        brand_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        source: str = "system",
        source_agent_id: str | None = None,
        confidence: float = 0.7,
        importance: float = 0.5,
        structured: dict[str, Any] | None = None,
        conditions: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        ttl: timedelta | None = None,
        embed: bool = True,
    ) -> Memory:
        if not content.strip():
            raise ValidationError("memory content must not be empty", {"key": key})

        scope = MemoryScope(scope)
        memory_type = MemoryType(memory_type)
        if scope in {MemoryScope.BRAND, MemoryScope.PROJECT} and brand_id is None:
            raise ValidationError("brand-scoped memory requires a brand_id", {"scope": scope.value})

        expires_at = None
        effective_ttl = ttl if ttl is not None else DEFAULT_TTL.get(memory_type)
        if effective_ttl is not None:
            expires_at = utcnow() + effective_ttl

        record = self.repo.add(
            Memory(
                scope=scope.value,
                memory_type=memory_type.value,
                brand_id=brand_id,
                project_id=project_id,
                mission_id=mission_id,
                task_id=task_id,
                key=key,
                content=content.strip(),
                structured=structured or {},
                source=source,
                source_agent_id=source_agent_id,
                confidence=confidence,
                importance=importance,
                conditions=conditions or [],
                evidence_refs=evidence_refs or [],
                expires_at=expires_at,
            )
        )
        await self.session.flush()

        if embed:
            await self._embed(record)
        return record

    async def _embed(self, record: Memory) -> None:
        vector = self.embedder.embed(f"{record.key}\n{record.content}")
        existing = await self.embeddings.find_one(
            MemoryEmbedding.memory_id == record.id,
            MemoryEmbedding.model == self.embedder.model,
        )
        if existing is not None:
            existing.embedding = vector
            existing.dimensions = self.embedder.dimensions
        else:
            self.embeddings.add(
                MemoryEmbedding(
                    memory_id=record.id,
                    model=self.embedder.model,
                    dimensions=self.embedder.dimensions,
                    embedding=vector,
                )
            )
        await self.session.flush()

    async def update(self, memory_id: uuid.UUID, **changes: Any) -> Memory:
        record = await self.repo.get_or_raise(memory_id)
        allowed = {
            "content",
            "structured",
            "confidence",
            "importance",
            "conditions",
            "evidence_refs",
            "expires_at",
        }
        rejected = set(changes) - allowed
        if rejected:
            raise ValidationError(
                "those memory fields cannot be updated", {"fields": sorted(rejected)}
            )
        for key, value in changes.items():
            setattr(record, key, value)
        await self.session.flush()
        if "content" in changes:
            await self._embed(record)
        return record

    async def forget(self, memory_id: uuid.UUID, *, hard: bool = False) -> None:
        """Soft-forget by default so the audit trail survives the deletion."""
        record = await self.repo.get_or_raise(memory_id)
        if hard:
            await self.embeddings.delete_where(MemoryEmbedding.memory_id == record.id)
            await self.repo.delete(record)
        else:
            record.is_active = False
            record.forgotten_at = utcnow()
        await self.session.flush()

    async def forget_expired(self) -> int:
        now = utcnow()
        return await self.repo.update_where(
            [
                Memory.is_active.is_(True),
                Memory.expires_at.is_not(None),
                Memory.expires_at < now,
            ],
            {"is_active": False, "forgotten_at": now},
        )

    # -- read ------------------------------------------------------------
    def _scope_filters(
        self,
        *,
        scopes: list[MemoryScope | str] | None,
        brand_id: uuid.UUID | None,
        mission_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
        memory_types: list[MemoryType | str] | None,
    ) -> list[Any]:
        criteria: list[Any] = [Memory.is_active.is_(True)]
        if scopes:
            criteria.append(Memory.scope.in_([MemoryScope(s).value for s in scopes]))
        if memory_types:
            criteria.append(Memory.memory_type.in_([MemoryType(t).value for t in memory_types]))
        if brand_id is not None:
            # Tenant- and platform-scoped memories are legitimately shared
            # across a tenant's brands; brand-scoped ones are not.
            criteria.append((Memory.brand_id == brand_id) | (Memory.brand_id.is_(None)))
        if mission_id is not None:
            criteria.append((Memory.mission_id == mission_id) | (Memory.mission_id.is_(None)))
        if task_id is not None:
            criteria.append((Memory.task_id == task_id) | (Memory.task_id.is_(None)))
        return criteria

    async def retrieve(
        self,
        *,
        scopes: list[MemoryScope | str] | None = None,
        brand_id: uuid.UUID | None = None,
        mission_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        memory_types: list[MemoryType | str] | None = None,
        key: str | None = None,
        limit: int = 50,
    ) -> list[Memory]:
        criteria = self._scope_filters(
            scopes=scopes,
            brand_id=brand_id,
            mission_id=mission_id,
            task_id=task_id,
            memory_types=memory_types,
        )
        if key:
            criteria.append(Memory.key == key)
        rows = await self.repo.list(*criteria, limit=limit, order_by=Memory.importance.desc())
        return list(rows)

    async def search_semantic(
        self,
        query: str,
        *,
        brand_id: uuid.UUID | None = None,
        scopes: list[MemoryScope | str] | None = None,
        memory_types: list[MemoryType | str] | None = None,
        limit: int = 10,
        min_similarity: float = 0.05,
    ) -> list[MemoryHit]:
        """Vector search over this tenant's memory only.

        The tenant predicate appears on both joined tables.  That is redundant
        by design: this is the one query in the system written by hand, and a
        redundant filter is cheaper than an isolation bug.
        """
        vector = self.embedder.embed(query)
        conditions = [
            "m.tenant_id = :tenant_id",
            "e.tenant_id = :tenant_id",
            "m.is_active = true",
            "e.model = :model",
        ]
        params: dict[str, Any] = {
            "tenant_id": self.tenant_id,
            "model": self.embedder.model,
            "query_vector": str(vector),
            "limit": limit,
        }
        if brand_id is not None:
            conditions.append("(m.brand_id = :brand_id OR m.brand_id IS NULL)")
            params["brand_id"] = brand_id
        if scopes:
            conditions.append("m.scope = ANY(:scopes)")
            params["scopes"] = [MemoryScope(s).value for s in scopes]
        if memory_types:
            conditions.append("m.memory_type = ANY(:memory_types)")
            params["memory_types"] = [MemoryType(t).value for t in memory_types]

        statement = text(
            f"""
            SELECT m.id, 1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity
            FROM memories m
            JOIN memory_embeddings e ON e.memory_id = m.id
            WHERE {" AND ".join(conditions)}
              AND (m.expires_at IS NULL OR m.expires_at > now())
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        )
        rows = (await self.session.execute(statement, params)).all()

        scored = {row[0]: float(row[1]) for row in rows if float(row[1]) >= min_similarity}
        if not scored:
            return []

        # Re-fetch through the tenant-scoped repository: even if the raw query
        # were wrong, nothing outside this tenant can be returned.
        found = await self.session.execute(
            self.repo.scoped(select(Memory).where(Memory.id.in_(list(scored))))
        )
        hits = [MemoryHit(memory=m, score=scored[m.id]) for m in found.scalars()]
        hits.sort(key=lambda h: h.score, reverse=True)

        for hit in hits:
            hit.memory.hit_count += 1
        await self.session.flush()
        return hits

    # -- outcome / learning ---------------------------------------------
    async def record_outcome(
        self,
        *,
        brand_id: uuid.UUID,
        action_summary: str,
        result_summary: str,
        metric: str,
        delta: float | None,
        window_days: int,
        confidence: float,
        conditions: list[str],
        mission_id: uuid.UUID | None = None,
        evidence_refs: list[str] | None = None,
    ) -> Memory:
        """Store an outcome as institutional memory.

        Architecture Pack §85: never generalise to "X always works".  The
        conditions under which the outcome was observed are stored with it and
        are part of the retrievable content.
        """
        condition_text = "; ".join(conditions) if conditions else "no conditions recorded"
        content = (
            f"Under these conditions ({condition_text}), {action_summary} "
            f"was followed by: {result_summary}. "
            f"Metric {metric} changed by {delta if delta is not None else 'an unmeasured amount'} "
            f"over {window_days} days."
        )
        return await self.store(
            key=f"outcome:{metric}",
            content=content,
            scope=MemoryScope.BRAND,
            memory_type=MemoryType.OUTCOME,
            brand_id=brand_id,
            mission_id=mission_id,
            source="outcome_engine",
            confidence=confidence,
            importance=0.8,
            structured={
                "metric": metric,
                "delta": delta,
                "window_days": window_days,
                "action": action_summary,
                "result": result_summary,
            },
            conditions=conditions,
            evidence_refs=evidence_refs or [],
        )


__all__ = ["DEFAULT_TTL", "MemoryHit", "MemoryService"]
