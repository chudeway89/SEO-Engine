"""BRD-001 — Brand Understanding Agent.

Reads the brand graph through the brand domain service and turns it into the
working model every downstream agent depends on: what the business sells, to
whom, where, against which competitors, under which claim constraints.

Everything it reports is derived from data the customer supplied. Where the
graph is incomplete it says so and records a limitation — it never fills a gap
with a plausible guess, because a fabricated audience or service would silently
corrupt every keyword, content and prioritisation decision downstream.

This agent is deterministic. It performs no external lookups and needs no LLM.
"""

from __future__ import annotations

from typing import Any

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import EvidenceType, MemoryScope, MemoryType, SynthesisMode

_schemas = load_agent_module(__file__)
BrandUnderstandingInput = _schemas.BrandUnderstandingInput
BrandUnderstandingOutput = _schemas.BrandUnderstandingOutput
CompletenessDimension = _schemas.CompletenessDimension

#: What a brand graph needs before downstream research is trustworthy.
EXPECTED: dict[str, int] = {
    "goals": 1,
    "services": 1,
    "audiences": 1,
    "locations": 0,
    "competitors": 2,
    "voice": 1,
    "claims": 0,
}


class BrandUnderstandingAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = BrandUnderstandingInput.model_validate(context.inputs)
        brands = context.service("brands")
        profile = await brands.profile(payload.brand_id)

        brand = profile["brand"]
        goals = profile["goals"]
        services = profile["services"]
        products = profile["products"]
        audiences = profile["audiences"]
        locations = profile["locations"]
        competitors = profile["competitors"]
        claims = profile["claims"]
        prohibited = profile["prohibited_claims"]
        voice = profile["voice"]

        # --- evidence: what the customer actually told us ------------------
        graph_evidence = workspace.observe(
            evidence_type=EvidenceType.BRAND,
            source="brand_graph",
            reference=f"brand:{brand.id}",
            observation=(
                f"{brand.name} describes itself as operating in "
                f"{brand.industry or 'an unspecified industry'} with "
                f"{len(services)} service(s), {len(products)} product(s), "
                f"{len(audiences)} audience(s) and {len(locations)} location(s)."
            ),
            data={
                "services": [s.name for s in services],
                "products": [p.name for p in products],
                "audiences": [a.name for a in audiences],
                "locations": [_location_label(location) for location in locations],
                "competitors": [c.domain for c in competitors],
            },
            confidence=1.0,
        )

        completeness = self._completeness(profile)
        score = round(100 * sum(d.ratio for d in completeness) / max(len(completeness), 1), 1)

        missing = [d.dimension for d in completeness if not d.complete]
        for dimension in completeness:
            if not dimension.complete:
                workspace.limitation(
                    f"The brand has no {dimension.dimension} recorded. {dimension.detail}"
                )

        workspace.find(
            key="brand.completeness",
            title=f"Brand profile is {score:.0f}% complete",
            detail=(
                "Complete: "
                + ", ".join(d.dimension for d in completeness if d.complete)
                + (f". Missing: {', '.join(missing)}." if missing else ".")
            ),
            severity="info" if score >= 70 else "medium",
            data={"score": score, "missing": missing},
            evidence=[graph_evidence],
        )

        # --- commercial priorities ----------------------------------------
        priorities = self._commercial_priorities(goals, services, products)
        if priorities:
            priority_evidence = workspace.infer(
                source="brand_understanding",
                conclusion=(
                    "Commercial priority order derived from stated goals and the "
                    "revenue weighting of services and products: " + ", ".join(priorities[:5])
                ),
                data={"priorities": priorities},
                confidence=0.7,
                derived_from=[graph_evidence.id],
            )
            workspace.find(
                key="brand.commercial_priorities",
                title="Commercial priorities identified",
                detail=(
                    "Downstream keyword and content prioritisation weights business "
                    "relevance most heavily, so this ordering matters."
                ),
                data={"priorities": priorities},
                evidence=[priority_evidence],
            )

        # --- claim constraints ---------------------------------------------
        if prohibited:
            workspace.observe(
                evidence_type=EvidenceType.BRAND,
                source="brand_claims",
                reference=f"brand:{brand.id}",
                observation=(
                    f"{len(prohibited)} claim(s) are explicitly prohibited for this brand "
                    "and must never appear in generated content."
                ),
                data={"prohibited": [c.claim for c in prohibited]},
            )
        if not claims and brand.risk_category != "general":
            workspace.limitation(
                f"This brand is in the '{brand.risk_category}' risk category but has no "
                "approved claims recorded. Commercial content generation will be "
                "constrained until claims are approved."
            )

        # --- seed topics for research ---------------------------------------
        seed_topics = self._seed_topics(services, products, audiences, locations)
        vocabulary = sorted(
            {term for audience in audiences for term in (audience.vocabulary or [])}
        )

        output = BrandUnderstandingOutput(
            brand_id=str(brand.id),
            brand_name=brand.name,
            industry=brand.industry,
            risk_category=brand.risk_category,
            completeness=completeness,
            completeness_score=score,
            commercial_priorities=priorities,
            target_locations=[_location_label(location) for location in locations],
            audience_vocabulary=vocabulary,
            seed_topics=seed_topics,
            approved_claims=[c.claim for c in claims],
            prohibited_claims=[c.claim for c in prohibited],
            missing_inputs=missing,
            profile={
                "name": brand.name,
                "description": brand.description,
                "industry": brand.industry,
                "country": brand.country,
                "language": brand.primary_language,
                "business_model": brand.business_model,
                "voice": voice.tone if voice else None,
                "goals": [g.description for g in goals],
                "services": [s.name for s in services],
                "products": [p.name for p in products],
                "audiences": [a.name for a in audiences],
                "competitors": [
                    {"name": c.name, "domain": c.domain, "types": c.competitor_types}
                    for c in competitors
                ],
            },
        )
        workspace.outputs["brand_understanding"] = output.model_dump(mode="json")
        workspace.metrics["completeness_score"] = score
        workspace.metrics["seed_topics"] = float(len(seed_topics))

        # --- remember what matters -------------------------------------------
        if workspace.note_unavailable_tool("memory"):
            memory = context.service("memory")
            await memory.store(
                key="brand:profile",
                content=(
                    f"{brand.name} operates in {brand.industry or 'an unspecified industry'}. "
                    f"Services: {', '.join(s.name for s in services) or 'none recorded'}. "
                    f"Audiences: {', '.join(a.name for a in audiences) or 'none recorded'}. "
                    f"Locations: {', '.join(output.target_locations) or 'none recorded'}."
                ),
                scope=MemoryScope.BRAND,
                memory_type=MemoryType.BRAND_FACT,
                brand_id=brand.id,
                source="BRD-001",
                source_agent_id="BRD-001",
                confidence=1.0,
                importance=0.9,
                structured=output.profile,
                evidence_refs=[graph_evidence.id],
            )

        return self._summary(brand, output, completeness)

    # ------------------------------------------------------------------
    def _completeness(self, profile: dict[str, Any]) -> list[CompletenessDimension]:
        counts = {
            "goals": len(profile["goals"]),
            "services": len(profile["services"]) + len(profile["products"]),
            "audiences": len(profile["audiences"]),
            "locations": len(profile["locations"]),
            "competitors": len(profile["competitors"]),
            "voice": 1 if profile["voice"] else 0,
            "claims": len(profile["claims"]),
        }
        details = {
            "goals": "Without a business objective the system cannot rank opportunities commercially.",
            "services": "Without services or products, keyword research has no commercial anchor.",
            "audiences": "Without an audience, search intent cannot be judged against a real reader.",
            "locations": "Only needed if the brand competes locally.",
            "competitors": "At least two competitors are needed for meaningful gap analysis.",
            "voice": "Without a voice profile, generated content cannot be checked for brand alignment.",
            "claims": "Approved claims are required before commercial copy can be generated.",
        }
        return [
            CompletenessDimension(
                dimension=dimension,
                present=counts[dimension],
                expected_minimum=expected,
                complete=counts[dimension] >= expected,
                detail=details[dimension],
            )
            for dimension, expected in EXPECTED.items()
        ]

    def _commercial_priorities(
        self, goals: list[Any], services: list[Any], products: list[Any]
    ) -> list[str]:
        ranked: list[tuple[float, str]] = []
        for service in services:
            weight = float(getattr(service, "revenue_weight", 1.0) or 1.0)
            priority = int(getattr(service, "priority", 3) or 3)
            ranked.append((weight * (6 - priority), service.name))
        for product in products:
            ranked.append((1.0, product.name))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        priorities = [name for _, name in ranked]

        # A goal that names a service lifts it to the front.
        goal_text = " ".join(g.description.lower() for g in goals)
        priorities.sort(key=lambda name: name.lower() not in goal_text)
        return priorities

    def _seed_topics(
        self, services: list[Any], products: list[Any], audiences: list[Any], locations: list[Any]
    ) -> list[str]:
        """Seeds come only from what the customer told us, never from guesses."""
        seeds: list[str] = []
        for service in services:
            seeds.append(service.name)
            seeds.extend(service.keywords or [])
        for product in products:
            seeds.append(product.name)
            seeds.extend(product.keywords or [])
        for audience in audiences:
            seeds.extend(audience.vocabulary or [])
            seeds.extend(audience.pains or [])

        location_labels = [_location_label(location) for location in locations]
        combined = list(seeds)
        for service in services:
            for label in location_labels:
                combined.append(f"{service.name} {label}")

        seen: set[str] = set()
        unique: list[str] = []
        for seed in combined:
            cleaned = " ".join((seed or "").split()).strip()
            if cleaned and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                unique.append(cleaned)
        return unique

    def _summary(self, brand: Any, output: Any, completeness: list[Any]) -> str:
        parts = [
            f"{brand.name} operates in "
            f"{brand.industry or 'an industry the brand profile does not state'}."
        ]
        if output.commercial_priorities:
            parts.append(
                "Commercial priority order: " + ", ".join(output.commercial_priorities[:4]) + "."
            )
        if output.target_locations:
            parts.append(f"Target locations: {', '.join(output.target_locations)}.")
        parts.append(
            f"The brand profile is {output.completeness_score:.0f}% complete and yields "
            f"{len(output.seed_topics)} research seed(s)."
        )
        missing = [d.dimension for d in completeness if not d.complete]
        if missing:
            parts.append(
                "Missing inputs that will limit downstream accuracy: " + ", ".join(missing) + "."
            )
        if output.prohibited_claims:
            parts.append(
                f"{len(output.prohibited_claims)} prohibited claim(s) are on record and "
                "will be enforced during content generation."
            )
        return " ".join(parts)


def _location_label(location: Any) -> str:
    return location.city or location.region or location.name


AGENT = BrandUnderstandingAgent
