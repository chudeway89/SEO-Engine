"""Registration, login, token refresh and the current identity."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope
from seo_engine.domain.services.identity import IdentityService

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    name: str = Field(min_length=1, max_length=200)
    organisation_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, session: SessionDep, request: Request) -> dict:
    result = await IdentityService(session).register(
        email=body.email,
        password=body.password,
        name=body.name,
        organisation_name=body.organisation_name,
    )
    return envelope(
        {
            "user": serialize.user(result.user),
            "tenant": serialize.tenant(result.tenant),
            "tokens": serialize.tokens(result.tokens),
        },
        request_id=request.state.request_id,
    )


@router.post("/login")
async def login(body: LoginRequest, session: SessionDep, request: Request) -> dict:
    user, tenant, tokens = await IdentityService(session).login(
        email=body.email, password=body.password, tenant_slug=body.tenant_slug
    )
    return envelope(
        {
            "user": serialize.user(user),
            "tenant": serialize.tenant(tenant),
            "tokens": serialize.tokens(tokens),
        },
        request_id=request.state.request_id,
    )


@router.post("/refresh")
async def refresh(body: RefreshRequest, session: SessionDep, request: Request) -> dict:
    tokens = await IdentityService(session).refresh(body.refresh_token)
    return envelope({"tokens": serialize.tokens(tokens)}, request_id=request.state.request_id)


@router.get("/me")
async def me(principal: PrincipalDep, session: SessionDep, request: Request) -> dict:
    tenant = await IdentityService(session).get_tenant(principal)
    return envelope(
        {
            "user_id": str(principal.user_id),
            "email": principal.email,
            "role": principal.role.value,
            "permissions": sorted(principal.permissions),
            "tenant": serialize.tenant(tenant),
        },
        request_id=request.state.request_id,
    )
