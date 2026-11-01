"""Brand graph endpoints.

The brand graph is customer-supplied truth — the one input the system never
invents. These endpoints are therefore plain CRUD over the brand domain
service; the only intelligence here is validation.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PageDep, PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope, page_meta
from seo_engine.domain.services import BrandService
from seo_engine.schemas.enums import CompetitorType, RiskCategory

router = APIRouter(prefix="/brands", tags=["brands"])


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    primary_language: str = "en"
    business_model: str | None = None
    risk_category: RiskCategory = RiskCategory.GENERAL


class BrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    business_model: str | None = None
    risk_category: RiskCategory | None = None


class GoalCreate(BaseModel):
    goal_type: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1)
    target_metric: str | None = None
    target_value: float | None = None
    timeframe: str | None = None
    priority: int = Field(default=3, ge=1, le=5)


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str | None = None
    keywords: list[str] = Field(default_factory=list)
    landing_url: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    revenue_weight: float = Field(default=1.0, ge=0)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str | None = None
    keywords: list[str] = Field(default_factory=list)


class AudienceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    pains: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    stage: str | None = None
    priority: int = Field(default=3, ge=1, le=5)


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = None
    region: str | None = None
    city: str | None = None
    is_primary: bool = False


class CompetitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)
    competitor_types: list[CompetitorType] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)
    notes: str = ""


class VoiceProfile(BaseModel):
    tone: str = ""
    reading_level: str | None = None
    person: str | None = None
    approved_terminology: list[str] = Field(default_factory=list)
    forbidden_terminology: list[str] = Field(default_factory=list)
    style_rules: list[str] = Field(default_factory=list)


class ClaimCreate(BaseModel):
    claim: str = Field(min_length=1)
    source: str | None = None
    risk: str = "low"
    is_prohibited: bool = False


def _service(session: Any, principal: Any) -> BrandService:
    return BrandService(session, principal)


@router.post("", status_code=201)
async def create_brand(
    body: BrandCreate, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    brand = await _service(session, principal).create(**body.model_dump())
    return envelope(serialize.brand(brand), request_id=request.state.request_id)


@router.get("")
async def list_brands(
    session: SessionDep, principal: PrincipalDep, page: PageDep, request: Request
) -> dict:
    service = _service(session, principal)
    brands = await service.list_brands(limit=page.limit, offset=page.offset)
    total = await service.count()
    return envelope(
        [serialize.brand(b) for b in brands],
        meta=page_meta(brands, limit=page.limit, offset=page.offset, total=total),
        request_id=request.state.request_id,
    )


@router.get("/{brand_id}")
async def get_brand(
    brand_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    brand = await _service(session, principal).get(brand_id)
    return envelope(serialize.brand(brand), request_id=request.state.request_id)


@router.patch("/{brand_id}")
async def update_brand(
    brand_id: uuid.UUID,
    body: BrandUpdate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    brand = await _service(session, principal).update(brand_id, **changes)
    return envelope(serialize.brand(brand), request_id=request.state.request_id)


@router.get("/{brand_id}/profile")
async def brand_profile(
    brand_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    profile = await _service(session, principal).profile(brand_id)
    return envelope(serialize.brand_profile(profile), request_id=request.state.request_id)


@router.post("/{brand_id}/goals", status_code=201)
async def add_goal(
    brand_id: uuid.UUID,
    body: GoalCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    goal = await _service(session, principal).add_goal(brand_id, **body.model_dump())
    return envelope({"id": str(goal.id)}, request_id=request.state.request_id)


@router.post("/{brand_id}/services", status_code=201)
async def add_brand_service(
    brand_id: uuid.UUID,
    body: ServiceCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    item = await _service(session, principal).add_service(brand_id, **body.model_dump())
    return envelope({"id": str(item.id)}, request_id=request.state.request_id)


@router.post("/{brand_id}/products", status_code=201)
async def add_product(
    brand_id: uuid.UUID,
    body: ProductCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    item = await _service(session, principal).add_product(brand_id, **body.model_dump())
    return envelope({"id": str(item.id)}, request_id=request.state.request_id)


@router.post("/{brand_id}/audiences", status_code=201)
async def add_audience(
    brand_id: uuid.UUID,
    body: AudienceCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    item = await _service(session, principal).add_audience(brand_id, **body.model_dump())
    return envelope({"id": str(item.id)}, request_id=request.state.request_id)


@router.post("/{brand_id}/locations", status_code=201)
async def add_location(
    brand_id: uuid.UUID,
    body: LocationCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    item = await _service(session, principal).add_location(brand_id, **body.model_dump())
    return envelope({"id": str(item.id)}, request_id=request.state.request_id)


@router.post("/{brand_id}/competitors", status_code=201)
async def add_competitor(
    brand_id: uuid.UUID,
    body: CompetitorCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    item = await _service(session, principal).add_competitor(
        brand_id,
        name=body.name,
        domain=body.domain,
        competitor_types=body.competitor_types or None,
        priority=body.priority,
        notes=body.notes,
    )
    return envelope(serialize.competitor(item), request_id=request.state.request_id)


@router.get("/{brand_id}/competitors")
async def list_competitors(
    brand_id: uuid.UUID, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    rows = await _service(session, principal).list_competitors(brand_id)
    return envelope([serialize.competitor(c) for c in rows], request_id=request.state.request_id)


@router.put("/{brand_id}/voice")
async def set_voice(
    brand_id: uuid.UUID,
    body: VoiceProfile,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    await _service(session, principal).set_voice_profile(brand_id, **body.model_dump())
    return envelope({"status": "saved"}, request_id=request.state.request_id)


@router.post("/{brand_id}/claims", status_code=201)
async def add_claim(
    brand_id: uuid.UUID,
    body: ClaimCreate,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    claim = await _service(session, principal).add_claim(brand_id, **body.model_dump())
    return envelope(serialize.claim(claim), request_id=request.state.request_id)


@router.post("/{brand_id}/claims/{claim_id}/approve")
async def approve_claim(
    brand_id: uuid.UUID,
    claim_id: uuid.UUID,
    session: SessionDep,
    principal: PrincipalDep,
    request: Request,
) -> dict:
    claim = await _service(session, principal).approve_claim(claim_id)
    return envelope(serialize.claim(claim), request_id=request.state.request_id)
