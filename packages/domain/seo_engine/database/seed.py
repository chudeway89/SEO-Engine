"""Seed the demonstration tenant.

Run with::

    python -m seo_engine.database.seed            # create the demo tenant
    python -m seo_engine.database.seed --reset     # delete it first, then recreate

It creates one organisation, one owner user, and the demonstration brand from
:mod:`seo_engine.domain.seed.demo` — a health-category diagnostics business with
services, audiences, a competitor, prohibited claims and a connected pair of
development-mode integrations.

Every figure the demo later shows is produced at runtime: measured by a
provider, computed from a crawl, or labelled synthetic by a development adapter.
The seed itself contains no metrics — only the brand's own account of its
business (Rule 2: no fake dashboards).
"""

from __future__ import annotations

import argparse
import asyncio

from seo_engine.domain.models.identity import Tenant, TenantUser, User
from seo_engine.domain.repositories import repository_for
from seo_engine.domain.seed.demo import DEMO_OBJECTIVE, build_demo_brand, scenario_summary
from seo_engine.observability.logging import configure_logging, get_logger
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import Role
from seo_engine.shared.db import dispose_engine, session_scope
from seo_engine.shared.security import hash_password
from sqlalchemy import select

log = get_logger(__name__)

DEMO_EMAIL = "demo-owner@example.com"
DEMO_ORG = "Demo Organisation"
DEMO_PASSWORD = "demo-password-change-me"


async def _delete_existing(session) -> bool:
    user = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    if user is None:
        return False
    memberships = (
        await session.execute(select(TenantUser).where(TenantUser.user_id == user.id))
    ).scalars()
    tenant_ids = {m.tenant_id for m in memberships}
    for tenant_id in tenant_ids:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is not None:
            # ON DELETE CASCADE on tenant_id removes every owned row with it.
            await session.delete(tenant)
    await session.delete(user)
    await session.flush()
    return True


async def seed(*, reset: bool) -> dict:
    async with session_scope() as session:
        if reset:
            removed = await _delete_existing(session)
            if removed:
                log.info("demo_tenant_removed")

        existing = (
            await session.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()
        if existing is not None:
            raise SystemExit(
                "the demo tenant already exists; pass --reset to recreate it, "
                "or log in as demo-owner@example.com"
            )

        tenant = Tenant(name=DEMO_ORG, slug="demo-organisation", status="active")
        user = User(
            email=DEMO_EMAIL,
            name="Demo Owner",
            password_hash=hash_password(DEMO_PASSWORD),
            auth_provider="password",
            status="active",
        )
        session.add_all([tenant, user])
        await session.flush()
        session.add(
            TenantUser(tenant_id=tenant.id, user_id=user.id, role=Role.OWNER, is_default=True)
        )
        await session.flush()

        principal = Principal.build(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.OWNER
        )
        scenario = await build_demo_brand(
            session, principal, name="Acme Diagnostics", connect_integrations=True
        )
        summary = scenario_summary(scenario)

    # A tiny sanity check: the repository refuses to read another tenant's rows.
    repo_count = None
    async with session_scope() as session:
        from seo_engine.domain.models.brand import Brand

        principal = Principal.build(
            user_id=user.id, tenant_id=tenant.id, email=user.email, role=Role.OWNER
        )
        repo_count = await repository_for(Brand)(session, principal.tenant_id).count()

    return {
        **summary,
        "login": {"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        "brands_visible_to_tenant": repo_count,
    }


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Seed the SEO Engine demo tenant.")
    parser.add_argument(
        "--reset", action="store_true", help="delete the existing demo tenant first"
    )
    args = parser.parse_args()

    async def _run() -> dict:
        try:
            return await seed(reset=args.reset)
        finally:
            await dispose_engine()

    summary = asyncio.run(_run())

    print("\nDemo tenant ready.\n")
    print(f"  Organisation : {DEMO_ORG}")
    print(f"  Login        : {summary['login']['email']} / {summary['login']['password']}")
    print(f"  Brand        : {summary['brand']}  ({summary['brand_id']})")
    print(f"  Website      : {summary['website']}")
    print(f"  Integrations : {', '.join(summary['connected_providers'])} (development adapter)")
    print(f'  Try          : POST a mission with objective "{DEMO_OBJECTIVE}"')
    print()


if __name__ == "__main__":
    main()
