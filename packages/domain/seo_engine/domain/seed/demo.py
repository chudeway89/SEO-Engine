"""The demonstration scenario.

One brand, described exactly the way a real customer would describe theirs, so
the canonical mission — *increase qualified organic leads* — has something true
to work from. Nothing here is a metric: the seed supplies the brand's own
account of its business, its website and its competitors, and every number in
the product is then either measured by a provider, computed from a crawl, or
explicitly labelled synthetic by a development adapter.

This module is imported both by the seed CLI and by the end-to-end test, so the
scenario a developer sees is the scenario the test asserts against.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from seo_engine.domain.models.brand import Brand
from seo_engine.domain.models.website import Website
from seo_engine.domain.services import BrandService
from seo_engine.domain.services.integration import IntegrationService
from seo_engine.domain.services.website import WebsiteService
from seo_engine.permissions.rbac import Principal
from seo_engine.schemas.enums import CompetitorType, IntegrationProvider, RiskCategory
from sqlalchemy.ext.asyncio import AsyncSession

DEMO_OBJECTIVE = "Increase qualified organic leads"
DEMO_DOMAIN = "acme.test"
DEMO_COMPETITOR_DOMAIN = "rival.test"


@dataclass(slots=True)
class DemoScenario:
    brand: Brand
    website: Website
    connected_providers: list[str]


async def build_demo_brand(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str | None = None,
    domain: str = DEMO_DOMAIN,
    connect_integrations: bool = True,
) -> DemoScenario:
    """Create the demonstration brand, website and competitors."""
    brands = BrandService(session, principal)
    websites = WebsiteService(session, principal)

    brand = await brands.create(
        name=name or f"Acme Diagnostics {uuid.uuid4().hex[:6]}",
        description=(
            "An accredited private laboratory offering DNA testing and prenatal "
            "screening to clinicians and to the public."
        ),
        industry="Clinical diagnostics",
        website=f"https://{domain}",
        country="GB",
        business_model="b2c_and_b2b",
        # Health content carries a higher approval bar. The demonstration brand
        # is deliberately in that category so the approval path is exercised.
        risk_category=RiskCategory.HEALTH,
    )

    await brands.add_goal(
        brand.id,
        goal_type="acquisition",
        description="Increase qualified organic leads from clinicians and self-referring patients",
        target_metric="qualified_organic_leads",
        timeframe="6 months",
        priority=1,
    )
    await brands.add_goal(
        brand.id,
        goal_type="visibility",
        description="Be found for prenatal screening questions before the booking decision",
        priority=2,
    )

    await brands.add_service(
        brand.id,
        name="DNA testing",
        description="Accredited paternity, relationship and ancestry DNA testing.",
        category="testing",
        keywords=["dna testing", "dna test", "paternity test"],
        landing_url=f"https://{domain}/services/dna-testing",
        priority=1,
        revenue_weight=2.0,
    )
    await brands.add_service(
        brand.id,
        name="Prenatal screening",
        description="Non-invasive prenatal screening for expectant parents.",
        category="testing",
        keywords=["prenatal screening", "nipt test"],
        landing_url=f"https://{domain}/services/prenatal-screening",
        priority=2,
        revenue_weight=1.5,
    )

    await brands.add_audience(
        brand.id,
        name="Expectant parents",
        description="Researching screening options before a clinical appointment.",
        pains=["worried about test accuracy", "unclear pricing", "long waiting times"],
        goals=["understand the options", "book quickly", "get an accredited result"],
        vocabulary=["nipt", "prenatal screening", "how much does a dna test cost", "is it safe"],
        stage="consideration",
        priority=1,
    )
    await brands.add_audience(
        brand.id,
        name="Referring clinicians",
        description="GPs and midwives choosing a laboratory to refer to.",
        pains=["turnaround times", "accreditation evidence", "sample logistics"],
        goals=["refer confidently", "get results fast"],
        vocabulary=["accredited laboratory", "ukas", "turnaround time", "referral"],
        stage="decision",
        priority=2,
    )

    await brands.add_location(
        brand.id,
        name="Manchester laboratory",
        country="GB",
        region="Greater Manchester",
        city="Manchester",
        is_primary=True,
    )

    await brands.add_competitor(
        brand.id,
        name="Rival Diagnostics",
        domain=DEMO_COMPETITOR_DOMAIN,
        competitor_types=[CompetitorType.BUSINESS, CompetitorType.SERP],
        priority=1,
        notes="Ranks for the cost and explainer questions this brand does not answer.",
    )

    await brands.set_voice_profile(
        brand.id,
        tone="Plain, calm and clinical. No pressure, no hype.",
        reading_level="GCSE",
        person="second",
        approved_terminology=["accredited", "screening", "laboratory"],
        forbidden_terminology=["guaranteed", "100% accurate", "risk-free"],
        style_rules=[
            "State what a test can and cannot tell you.",
            "Never imply a diagnosis.",
            "Name the accreditation rather than claiming quality in the abstract.",
        ],
    )

    # Claims: one that is true and evidenced, one that must never be published.
    approved = await brands.add_claim(
        brand.id,
        claim="Our laboratory is UKAS accredited for DNA testing.",
        source="UKAS certificate 1234",
        risk="medium",
    )
    await brands.approve_claim(approved.id)
    await brands.add_claim(
        brand.id,
        claim="Our tests are 100% accurate.",
        risk="high",
        is_prohibited=True,
    )

    website = await websites.add_website(
        brand.id,
        url=f"https://{domain}",
        cms="custom",
        crawl_frequency="weekly",
    )

    connected: list[str] = []
    if connect_integrations:
        integrations = IntegrationService(session, principal)
        for provider in (
            IntegrationProvider.GOOGLE_SEARCH_CONSOLE,
            IntegrationProvider.GOOGLE_ANALYTICS_4,
        ):
            connection = await integrations.connect(brand.id, provider)
            connected.append(connection.provider)

    await session.flush()
    return DemoScenario(brand=brand, website=website, connected_providers=connected)


def scenario_summary(scenario: DemoScenario) -> dict[str, Any]:
    return {
        "brand": scenario.brand.name,
        "brand_id": str(scenario.brand.id),
        "website": scenario.website.base_url,
        "website_id": str(scenario.website.id),
        "connected_providers": scenario.connected_providers,
        "objective": DEMO_OBJECTIVE,
    }


__all__ = [
    "DEMO_COMPETITOR_DOMAIN",
    "DEMO_DOMAIN",
    "DEMO_OBJECTIVE",
    "DemoScenario",
    "build_demo_brand",
    "scenario_summary",
]
