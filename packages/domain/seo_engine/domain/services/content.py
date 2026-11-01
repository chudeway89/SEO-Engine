"""Content production persistence: briefs, research, sources, assets, versions,
evaluations, derivatives and repairs.

The content agents never touch these tables directly. They go through this
service, which carries the principal's tenant and permissions like every other
domain service, and which enforces the invariants the content pipeline rests on:

* **Versions are immutable.** A change is a new version; the previous one is
  never overwritten, so every evaluation stays attached to the text it judged.
* **A source is verified only if the platform fetched it.** Nothing here can
  promote a model-suggested citation to a verified one.
* **Approval is a human decision.** The instance handed to an agent run is built
  with ``acting_as_agent=True`` and refuses to approve or publish content. An
  agent can move a draft to review; only a person can approve it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any

from seo_engine.domain.models.content import (
    ContentAsset,
    ContentBriefRecord,
    ContentEvaluationRecord,
    ContentRepair,
    ContentRepresentation,
    ContentResearchRecord,
    ContentSource,
    ContentVersion,
)
from seo_engine.domain.repositories import repository_for
from seo_engine.events.bus import emit
from seo_engine.observability.audit import record_audit
from seo_engine.permissions.rbac import (
    P_CONTENT_DRAFT,
    P_CONTENT_PUBLISH,
    P_CONTENT_READ,
    Principal,
)
from seo_engine.schemas.content import (
    ContentBrief,
    ContentDraft,
    ContentEvaluation,
    ContentSection,
    InternalLinkTarget,
    RepurposedAsset,
)
from seo_engine.schemas.enums import (
    ContentAssetType,
    ContentDecision,
    ContentStatus,
    RiskCategory,
    SourceTier,
)
from seo_engine.schemas.events import EventType
from seo_engine.schemas.evidence import SourceReference
from seo_engine.shared.errors import ConflictError, PermissionDeniedError
from seo_engine.shared.ids import utcnow
from sqlalchemy.ext.asyncio import AsyncSession

AssetRepository = repository_for(ContentAsset)
VersionRepository = repository_for(ContentVersion)
BriefRepository = repository_for(ContentBriefRecord)
ResearchRepository = repository_for(ContentResearchRecord)
SourceRepository = repository_for(ContentSource)
EvaluationRepository = repository_for(ContentEvaluationRecord)
RepresentationRepository = repository_for(ContentRepresentation)
RepairRepository = repository_for(ContentRepair)

#: The editorial lifecycle. Anything not listed is not a legal transition.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ContentStatus.DRAFT.value: frozenset({ContentStatus.IN_REVIEW.value, "archived"}),
    ContentStatus.IN_REVIEW.value: frozenset(
        {ContentStatus.DRAFT.value, ContentStatus.APPROVED.value, "archived"}
    ),
    ContentStatus.APPROVED.value: frozenset(
        {ContentStatus.DRAFT.value, ContentStatus.PUBLISHED.value, "archived"}
    ),
    ContentStatus.PUBLISHED.value: frozenset({ContentStatus.DRAFT.value, "archived"}),
    "archived": frozenset(),
}

#: Transitions only a person may make.
HUMAN_ONLY_TRANSITIONS = frozenset({ContentStatus.APPROVED.value, ContentStatus.PUBLISHED.value})

#: Evaluation types the pipeline records, so a gate can find the right one.
EVALUATION_QUALITY = "quality_evaluation"
EVALUATION_GATE = "quality_gate"
EVALUATION_POLICY = "policy_review"


def content_hash(text: str) -> str:
    normalised = " ".join((text or "").lower().split())
    return hashlib.sha256(normalised.encode()).hexdigest()


class ContentService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        acting_as_agent: bool = False,
    ) -> None:
        self.session = session
        self.principal = principal
        self.acting_as_agent = acting_as_agent
        tenant = principal.tenant_id
        self.assets = AssetRepository(session, tenant)
        self.versions = VersionRepository(session, tenant)
        self.briefs = BriefRepository(session, tenant)
        self.research = ResearchRepository(session, tenant)
        self.sources = SourceRepository(session, tenant)
        self.evaluations = EvaluationRepository(session, tenant)
        self.representations = RepresentationRepository(session, tenant)
        self.repairs = RepairRepository(session, tenant)

    # ------------------------------------------------------------------
    # Briefs
    # ------------------------------------------------------------------
    async def save_brief(
        self,
        brand_id: uuid.UUID,
        brief: ContentBrief,
        *,
        opportunity_id: uuid.UUID | None = None,
        recommendation_id: uuid.UUID | None = None,
        content_asset_id: uuid.UUID | None = None,
        created_by_agent: str | None = None,
    ) -> ContentBriefRecord:
        """Store a brief. Re-briefing the same topic revises the open brief."""
        self.principal.require(P_CONTENT_DRAFT)
        existing = await self.briefs.find_one(
            ContentBriefRecord.brand_id == brand_id,
            ContentBriefRecord.title == brief.title,
            ContentBriefRecord.status == "draft",
        )
        body = brief.model_dump(mode="json")
        if existing is not None:
            existing.brief = body
            existing.decision = brief.decision.value
            existing.evidence_ids = list(brief.evidence_ids)
            existing.created_by_agent = created_by_agent or existing.created_by_agent
            if content_asset_id is not None:
                existing.content_asset_id = content_asset_id
            await self.session.flush()
            return existing

        record = self.briefs.add(
            ContentBriefRecord(
                brand_id=brand_id,
                content_asset_id=content_asset_id,
                opportunity_id=opportunity_id,
                recommendation_id=recommendation_id,
                title=brief.title,
                decision=brief.decision.value,
                brief=body,
                status="draft",
                created_by_agent=created_by_agent,
                evidence_ids=list(brief.evidence_ids),
            )
        )
        await self.session.flush()
        await emit(
            self.session,
            EventType.CONTENT_BRIEF_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="content_brief",
            aggregate_id=str(record.id),
            actor_type="agent" if created_by_agent else "user",
            actor_id=created_by_agent or str(self.principal.user_id),
            payload={"title": brief.title, "decision": brief.decision.value},
        )
        return record

    async def get_brief(self, brief_id: uuid.UUID) -> ContentBriefRecord:
        self.principal.require(P_CONTENT_READ)
        return await self.briefs.get_or_raise(brief_id)

    async def list_briefs(
        self, brand_id: uuid.UUID, *, status: str | None = None, limit: int = 50
    ) -> list[ContentBriefRecord]:
        self.principal.require(P_CONTENT_READ)
        filters: list[Any] = [ContentBriefRecord.brand_id == brand_id]
        if status:
            filters.append(ContentBriefRecord.status == status)
        return list(
            await self.briefs.list(
                *filters, limit=limit, order_by=ContentBriefRecord.created_at.desc()
            )
        )

    @staticmethod
    def brief_contract(record: ContentBriefRecord) -> ContentBrief:
        return ContentBrief.model_validate(record.brief)

    async def link_brief_to_asset(self, brief_id: uuid.UUID, asset_id: uuid.UUID) -> None:
        record = await self.briefs.get_or_raise(brief_id)
        record.content_asset_id = asset_id
        record.status = "in_production"
        await self.session.flush()

    # ------------------------------------------------------------------
    # Research and sources
    # ------------------------------------------------------------------
    async def save_research(
        self,
        brand_id: uuid.UUID,
        *,
        topic: str,
        brief_id: uuid.UUID | None = None,
        questions: Sequence[str] = (),
        entities: Sequence[str] = (),
        findings: Sequence[dict[str, Any]] = (),
        competitor_coverage: dict[str, Any] | None = None,
        created_by_agent: str | None = None,
    ) -> ContentResearchRecord:
        self.principal.require(P_CONTENT_DRAFT)
        record = self.research.add(
            ContentResearchRecord(
                brand_id=brand_id,
                brief_id=brief_id,
                topic=topic,
                questions=list(questions),
                entities=list(entities),
                findings=list(findings),
                competitor_coverage=competitor_coverage or {},
                created_by_agent=created_by_agent,
            )
        )
        await self.session.flush()
        return record

    async def latest_research(
        self, brand_id: uuid.UUID, *, topic: str | None = None
    ) -> ContentResearchRecord | None:
        self.principal.require(P_CONTENT_READ)
        filters: list[Any] = [ContentResearchRecord.brand_id == brand_id]
        if topic:
            filters.append(ContentResearchRecord.topic == topic)
        rows = await self.research.list(
            *filters, limit=1, order_by=ContentResearchRecord.created_at.desc()
        )
        return rows[0] if rows else None

    async def add_sources(
        self,
        brand_id: uuid.UUID,
        sources: Sequence[SourceReference],
        *,
        research_id: uuid.UUID | None = None,
        content_asset_id: uuid.UUID | None = None,
    ) -> int:
        """Record sources, once per URL per brand. Returns how many were new."""
        self.principal.require(P_CONTENT_DRAFT)
        added = 0
        for source in sources:
            existing = await self.sources.find_one(
                ContentSource.brand_id == brand_id, ContentSource.url == source.url
            )
            if existing is not None:
                # Verification can only ever be gained by a fetch, never lost by
                # a later unverified mention of the same URL.
                existing.verified = existing.verified or source.verified
                existing.tier = source.tier.value
                existing.reliability = source.reliability
                if source.supports_claim and not existing.supports_claim:
                    existing.supports_claim = source.supports_claim
                continue
            self.sources.add(
                ContentSource(
                    brand_id=brand_id,
                    research_id=research_id,
                    content_asset_id=content_asset_id,
                    url=source.url,
                    title=source.title,
                    publisher=source.publisher,
                    tier=source.tier.value,
                    reliability=source.reliability,
                    supports_claim=source.supports_claim,
                    verified=source.verified,
                    published_at=source.published_at,
                    retrieved_at=source.retrieved_at,
                )
            )
            added += 1
        await self.session.flush()
        return added

    async def list_sources(self, brand_id: uuid.UUID, *, limit: int = 200) -> list[ContentSource]:
        self.principal.require(P_CONTENT_READ)
        return list(
            await self.sources.list(
                ContentSource.brand_id == brand_id,
                limit=limit,
                order_by=ContentSource.reliability.desc(),
            )
        )

    @staticmethod
    def source_contract(row: ContentSource) -> SourceReference:
        return SourceReference(
            url=row.url,
            title=row.title,
            publisher=row.publisher,
            published_at=row.published_at,
            retrieved_at=row.retrieved_at,
            tier=SourceTier(row.tier),
            supports_claim=row.supports_claim,
            reliability=row.reliability,
            verified=row.verified,
        )

    # ------------------------------------------------------------------
    # Assets and versions
    # ------------------------------------------------------------------
    async def create_asset(
        self,
        brand_id: uuid.UUID,
        *,
        title: str,
        asset_type: ContentAssetType | str = ContentAssetType.ARTICLE,
        slug: str | None = None,
        url: str | None = None,
        website_id: uuid.UUID | None = None,
        page_id: uuid.UUID | None = None,
        risk_category: RiskCategory | str = RiskCategory.GENERAL,
        primary_keyword: str | None = None,
        cluster_id: uuid.UUID | None = None,
        canonical_source_asset_id: uuid.UUID | None = None,
        is_synthetic: bool = False,
    ) -> ContentAsset:
        self.principal.require(P_CONTENT_DRAFT)
        if slug:
            existing = await self.assets.find_one(
                ContentAsset.brand_id == brand_id,
                ContentAsset.slug == slug,
                ContentAsset.status != "archived",
            )
            if existing is not None:
                return existing
        record = self.assets.add(
            ContentAsset(
                brand_id=brand_id,
                website_id=website_id,
                page_id=page_id,
                asset_type=ContentAssetType(asset_type).value,
                title=title,
                slug=slug,
                url=url,
                canonical_url=url,
                status=ContentStatus.DRAFT.value,
                risk_category=RiskCategory(risk_category).value,
                primary_keyword=primary_keyword,
                cluster_id=cluster_id,
                canonical_source_asset_id=canonical_source_asset_id,
                is_synthetic=is_synthetic,
            )
        )
        await self.session.flush()
        return record

    async def add_version(
        self,
        asset: ContentAsset,
        draft: ContentDraft,
        *,
        change_summary: str,
        created_by_agent: str | None = None,
        brief_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContentVersion:
        """Append a new immutable version and point the asset at it."""
        self.principal.require(P_CONTENT_DRAFT)
        if asset.status == ContentStatus.PUBLISHED.value or asset.status == "archived":
            raise ConflictError(
                "a published or archived asset cannot take a new draft version directly; "
                "move it back to draft first",
                {"asset_id": str(asset.id), "status": asset.status},
            )
        body = draft.body_markdown or "\n\n".join(s.body for s in draft.sections)
        number = asset.current_version + 1
        version = self.versions.add(
            ContentVersion(
                content_asset_id=asset.id,
                version=number,
                title=draft.title,
                meta_description=draft.meta_description,
                body_markdown=body,
                sections=[s.model_dump(mode="json") for s in draft.sections],
                word_count=draft.word_count or len(body.split()),
                change_summary=change_summary,
                synthesis_mode=draft.synthesis_mode,
                created_by_agent=created_by_agent,
                created_by_user=None if created_by_agent else self.principal.user_id,
                brief_id=brief_id,
                metadata_json={
                    "slug": draft.slug,
                    "internal_links": [
                        link.model_dump(mode="json") for link in draft.internal_links
                    ],
                    "cited_sources": [s.model_dump(mode="json") for s in draft.cited_sources],
                    "entities": list(draft.entities),
                    "schema_recommendation": draft.schema_recommendation,
                    "cta": draft.cta,
                    "unverified_claims": list(draft.unverified_claims),
                    **(metadata or {}),
                },
            )
        )
        asset.current_version = number
        asset.title = draft.title
        asset.content_hash = content_hash(body)
        if asset.status != ContentStatus.DRAFT.value:
            # Any change sends the asset back through review.
            asset.status = ContentStatus.DRAFT.value
        await self.session.flush()
        await emit(
            self.session,
            EventType.CONTENT_CREATED if number == 1 else EventType.CONTENT_UPDATED,
            tenant_id=self.principal.tenant_id,
            brand_id=asset.brand_id,
            aggregate_type="content_asset",
            aggregate_id=str(asset.id),
            actor_type="agent" if created_by_agent else "user",
            actor_id=created_by_agent or str(self.principal.user_id),
            payload={"version": number, "synthesis_mode": draft.synthesis_mode},
        )
        return version

    async def get_asset(self, asset_id: uuid.UUID) -> ContentAsset:
        self.principal.require(P_CONTENT_READ)
        return await self.assets.get_or_raise(asset_id)

    async def list_assets(
        self,
        brand_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ContentAsset]:
        self.principal.require(P_CONTENT_READ)
        filters: list[Any] = [ContentAsset.brand_id == brand_id]
        if status:
            filters.append(ContentAsset.status == status)
        return list(
            await self.assets.list(*filters, limit=limit, order_by=ContentAsset.created_at.desc())
        )

    async def latest_version(self, asset_id: uuid.UUID) -> ContentVersion | None:
        self.principal.require(P_CONTENT_READ)
        rows = await self.versions.list(
            ContentVersion.content_asset_id == asset_id,
            limit=1,
            order_by=ContentVersion.version.desc(),
        )
        return rows[0] if rows else None

    async def list_versions(self, asset_id: uuid.UUID) -> list[ContentVersion]:
        self.principal.require(P_CONTENT_READ)
        return list(
            await self.versions.list(
                ContentVersion.content_asset_id == asset_id, order_by=ContentVersion.version
            )
        )

    @staticmethod
    def draft_contract(version: ContentVersion) -> ContentDraft:
        meta = version.metadata_json or {}
        return ContentDraft(
            title=version.title,
            meta_description=version.meta_description,
            slug=meta.get("slug") or "untitled",
            sections=[ContentSection.model_validate(s) for s in version.sections or []],
            body_markdown=version.body_markdown,
            word_count=version.word_count,
            internal_links=[
                InternalLinkTarget.model_validate(link) for link in meta.get("internal_links", [])
            ],
            cited_sources=[
                SourceReference.model_validate(s) for s in meta.get("cited_sources", [])
            ],
            entities=list(meta.get("entities", [])),
            schema_recommendation=meta.get("schema_recommendation"),
            cta=meta.get("cta"),
            unverified_claims=list(meta.get("unverified_claims", [])),
            synthesis_mode=version.synthesis_mode,
        )

    async def content_hashes(
        self, brand_id: uuid.UUID, *, exclude_asset_id: uuid.UUID | None = None
    ) -> set[str]:
        """Hashes of the brand's other assets, for duplicate detection."""
        rows = await self.assets.list(ContentAsset.brand_id == brand_id, limit=1000)
        return {row.content_hash for row in rows if row.content_hash and row.id != exclude_asset_id}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def set_status(
        self, asset_id: uuid.UUID, status: ContentStatus | str, *, reason: str
    ) -> ContentAsset:
        """Move an asset through the editorial lifecycle.

        Approval and publication are human decisions: an agent-scoped service
        refuses them outright, whatever permission the operator holds.
        """
        target = ContentStatus(status).value if status != "archived" else "archived"
        asset = await self.assets.get_or_raise(asset_id)
        if target in HUMAN_ONLY_TRANSITIONS:
            if self.acting_as_agent and target == ContentStatus.APPROVED.value:
                raise PermissionDeniedError(
                    "content approval is a human decision; an agent cannot approve content",
                    {"asset_id": str(asset_id)},
                )
            self.principal.require(P_CONTENT_PUBLISH)
        else:
            self.principal.require(P_CONTENT_DRAFT)

        allowed = ALLOWED_TRANSITIONS.get(asset.status, frozenset())
        if target not in allowed:
            raise ConflictError(
                f"content cannot move from {asset.status} to {target}",
                {"asset_id": str(asset_id), "from": asset.status, "to": target},
            )
        previous = asset.status
        asset.status = target
        await self.session.flush()
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action=f"content.{target}",
            resource_type="content_asset",
            resource_id=str(asset.id),
            actor_type="agent" if self.acting_as_agent else "user",
            actor_id=str(self.principal.user_id),
            actor_label=("agent on behalf of " if self.acting_as_agent else "")
            + self.principal.email,
            brand_id=asset.brand_id,
            reason=reason,
            before_state={"status": previous},
            after_state={"status": target},
        )
        return asset

    async def approve(self, asset_id: uuid.UUID, *, note: str = "") -> ContentAsset:
        """A person approves the current version for publication."""
        asset = await self.assets.get_or_raise(asset_id)
        current = await self.latest_version(asset_id)
        # The verdict must be for the version being approved: a pass recorded
        # against an earlier version says nothing about the text now current.
        gate = (
            await self.latest_evaluation(
                asset_id, evaluation_type=EVALUATION_GATE, version_id=current.id
            )
            if current is not None
            else None
        )
        if gate is None or not gate.passed:
            raise ConflictError(
                "content can only be approved after its current version has passed the "
                "quality gate",
                {"asset_id": str(asset_id), "version": asset.current_version},
            )
        return await self.set_status(asset.id, ContentStatus.APPROVED, reason=note or "approved")

    async def mark_published(
        self,
        asset_id: uuid.UUID,
        *,
        url: str | None,
        external_ref: dict[str, Any],
    ) -> ContentAsset:
        """Record that an approved asset was published through the CMS adapter."""
        self.principal.require(P_CONTENT_PUBLISH)
        asset = await self.assets.get_or_raise(asset_id)
        if asset.status != ContentStatus.APPROVED.value:
            raise ConflictError(
                "only approved content can be marked published",
                {"asset_id": str(asset_id), "status": asset.status},
            )
        asset.status = ContentStatus.PUBLISHED.value
        asset.published_at = utcnow()
        asset.external_ref = {**(asset.external_ref or {}), **external_ref}
        if url:
            asset.url = url
        await self.session.flush()
        await emit(
            self.session,
            EventType.CONTENT_PUBLISHED,
            tenant_id=self.principal.tenant_id,
            brand_id=asset.brand_id,
            aggregate_type="content_asset",
            aggregate_id=str(asset.id),
            payload={"url": url, "mode": external_ref.get("mode")},
        )
        return asset

    # ------------------------------------------------------------------
    # Evaluations
    # ------------------------------------------------------------------
    async def record_evaluation(
        self,
        asset_id: uuid.UUID,
        evaluation: ContentEvaluation,
        *,
        version_id: uuid.UUID | None,
        evaluation_type: str = EVALUATION_QUALITY,
        evaluated_by_agent: str | None = None,
    ) -> ContentEvaluationRecord:
        self.principal.require(P_CONTENT_READ)
        asset = await self.assets.get_or_raise(asset_id)
        record = self.evaluations.add(
            ContentEvaluationRecord(
                content_asset_id=asset_id,
                content_version_id=version_id,
                evaluation_type=evaluation_type,
                overall_score=evaluation.overall_score,
                passed=evaluation.passed,
                criteria=[c.model_dump(mode="json") for c in evaluation.criteria],
                blocking_failures=list(evaluation.blocking_failures),
                warnings=list(evaluation.warnings),
                requires_human_review=evaluation.requires_human_review,
                evaluated_by_agent=evaluated_by_agent,
            )
        )
        await self.session.flush()
        await emit(
            self.session,
            EventType.CONTENT_REVIEWED,
            tenant_id=self.principal.tenant_id,
            brand_id=asset.brand_id,
            aggregate_type="content_asset",
            aggregate_id=str(asset_id),
            actor_type="agent" if evaluated_by_agent else "user",
            actor_id=evaluated_by_agent or str(self.principal.user_id),
            payload={
                "evaluation_type": evaluation_type,
                "passed": evaluation.passed,
                "score": evaluation.overall_score,
            },
        )
        return record

    async def latest_evaluation(
        self,
        asset_id: uuid.UUID,
        *,
        evaluation_type: str | None = None,
        version_id: uuid.UUID | None = None,
    ) -> ContentEvaluationRecord | None:
        filters: list[Any] = [ContentEvaluationRecord.content_asset_id == asset_id]
        if evaluation_type:
            filters.append(ContentEvaluationRecord.evaluation_type == evaluation_type)
        if version_id:
            filters.append(ContentEvaluationRecord.content_version_id == version_id)
        rows = await self.evaluations.list(
            *filters, limit=1, order_by=ContentEvaluationRecord.created_at.desc()
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Derivatives and repairs
    # ------------------------------------------------------------------
    async def save_representations(
        self, asset_id: uuid.UUID, derivatives: Sequence[RepurposedAsset]
    ) -> list[ContentRepresentation]:
        """Store derivatives; an unpublished derivative for a platform is replaced."""
        self.principal.require(P_CONTENT_DRAFT)
        await self.assets.get_or_raise(asset_id)
        saved: list[ContentRepresentation] = []
        for item in derivatives:
            existing = await self.representations.find_one(
                ContentRepresentation.content_asset_id == asset_id,
                ContentRepresentation.platform == item.platform,
                ContentRepresentation.status == "draft",
            )
            fields = {
                "audience": item.audience,
                "objective": item.objective,
                "format": item.format,
                "tone": item.tone,
                "cta": item.cta,
                "body": item.body,
                "canonical_source_url": item.canonical_source_url,
            }
            if existing is not None:
                for key, value in fields.items():
                    setattr(existing, key, value)
                saved.append(existing)
                continue
            saved.append(
                self.representations.add(
                    ContentRepresentation(
                        content_asset_id=asset_id, platform=item.platform, status="draft", **fields
                    )
                )
            )
        await self.session.flush()
        return saved

    async def list_representations(self, asset_id: uuid.UUID) -> list[ContentRepresentation]:
        self.principal.require(P_CONTENT_READ)
        return list(
            await self.representations.list(ContentRepresentation.content_asset_id == asset_id)
        )

    async def record_repair(
        self,
        asset_id: uuid.UUID,
        *,
        issue: str,
        repair_type: str,
        detail: str = "",
        evaluation_id: uuid.UUID | None = None,
        performed_by_agent: str | None = None,
    ) -> ContentRepair:
        self.principal.require(P_CONTENT_DRAFT)
        record = self.repairs.add(
            ContentRepair(
                content_asset_id=asset_id,
                evaluation_id=evaluation_id,
                issue=issue,
                repair_type=repair_type,
                detail=detail,
                applied=False,
                performed_by_agent=performed_by_agent,
            )
        )
        await self.session.flush()
        return record

    async def list_repairs(self, asset_id: uuid.UUID) -> list[ContentRepair]:
        self.principal.require(P_CONTENT_READ)
        return list(await self.repairs.list(ContentRepair.content_asset_id == asset_id))


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EVALUATION_GATE",
    "EVALUATION_POLICY",
    "EVALUATION_QUALITY",
    "HUMAN_ONLY_TRANSITIONS",
    "ContentDecision",
    "ContentService",
    "content_hash",
]
