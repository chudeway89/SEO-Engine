"""Agent memory: structured records plus pgvector embeddings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from seo_engine.schemas.enums import MemoryScope, MemoryType
from seo_engine.shared.db import (
    Base,
    SyntheticDataMixin,
    TenantOwnedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

#: Dimensionality of the built-in deterministic embedder.  Kept small so the
#: platform can do semantic retrieval with no external embedding provider; a
#: production embedding model plugs in behind MemoryService.embed().
EMBEDDING_DIM = 384


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, SyntheticDataMixin, Base):
    """A memory record.  ``tenant_id`` is never optional — Rule 10."""

    __tablename__ = "memories"

    scope: Mapped[str] = mapped_column(
        String(32), default=MemoryScope.BRAND, nullable=False, index=True
    )
    memory_type: Mapped[str] = mapped_column(
        String(32), default=MemoryType.BRAND_FACT, nullable=False, index=True
    )
    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="system", nullable=False)
    source_agent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    conditions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forgotten_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class MemoryEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (UniqueConstraint("memory_id", "model", name="uq_memory_embeddings_model"),)

    memory_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(120), default="hashing-v1", nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, default=EMBEDDING_DIM, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class KnowledgeNode(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    """Knowledge-graph entity (brand, topic, page, competitor, claim …)."""

    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "node_type", "key", name="uq_knowledge_nodes_key"),
    )

    brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(300), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="system", nullable=False)


class KnowledgeEdge(UUIDPrimaryKeyMixin, TimestampMixin, TenantOwnedMixin, Base):
    __tablename__ = "knowledge_edges"

    source_node_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = [
    "EMBEDDING_DIM",
    "KnowledgeEdge",
    "KnowledgeNode",
    "Memory",
    "MemoryEmbedding",
]
