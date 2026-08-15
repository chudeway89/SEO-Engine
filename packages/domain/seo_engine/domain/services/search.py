"""Keyword, cluster and SERP persistence."""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.domain.models.search import (
    Keyword,
    KeywordMetricRecord,
    SearchIntentRecord,
    SearchQuestionRecord,
    SERPResultRecord,
    SERPSnapshotRecord,
)
from seo_engine.domain.models.search import (
    KeywordCluster as KeywordClusterRow,
)
from seo_engine.domain.repositories import repository_for
from seo_engine.events.bus import emit
from seo_engine.permissions.rbac import P_RESEARCH_RUN, Principal
from seo_engine.schemas.events import EventType
from seo_engine.schemas.search import (
    KeywordCluster,
    KeywordRecord,
    SearchQuestion,
    SERPSnapshot,
)
from sqlalchemy.ext.asyncio import AsyncSession

KeywordRepository = repository_for(Keyword)
ClusterRepository = repository_for(KeywordClusterRow)
MetricRepository = repository_for(KeywordMetricRecord)
IntentRepository = repository_for(SearchIntentRecord)
QuestionRepository = repository_for(SearchQuestionRecord)
SnapshotRepository = repository_for(SERPSnapshotRecord)
SERPResultRepository = repository_for(SERPResultRecord)


class SearchService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.keywords = KeywordRepository(session, principal.tenant_id)
        self.clusters = ClusterRepository(session, principal.tenant_id)
        self.metrics = MetricRepository(session, principal.tenant_id)
        self.intents = IntentRepository(session, principal.tenant_id)
        self.questions = QuestionRepository(session, principal.tenant_id)
        self.snapshots = SnapshotRepository(session, principal.tenant_id)
        self.results = SERPResultRepository(session, principal.tenant_id)

    async def store(
        self,
        brand_id: uuid.UUID,
        records: list[KeywordRecord],
        clusters: list[KeywordCluster],
    ) -> dict[str, int]:
        """Upsert keywords and clusters for a brand."""
        self.principal.require(P_RESEARCH_RUN)

        cluster_ids: dict[str, uuid.UUID] = {}
        for cluster in clusters:
            existing = await self.clusters.find_one(
                KeywordClusterRow.brand_id == brand_id,
                KeywordClusterRow.head_keyword == cluster.head_keyword,
            )
            if existing is None:
                existing = self.clusters.add(
                    KeywordClusterRow(
                        brand_id=brand_id,
                        label=cluster.label,
                        head_keyword=cluster.head_keyword,
                        intent=cluster.intent.as_dict(),
                        keyword_count=len(cluster.keywords),
                        opportunity_score=cluster.opportunity_score,
                        coverage=cluster.coverage,
                        mapped_urls=cluster.mapped_urls,
                        recommended_decision=(
                            cluster.recommended_decision.value
                            if cluster.recommended_decision
                            else None
                        ),
                    )
                )
                await self.session.flush()
            else:
                existing.label = cluster.label
                existing.intent = cluster.intent.as_dict()
                existing.keyword_count = len(cluster.keywords)
                existing.opportunity_score = cluster.opportunity_score
            cluster_ids[cluster.id] = existing.id

        stored = 0
        for record in records:
            existing = await self.keywords.find_one(
                Keyword.brand_id == brand_id,
                Keyword.normalised == record.normalised,
                Keyword.country == (record.country or ""),
            )
            fields = {
                "keyword": record.keyword,
                "language": record.language,
                "source": record.source,
                "is_branded": record.is_branded,
                "is_local": record.is_local,
                "is_question": record.is_question,
                "intent": record.intent.as_dict(),
                "primary_intent": record.intent.primary.value,
                "score_breakdown": record.score.model_dump(mode="json"),
                "opportunity_score": record.score.opportunity_score,
                "cluster_id": cluster_ids.get(record.cluster_id or ""),
                "mapped_url": record.mapped_url,
                "mapping_confidence": record.mapping_confidence,
            }
            if existing is None:
                row = self.keywords.add(
                    Keyword(
                        brand_id=brand_id,
                        normalised=record.normalised,
                        country=record.country or "",
                        **fields,
                    )
                )
                await self.session.flush()
            else:
                row = existing
                for key, value in fields.items():
                    setattr(row, key, value)

            await self.metrics.delete_where(KeywordMetricRecord.keyword_id == row.id)
            for metric in record.metrics:
                self.metrics.add(
                    KeywordMetricRecord(
                        keyword_id=row.id,
                        metric_name=metric.name,
                        value=metric.value,
                        unit=metric.unit,
                        provenance=metric.provenance.value,
                        source=metric.source,
                        note=metric.note,
                        observed_at=metric.observed_at,
                    )
                )
            self.intents.add(
                SearchIntentRecord(
                    keyword_id=row.id,
                    distribution=record.intent.as_dict(),
                    primary_intent=record.intent.primary.value,
                    confidence=record.intent.primary_probability,
                    classifier="lexical_v1",
                    rationale="Lexical signal classification over the query string.",
                )
            )
            stored += 1

        await self.session.flush()
        await emit(
            self.session,
            EventType.KEYWORD_RESEARCH_COMPLETED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="brand",
            aggregate_id=str(brand_id),
            payload={"keywords": stored, "clusters": len(clusters)},
        )
        return {"keywords": stored, "clusters": len(clusters)}

    async def list_keywords(
        self, brand_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> list[Keyword]:
        return list(
            await self.keywords.list(
                Keyword.brand_id == brand_id,
                limit=limit,
                offset=offset,
                order_by=Keyword.opportunity_score.desc(),
            )
        )

    async def list_clusters(
        self, brand_id: uuid.UUID, *, limit: int = 100
    ) -> list[KeywordClusterRow]:
        return list(
            await self.clusters.list(
                KeywordClusterRow.brand_id == brand_id,
                limit=limit,
                order_by=KeywordClusterRow.opportunity_score.desc(),
            )
        )

    async def store_questions(self, brand_id: uuid.UUID, questions: list[SearchQuestion]) -> int:
        from seo_engine.engines.keywords.pipeline import normalise

        stored = 0
        for question in questions:
            normalised = normalise(question.question)
            if await self.questions.exists(
                SearchQuestionRecord.brand_id == brand_id,
                SearchQuestionRecord.normalised == normalised,
            ):
                continue
            self.questions.add(
                SearchQuestionRecord(
                    brand_id=brand_id,
                    question=question.question,
                    normalised=normalised,
                    source=question.source,
                    provenance=question.provenance.value,
                    intent=question.intent.as_dict(),
                    answered_by_url=question.answered_by_url,
                )
            )
            stored += 1
        await self.session.flush()
        return stored

    async def store_snapshot(
        self, brand_id: uuid.UUID, snapshot: SERPSnapshot
    ) -> SERPSnapshotRecord:
        record = self.snapshots.add(
            SERPSnapshotRecord(
                brand_id=brand_id,
                query=snapshot.query,
                engine=snapshot.engine,
                country=snapshot.country,
                device=snapshot.device,
                provider=snapshot.provider,
                provenance=snapshot.provenance.value,
                available=snapshot.available,
                unavailable_reason=snapshot.unavailable_reason,
                features=snapshot.features,
                observed_at=snapshot.observed_at,
            )
        )
        await self.session.flush()
        for item in snapshot.results:
            self.results.add(
                SERPResultRecord(
                    snapshot_id=record.id,
                    position=item.position,
                    url=item.url,
                    domain=item.domain,
                    title=item.title,
                    snippet=item.snippet,
                    result_type=item.result_type,
                )
            )
        await self.session.flush()
        return record

    async def keyword_summary(self, brand_id: uuid.UUID) -> dict[str, Any]:
        keywords = await self.list_keywords(brand_id, limit=1000)
        intents: dict[str, int] = {}
        for keyword in keywords:
            if keyword.primary_intent:
                intents[keyword.primary_intent] = intents.get(keyword.primary_intent, 0) + 1
        return {
            "total": len(keywords),
            "mapped": sum(1 for k in keywords if k.mapped_url),
            "branded": sum(1 for k in keywords if k.is_branded),
            "intent_distribution": intents,
        }


__all__ = ["SearchService"]
