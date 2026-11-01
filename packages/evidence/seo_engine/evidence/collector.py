"""Evidence collection and persistence.

The collector is handed to every agent run.  Agents record what they *saw*
through it, and the resulting references are what recommendations cite.  Because
the collector assigns the reference, an agent cannot cite evidence it never
recorded — the :class:`ResultValidator` checks exactly that.
"""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.domain.models.decision import Evidence, EvidenceRelationship
from seo_engine.domain.repositories import repository_for
from seo_engine.schemas.enums import (
    OBSERVED_EVIDENCE_TYPES,
    DataProvenance,
    EvidenceType,
    SourceTier,
)
from seo_engine.schemas.evidence import EvidenceRecord
from seo_engine.shared.ids import new_ref, utcnow
from sqlalchemy.ext.asyncio import AsyncSession

EvidenceRepository = repository_for(Evidence)
RelationshipRepository = repository_for(EvidenceRelationship)


class EvidenceCollector:
    """Accumulates evidence during a run and persists it atomically."""

    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        brand_id: uuid.UUID | None = None,
        agent_id: str | None = None,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.brand_id = brand_id
        self.agent_id = agent_id
        self.agent_run_id = agent_run_id
        self.repo = EvidenceRepository(session, tenant_id)
        self.relationships = RelationshipRepository(session, tenant_id)
        self._collected: list[EvidenceRecord] = []

    # ------------------------------------------------------------------
    @property
    def collected(self) -> list[EvidenceRecord]:
        return list(self._collected)

    @property
    def refs(self) -> list[str]:
        return [e.id for e in self._collected]

    def observe(
        self,
        *,
        evidence_type: EvidenceType | str,
        source: str,
        observation: str,
        reference: str = "",
        data: dict[str, Any] | None = None,
        confidence: float = 1.0,
        provenance: DataProvenance | str | None = None,
        source_tier: SourceTier | str | None = None,
    ) -> EvidenceRecord:
        """Record something the system measured."""
        resolved_type = EvidenceType(evidence_type)
        if provenance is None:
            provenance = (
                DataProvenance.OBSERVED
                if resolved_type in OBSERVED_EVIDENCE_TYPES
                else DataProvenance.INFERRED
            )
        record = EvidenceRecord(
            id=new_ref("ev"),
            type=resolved_type,
            source=source,
            reference=reference,
            observation=observation,
            data=data or {},
            confidence=confidence,
            observed_at=utcnow(),
            provenance=DataProvenance(provenance),
            source_tier=SourceTier(source_tier) if source_tier else None,
        )
        self._collected.append(record)
        return record

    def infer(
        self,
        *,
        source: str,
        conclusion: str,
        data: dict[str, Any] | None = None,
        confidence: float = 0.6,
        derived_from: list[str] | None = None,
    ) -> EvidenceRecord:
        """Record a conclusion drawn from observations, marked as such."""
        payload = dict(data or {})
        if derived_from:
            payload["derived_from"] = derived_from
        return self.observe(
            evidence_type=EvidenceType.MODEL_INFERENCE,
            source=source,
            observation=conclusion,
            data=payload,
            confidence=min(confidence, 0.95),
            provenance=DataProvenance.INFERRED,
        )

    # ------------------------------------------------------------------
    async def persist(self, records: list[EvidenceRecord] | None = None) -> list[Evidence]:
        """Write evidence rows.  Idempotent per reference within a tenant."""
        to_write = records if records is not None else self._collected
        stored: list[Evidence] = []
        for record in to_write:
            existing = await self.repo.find_one(Evidence.ref == record.id)
            if existing is not None:
                stored.append(existing)
                continue
            row = self.repo.add(
                Evidence(
                    ref=record.id,
                    brand_id=self.brand_id,
                    evidence_type=record.type.value,
                    source=record.source,
                    source_ref=record.reference,
                    observation=record.observation,
                    structured_data=record.data,
                    confidence=record.confidence,
                    provenance=record.provenance.value,
                    source_tier=record.source_tier.value if record.source_tier else None,
                    is_observation=record.is_observation,
                    agent_id=self.agent_id,
                    agent_run_id=self.agent_run_id,
                    observed_at=record.observed_at,
                )
            )
            stored.append(row)
        await self.session.flush()
        return stored

    async def link(
        self, evidence_ref: str, *, entity_type: str, entity_id: str, relationship: str = "supports"
    ) -> EvidenceRelationship | None:
        row = await self.repo.find_one(Evidence.ref == evidence_ref)
        if row is None:
            return None
        link = self.relationships.add(
            EvidenceRelationship(
                evidence_id=row.id,
                entity_type=entity_type,
                entity_id=entity_id,
                relationship=relationship,
            )
        )
        await self.session.flush()
        return link

    async def load(self, refs: list[str]) -> list[EvidenceRecord]:
        """Rehydrate stored evidence for a downstream agent or the UI."""
        if not refs:
            return []
        rows = await self.repo.list(Evidence.ref.in_(refs))
        return [
            EvidenceRecord(
                id=row.ref,
                type=EvidenceType(row.evidence_type),
                source=row.source,
                reference=row.source_ref,
                observation=row.observation,
                data=row.structured_data,
                confidence=row.confidence,
                observed_at=row.observed_at,
                provenance=DataProvenance(row.provenance),
                source_tier=SourceTier(row.source_tier) if row.source_tier else None,
            )
            for row in rows
        ]

    async def for_brand(self, brand_id: uuid.UUID, *, limit: int = 200) -> list[Evidence]:
        return list(
            await self.repo.list(
                Evidence.brand_id == brand_id,
                limit=limit,
                order_by=Evidence.observed_at.desc(),
            )
        )


__all__ = ["EvidenceCollector"]
