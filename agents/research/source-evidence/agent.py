"""RES-006 — Source and Evidence Agent.

Builds the register of sources the brand's content may cite, and checks the
brand's approved claims against it.

Candidate sources come from two places the platform can actually see: URLs the
customer named as the source of an approved claim, and external pages the
brand's own site links to. Each is tiered by explicit domain rules (the source
trust hierarchy), and a bounded number are fetched. **Only a fetched source is
verified.** A URL that was named, linked or tiered but not fetched stays
unverified, however reputable its domain — tiering never verifies anything.

Fetched pages are untrusted external content: only their status and title are
kept, and nothing on them is treated as an instruction.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, website_domain
from seo_engine.engines.crawler.crawler import WebsiteCrawler, config_from_settings
from seo_engine.engines.research.sources import build_source, claim_coverage, tier_for_url
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import (
    HIGH_RISK_CATEGORIES,
    SOURCE_TIER_WEIGHT,
    DataProvenance,
    EvidenceType,
    SynthesisMode,
)
from seo_engine.schemas.evidence import SourceReference
from seo_engine.shared.ids import utcnow

_schemas = load_agent_module(__file__)
SourceEvidenceInput = _schemas.SourceEvidenceInput
SourceEvidenceOutput = _schemas.SourceEvidenceOutput


def _is_url(value: str | None) -> bool:
    return bool(value) and urlparse(str(value)).scheme in {"http", "https"}


class SourceEvidenceAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = SourceEvidenceInput.model_validate(context.inputs)
        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)

        # --- candidates the platform can actually see ------------------------
        candidates: dict[str, dict[str, Any]] = {}
        for claim, named in facts.approved_claims:
            if _is_url(named):
                candidates.setdefault(str(named), {"supports_claim": claim, "via": "claim_source"})
        if payload.website_id is not None:
            links = await context.service("websites").list_links(
                payload.website_id, internal_only=False
            )
            for link in links:
                if not link.is_internal and _is_url(link.target_url):
                    candidates.setdefault(
                        link.target_url, {"supports_claim": None, "via": "cited_by_brand_site"}
                    )

        if not candidates and not facts.approved_claims:
            workspace.limitation(
                "The brand has no approved claims and its site cites no external pages, so "
                "there were no sources to register."
            )
            return "No candidate sources were found to register."

        # --- verification by fetch -------------------------------------------
        ordered = sorted(
            candidates,
            key=lambda url: -SOURCE_TIER_WEIGHT[tier_for_url(url, own_domain=facts.domain).tier],
        )
        fetched: dict[str, tuple[bool, str]] = {}
        to_fetch = ordered[: payload.max_fetch]
        if to_fetch and workspace.note_unavailable_tool("crawler"):
            factory = context.services.get("crawler_factory")
            for url in to_fetch:
                host = urlparse(url).netloc
                config = config_from_settings(
                    max_pages=1, max_depth=0, allowed_domains=[host], use_sitemap=False
                )
                crawler = factory(config) if factory else WebsiteCrawler(config)
                try:
                    result = await crawler.crawl(url)
                except Exception as exc:  # the source is unreachable; it stays unverified
                    fetched[url] = (False, f"fetch failed ({type(exc).__name__})")
                    continue
                page = result.pages[0] if result.pages else None
                ok = page is not None and page.status_code == 200 and not page.error
                fetched[url] = (ok, (page.title or "") if page and ok else "")
        if len(ordered) > len(to_fetch):
            workspace.limitation(
                f"{len(ordered) - len(to_fetch)} candidate source(s) were not fetched within "
                "this run's bound and remain unverified."
            )

        now = utcnow()
        sources: list[SourceReference] = []
        for url in ordered:
            verified, title = fetched.get(url, (False, ""))
            sources.append(
                build_source(
                    url,
                    title=title or url,
                    retrieved_at=now,
                    verified=verified,
                    own_domain=facts.domain,
                    supports_claim=candidates[url]["supports_claim"],
                )
            )

        new_sources = await context.service("content").add_sources(payload.brand_id, sources)
        register = [
            context.service("content").source_contract(row)
            for row in await context.service("content").list_sources(payload.brand_id)
        ]
        coverage = claim_coverage(facts.approved_claims, register)

        tiers: dict[str, int] = {}
        for source in sources:
            tiers[source.tier.value] = tiers.get(source.tier.value, 0) + 1
        verified_count = sum(1 for s in sources if s.verified)
        register_evidence = workspace.observe(
            evidence_type=EvidenceType.SOURCE,
            source="source_register",
            reference=f"brand:{payload.brand_id}",
            observation=(
                f"Registered {len(sources)} candidate source(s): {len(fetched)} fetched, "
                f"{verified_count} verified by a successful fetch."
            ),
            data={"tiers": tiers, "fetched": {u: ok for u, (ok, _) in fetched.items()}},
            provenance=DataProvenance.OBSERVED,
        )

        regulated = facts.risk_category in HIGH_RISK_CATEGORIES
        weak = [c for c in coverage if c.status != "sourced"]
        for claim in weak:
            workspace.find(
                key=f"sources.claim_{claim.status}",
                title=f"Approved claim without a verified source: '{claim.claim}'",
                detail=claim.detail,
                severity="high" if regulated else "medium",
                data=claim.as_dict(),
                evidence=[register_evidence],
            )
        if weak and regulated:
            workspace.limitation(
                f"This is {facts.risk_category.value} content: {len(weak)} approved claim(s) "
                "rest on no verified source and should not be published until one is fetched."
            )

        output = SourceEvidenceOutput(
            brand_id=str(payload.brand_id),
            candidates=len(sources),
            fetched=len(fetched),
            verified=verified_count,
            new_sources=new_sources,
            tiers=tiers,
            claims=[c.as_dict() for c in coverage],
            sources=[s.model_dump(mode="json") for s in sources[:100]],
        )
        workspace.outputs["source_evidence"] = output.model_dump(mode="json")
        workspace.metrics["sources_verified"] = float(verified_count)

        return (
            f"Registered {len(sources)} source(s), {verified_count} verified by fetch. "
            f"{len(coverage) - len(weak)} of {len(coverage)} approved claim(s) are backed by a "
            "verified tier 1-3 source."
        )


AGENT = SourceEvidenceAgent
