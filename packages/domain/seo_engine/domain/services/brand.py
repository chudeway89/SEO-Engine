"""Brand service — the brand graph that gives every agent its business context."""

from __future__ import annotations

import uuid
from typing import Any

from seo_engine.domain.models.brand import (
    Brand,
    BrandAudience,
    BrandClaim,
    BrandCompetitor,
    BrandGoal,
    BrandLocation,
    BrandProduct,
    BrandService,
    BrandVoiceProfile,
    Project,
)
from seo_engine.domain.repositories import TenantScopedRepository, repository_for
from seo_engine.events.bus import emit
from seo_engine.observability.audit import record_audit
from seo_engine.permissions.rbac import P_BRAND_READ, P_BRAND_WRITE, Principal
from seo_engine.schemas.enums import CompetitorType, RiskCategory
from seo_engine.schemas.events import EventType
from seo_engine.shared.errors import ConflictError, ValidationError
from seo_engine.shared.ids import utcnow
from sqlalchemy.ext.asyncio import AsyncSession

BrandRepository = repository_for(Brand)


def _normalise_domain(value: str) -> str:
    """Reduce a user-supplied URL or host to a bare, comparable domain."""
    from urllib.parse import urlparse

    raw = (value or "").strip().lower()
    if not raw:
        raise ValidationError("a domain is required", {})
    if "//" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.netloc or parsed.path).split("/")[0].split("@")[-1].split(":")[0]
    host = host.removeprefix("www.")
    if not host or "." not in host:
        raise ValidationError("that does not look like a valid domain", {"domain": value})
    return host


class BrandService_:
    """Owns brands and every satellite entity that describes the business."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.brands: TenantScopedRepository[Brand] = BrandRepository(session, principal.tenant_id)

    # -- brands ----------------------------------------------------------
    async def create(
        self,
        *,
        name: str,
        description: str = "",
        industry: str | None = None,
        website: str | None = None,
        country: str | None = None,
        primary_language: str = "en",
        business_model: str | None = None,
        risk_category: RiskCategory | str = RiskCategory.GENERAL,
    ) -> Brand:
        self.principal.require(P_BRAND_WRITE)
        if not name.strip():
            raise ValidationError("brand name is required", {})

        from seo_engine.domain.services.identity import slugify

        slug = slugify(name)
        if await self.brands.exists(Brand.slug == slug):
            raise ConflictError("a brand with that name already exists", {"slug": slug})

        brand = self.brands.add(
            Brand(
                name=name.strip(),
                slug=slug,
                description=description,
                industry=industry,
                website=website,
                country=country,
                primary_language=primary_language,
                business_model=business_model,
                risk_category=RiskCategory(risk_category).value,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.BRAND_CREATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand.id,
            aggregate_type="brand",
            aggregate_id=str(brand.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"name": brand.name, "industry": brand.industry},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="brand.create",
            resource_type="brand",
            resource_id=str(brand.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=brand.id,
            after_state={"name": brand.name},
        )
        return brand

    async def get(self, brand_id: uuid.UUID) -> Brand:
        self.principal.require(P_BRAND_READ)
        return await self.brands.get_or_raise(brand_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[Brand]:
        self.principal.require(P_BRAND_READ)
        rows = await self.brands.list(limit=limit, offset=offset, order_by=Brand.created_at.desc())
        return list(rows)

    async def count(self) -> int:
        self.principal.require(P_BRAND_READ)
        return await self.brands.count()

    async def update(self, brand_id: uuid.UUID, **changes: Any) -> Brand:
        self.principal.require(P_BRAND_WRITE)
        brand = await self.brands.get_or_raise(brand_id)

        allowed = {
            "name",
            "description",
            "industry",
            "website",
            "country",
            "primary_language",
            "business_model",
            "risk_category",
            "status",
            "profile",
        }
        rejected = set(changes) - allowed
        if rejected:
            raise ValidationError("those fields cannot be updated", {"fields": sorted(rejected)})

        before = {key: getattr(brand, key) for key in changes}
        for key, value in changes.items():
            setattr(brand, key, value)
        await self.session.flush()

        await emit(
            self.session,
            EventType.BRAND_UPDATED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand.id,
            aggregate_type="brand",
            aggregate_id=str(brand.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"changed": sorted(changes)},
        )
        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="brand.update",
            resource_type="brand",
            resource_id=str(brand.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=brand.id,
            before_state=before,
            after_state=dict(changes),
        )
        return brand

    # -- satellites ------------------------------------------------------
    async def _child_repo(self, model: type) -> TenantScopedRepository[Any]:
        return repository_for(model)(self.session, self.principal.tenant_id)

    async def add_goal(self, brand_id: uuid.UUID, **fields: Any) -> BrandGoal:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandGoal)
        goal = repo.add(BrandGoal(brand_id=brand_id, **fields))
        await self.session.flush()
        return goal

    async def add_service(self, brand_id: uuid.UUID, **fields: Any) -> BrandService:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandService)
        item = repo.add(BrandService(brand_id=brand_id, **fields))
        await self.session.flush()
        return item

    async def add_product(self, brand_id: uuid.UUID, **fields: Any) -> BrandProduct:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandProduct)
        item = repo.add(BrandProduct(brand_id=brand_id, **fields))
        await self.session.flush()
        return item

    async def add_audience(self, brand_id: uuid.UUID, **fields: Any) -> BrandAudience:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandAudience)
        item = repo.add(BrandAudience(brand_id=brand_id, **fields))
        await self.session.flush()
        return item

    async def add_location(self, brand_id: uuid.UUID, **fields: Any) -> BrandLocation:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandLocation)
        item = repo.add(BrandLocation(brand_id=brand_id, **fields))
        await self.session.flush()
        return item

    async def add_competitor(
        self,
        brand_id: uuid.UUID,
        *,
        name: str,
        domain: str,
        competitor_types: list[CompetitorType | str] | None = None,
        priority: int = 3,
        discovered_via: str = "user",
        notes: str = "",
    ) -> BrandCompetitor:
        """Add a competitor.

        A business competitor is *not* assumed to be a search competitor: the
        type list is explicit, and defaults to business only.
        """
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)

        normalised = _normalise_domain(domain)
        repo = await self._child_repo(BrandCompetitor)
        if await repo.exists(
            BrandCompetitor.brand_id == brand_id, BrandCompetitor.domain == normalised
        ):
            raise ConflictError("that competitor is already tracked", {"domain": normalised})

        types = [CompetitorType(t).value for t in (competitor_types or [CompetitorType.BUSINESS])]
        competitor = repo.add(
            BrandCompetitor(
                brand_id=brand_id,
                name=name.strip(),
                domain=normalised,
                competitor_types=types,
                priority=priority,
                discovered_via=discovered_via,
                notes=notes,
            )
        )
        await self.session.flush()

        await emit(
            self.session,
            EventType.COMPETITOR_DISCOVERED,
            tenant_id=self.principal.tenant_id,
            brand_id=brand_id,
            aggregate_type="competitor",
            aggregate_id=str(competitor.id),
            actor_type="user",
            actor_id=str(self.principal.user_id),
            payload={"domain": normalised, "types": types, "discovered_via": discovered_via},
        )
        return competitor

    async def list_competitors(self, brand_id: uuid.UUID) -> list[BrandCompetitor]:
        self.principal.require(P_BRAND_READ)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandCompetitor)
        rows = await repo.list(
            BrandCompetitor.brand_id == brand_id, order_by=BrandCompetitor.priority
        )
        return list(rows)

    async def set_voice_profile(self, brand_id: uuid.UUID, **fields: Any) -> BrandVoiceProfile:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandVoiceProfile)
        existing = await repo.find_one(
            BrandVoiceProfile.brand_id == brand_id, BrandVoiceProfile.is_default.is_(True)
        )
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.session.flush()
            return existing
        profile = repo.add(BrandVoiceProfile(brand_id=brand_id, **fields))
        await self.session.flush()
        return profile

    # -- claims ----------------------------------------------------------
    async def add_claim(
        self,
        brand_id: uuid.UUID,
        *,
        claim: str,
        source: str | None = None,
        risk: str = "low",
        is_prohibited: bool = False,
    ) -> BrandClaim:
        """Register a claim.  It is unapproved until a human approves it."""
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(BrandClaim)
        record = repo.add(
            BrandClaim(
                brand_id=brand_id,
                claim=claim.strip(),
                source=source,
                risk=risk,
                is_prohibited=is_prohibited,
                status="prohibited" if is_prohibited else "draft",
                approved=False,
            )
        )
        await self.session.flush()
        return record

    async def approve_claim(self, claim_id: uuid.UUID) -> BrandClaim:
        self.principal.require(P_BRAND_WRITE)
        repo = await self._child_repo(BrandClaim)
        record = await repo.get_or_raise(claim_id)
        if record.is_prohibited:
            raise ValidationError("a prohibited claim cannot be approved", {})
        record.approved = True
        record.status = "approved"
        record.approved_by = self.principal.user_id
        record.approved_at = utcnow()
        await self.session.flush()

        await record_audit(
            self.session,
            tenant_id=self.principal.tenant_id,
            action="brand.approve_claim",
            resource_type="brand_claim",
            resource_id=str(record.id),
            actor_id=str(self.principal.user_id),
            actor_label=self.principal.email,
            brand_id=record.brand_id,
            reason="human approval of a commercial claim",
        )
        return record

    async def approved_claims(self, brand_id: uuid.UUID) -> list[BrandClaim]:
        """Content agents call this before writing commercial copy."""
        repo = await self._child_repo(BrandClaim)
        today = utcnow().date()
        rows = await repo.list(
            BrandClaim.brand_id == brand_id,
            BrandClaim.approved.is_(True),
            BrandClaim.is_prohibited.is_(False),
        )
        return [c for c in rows if c.expires_at is None or c.expires_at >= today]

    async def prohibited_claims(self, brand_id: uuid.UUID) -> list[BrandClaim]:
        repo = await self._child_repo(BrandClaim)
        rows = await repo.list(BrandClaim.brand_id == brand_id, BrandClaim.is_prohibited.is_(True))
        return list(rows)

    # -- projects --------------------------------------------------------
    async def create_project(self, brand_id: uuid.UUID, **fields: Any) -> Project:
        self.principal.require(P_BRAND_WRITE)
        await self.brands.get_or_raise(brand_id)
        repo = await self._child_repo(Project)
        project = repo.add(Project(brand_id=brand_id, **fields))
        await self.session.flush()
        return project

    # -- aggregate view --------------------------------------------------
    async def profile(self, brand_id: uuid.UUID) -> dict[str, Any]:
        """The full brand graph, as the agent context builder consumes it."""
        self.principal.require(P_BRAND_READ)
        brand = await self.brands.get_or_raise(brand_id)

        async def children(model: type, order: Any = None) -> list[Any]:
            repo = await self._child_repo(model)
            return list(await repo.list(model.brand_id == brand_id, order_by=order))

        return {
            "brand": brand,
            "goals": await children(BrandGoal, BrandGoal.priority),
            "services": await children(BrandService, BrandService.priority),
            "products": await children(BrandProduct),
            "audiences": await children(BrandAudience, BrandAudience.priority),
            "locations": await children(BrandLocation),
            "competitors": await children(BrandCompetitor, BrandCompetitor.priority),
            "claims": await self.approved_claims(brand_id),
            "prohibited_claims": await self.prohibited_claims(brand_id),
            "voice": await (await self._child_repo(BrandVoiceProfile)).find_one(
                BrandVoiceProfile.brand_id == brand_id
            ),
        }


__all__ = ["BrandRepository", "BrandService_"]
