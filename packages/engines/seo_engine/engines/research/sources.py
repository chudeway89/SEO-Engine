"""Source tiering and claim coverage.

Implements the source trust hierarchy (Build Specification §55) as explicit,
inspectable rules over a source's domain. A tier says how much weight a source
can bear; it does not say the source is right. A source is ``verified`` only if
the platform itself fetched it — tiering a URL never verifies it.

Domains under reserved test TLDs (``.example``, ``.test``, ``.invalid``) are
always tier 6: they are synthetic by definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.schemas.enums import SOURCE_TIER_WEIGHT, SourceTier
from seo_engine.schemas.evidence import SourceReference

RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost")

#: Exact registrable domains with a known standing.
KNOWN_DOMAINS: dict[str, SourceTier] = {
    # Primary: regulators, official bodies, statutory registers.
    "nhs.uk": SourceTier.TIER_1_PRIMARY,
    "nice.org.uk": SourceTier.TIER_1_PRIMARY,
    "who.int": SourceTier.TIER_1_PRIMARY,
    "ukas.com": SourceTier.TIER_1_PRIMARY,
    "legislation.gov.uk": SourceTier.TIER_1_PRIMARY,
    "fda.gov": SourceTier.TIER_1_PRIMARY,
    "cdc.gov": SourceTier.TIER_1_PRIMARY,
    "nih.gov": SourceTier.TIER_1_PRIMARY,
    "europa.eu": SourceTier.TIER_1_PRIMARY,
    # Authoritative: peer-reviewed and institutional publishers.
    "pubmed.ncbi.nlm.nih.gov": SourceTier.TIER_2_AUTHORITATIVE,
    "ncbi.nlm.nih.gov": SourceTier.TIER_2_AUTHORITATIVE,
    "bmj.com": SourceTier.TIER_2_AUTHORITATIVE,
    "thelancet.com": SourceTier.TIER_2_AUTHORITATIVE,
    "nature.com": SourceTier.TIER_2_AUTHORITATIVE,
    "nejm.org": SourceTier.TIER_2_AUTHORITATIVE,
    "cochranelibrary.com": SourceTier.TIER_2_AUTHORITATIVE,
    "rcog.org.uk": SourceTier.TIER_2_AUTHORITATIVE,
    # Reputable secondary: established newsrooms and reference works.
    "bbc.co.uk": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    "bbc.com": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    "reuters.com": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    "theguardian.com": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    "ft.com": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    "britannica.com": SourceTier.TIER_3_REPUTABLE_SECONDARY,
    # Community: user-generated.
    "reddit.com": SourceTier.TIER_5_COMMUNITY,
    "quora.com": SourceTier.TIER_5_COMMUNITY,
    "mumsnet.com": SourceTier.TIER_5_COMMUNITY,
    "medium.com": SourceTier.TIER_5_COMMUNITY,
    "wikipedia.org": SourceTier.TIER_5_COMMUNITY,
}

#: Suffix rules, checked after exact matches.
SUFFIX_RULES: tuple[tuple[str, SourceTier], ...] = (
    (".gov.uk", SourceTier.TIER_1_PRIMARY),
    (".gov", SourceTier.TIER_1_PRIMARY),
    (".nhs.uk", SourceTier.TIER_1_PRIMARY),
    (".ac.uk", SourceTier.TIER_2_AUTHORITATIVE),
    (".edu", SourceTier.TIER_2_AUTHORITATIVE),
    (".org.uk", SourceTier.TIER_4_INDUSTRY),
    (".org", SourceTier.TIER_4_INDUSTRY),
)


@dataclass(slots=True)
class TierDecision:
    tier: SourceTier
    reliability: float
    rule: str


def registrable(host: str) -> str:
    return host.lower().removeprefix("www.").split(":")[0]


def tier_for_url(url: str, *, own_domain: str | None = None) -> TierDecision:
    host = registrable(urlparse(url).netloc or url)
    if not host or host.endswith(RESERVED_TLDS):
        return TierDecision(
            SourceTier.TIER_6_UNVERIFIED,
            SOURCE_TIER_WEIGHT[SourceTier.TIER_6_UNVERIFIED],
            "reserved or synthetic domain",
        )
    if own_domain and (
        host == registrable(own_domain) or host.endswith("." + registrable(own_domain))
    ):
        # The brand is the primary source for facts about itself, and only those.
        return TierDecision(
            SourceTier.TIER_1_PRIMARY,
            0.9,
            "the brand's own site: primary for claims about the brand only",
        )
    for domain, tier in KNOWN_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return TierDecision(tier, SOURCE_TIER_WEIGHT[tier], f"known domain {domain}")
    for suffix, tier in SUFFIX_RULES:
        if host.endswith(suffix):
            return TierDecision(tier, SOURCE_TIER_WEIGHT[tier], f"domain suffix {suffix}")
    return TierDecision(
        SourceTier.TIER_4_INDUSTRY,
        SOURCE_TIER_WEIGHT[SourceTier.TIER_4_INDUSTRY],
        "commercial or unclassified domain",
    )


def build_source(
    url: str,
    *,
    title: str,
    retrieved_at: datetime,
    verified: bool,
    own_domain: str | None = None,
    supports_claim: str | None = None,
    publisher: str | None = None,
) -> SourceReference:
    decision = tier_for_url(url, own_domain=own_domain)
    return SourceReference(
        url=url,
        title=title or url,
        publisher=publisher or registrable(urlparse(url).netloc) or None,
        retrieved_at=retrieved_at,
        tier=decision.tier,
        reliability=decision.reliability if verified else min(decision.reliability, 0.5),
        supports_claim=supports_claim,
        verified=verified,
    )


@dataclass(slots=True)
class ClaimCoverage:
    claim: str
    status: str  # "sourced" | "source_named_unverified" | "unsourced"
    sources: list[str]
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "claim": self.claim,
            "status": self.status,
            "sources": self.sources,
            "detail": self.detail,
        }


def claim_coverage(
    claims: list[tuple[str, str | None]], sources: list[SourceReference]
) -> list[ClaimCoverage]:
    """For each (claim, named source) pair, how well is it supported?

    A claim is ``sourced`` when a verified source of tier 1-3 supports it (by
    stated claim or by sharing most of its terms). A claim that only *names* a
    source the platform has not fetched is ``source_named_unverified``.
    """
    strong = [
        s
        for s in sources
        if s.verified
        and s.tier
        in {
            SourceTier.TIER_1_PRIMARY,
            SourceTier.TIER_2_AUTHORITATIVE,
            SourceTier.TIER_3_REPUTABLE_SECONDARY,
        }
    ]
    results: list[ClaimCoverage] = []
    for claim, named in claims:
        tokens = content_tokens(claim)
        supporting = [
            s.url
            for s in strong
            if (s.supports_claim and s.supports_claim.strip().lower() == claim.strip().lower())
            or (tokens and len(tokens & content_tokens(s.title)) / len(tokens) >= 0.6)
        ]
        if supporting:
            results.append(
                ClaimCoverage(claim, "sourced", supporting, "Supported by a verified source.")
            )
        elif named:
            results.append(
                ClaimCoverage(
                    claim,
                    "source_named_unverified",
                    [named],
                    f"The customer names '{named}' as the source; the platform has not "
                    "fetched or verified it.",
                )
            )
        else:
            results.append(
                ClaimCoverage(
                    claim,
                    "unsourced",
                    [],
                    "No source is recorded for this claim. It should not be published "
                    "until one is.",
                )
            )
    return results


__all__ = [
    "KNOWN_DOMAINS",
    "RESERVED_TLDS",
    "ClaimCoverage",
    "TierDecision",
    "build_source",
    "claim_coverage",
    "registrable",
    "tier_for_url",
]
