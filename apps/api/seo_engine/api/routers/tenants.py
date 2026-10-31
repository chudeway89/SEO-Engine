"""Tenant and membership management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from seo_engine.api import serialize
from seo_engine.api.deps import PrincipalDep, SessionDep
from seo_engine.api.envelope import envelope
from seo_engine.domain.services.identity import IdentityService
from seo_engine.schemas.enums import Role

router = APIRouter(prefix="/tenant", tags=["tenant"])


class InviteRequest(BaseModel):
    email: EmailStr
    name: str = Field(default="", max_length=200)
    role: Role = Role.EDITOR


class RoleChange(BaseModel):
    user_id: uuid.UUID
    role: Role


@router.get("")
async def get_tenant(session: SessionDep, principal: PrincipalDep, request: Request) -> dict:
    tenant = await IdentityService(session).get_tenant(principal)
    return envelope(serialize.tenant(tenant), request_id=request.state.request_id)


@router.get("/members")
async def list_members(session: SessionDep, principal: PrincipalDep, request: Request) -> dict:
    rows = await IdentityService(session).list_members(principal)
    return envelope(
        [serialize.membership(m, user) for m, user in rows],
        request_id=request.state.request_id,
    )


@router.post("/members", status_code=201)
async def invite_member(
    body: InviteRequest, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    membership = await IdentityService(session).invite_member(
        principal, email=body.email, name=body.name, role=body.role
    )
    return envelope(serialize.membership(membership), request_id=request.state.request_id)


@router.patch("/members/role")
async def change_role(
    body: RoleChange, session: SessionDep, principal: PrincipalDep, request: Request
) -> dict:
    membership = await IdentityService(session).change_role(
        principal, user_id=body.user_id, role=body.role
    )
    return envelope(serialize.membership(membership), request_id=request.state.request_id)
