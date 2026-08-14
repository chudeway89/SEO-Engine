"""Domain services.

Agents and API routes reach data only through these services (Build
Specification rule 4: "no direct database access from agents").
"""

from __future__ import annotations

from seo_engine.domain.services.brand import BrandService_ as BrandService
from seo_engine.domain.services.identity import IdentityService, RegistrationResult
from seo_engine.domain.services.website import WebsiteService

__all__ = [
    "BrandService",
    "IdentityService",
    "RegistrationResult",
    "WebsiteService",
]
