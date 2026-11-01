"""SEO-002 — On-Page SEO Agent.

The technical audit (SEO-001) checks that titles and headings exist and are the
right length. This agent checks that they say the right thing: for every page
the keyword pipeline mapped a keyword to, it scores how clearly the page's title,
H1, meta description, opening copy and URL carry that keyword.

A corrected title is proposed only from facts the platform holds — the keyword
and the brand name. No meta description is written: that needs prose, so the
agent says what it must contain and leaves the words to a person. Nothing is
changed on the site; misalignments become evidenced opportunity seeds that the
decision chain prioritises and, if approved, executes.
"""

from __future__ import annotations

from seo_engine.agent_runtime.base import AgentWorkspace, BaseAgent
from seo_engine.agent_runtime.loader import load_agent_module
from seo_engine.agent_runtime.support import load_brand_facts, load_page_facts, website_domain
from seo_engine.engines.keywords.intent_fit import PageType, classify_page_type
from seo_engine.engines.opportunities.detection import seed
from seo_engine.engines.seo.onpage import alignment_report
from seo_engine.schemas.agent import AgentContext
from seo_engine.schemas.enums import EvidenceType, OpportunityType, SynthesisMode

_schemas = load_agent_module(__file__)
OnPageInput = _schemas.OnPageInput
OnPageOutput = _schemas.OnPageOutput

COMMERCIAL_TYPES = frozenset(
    {PageType.SERVICE, PageType.PRODUCT, PageType.PRICING, PageType.LOCATION, PageType.CONTACT}
)


class OnPageAgent(BaseAgent):
    synthesis_mode = SynthesisMode.DETERMINISTIC

    async def run(self, context: AgentContext, workspace: AgentWorkspace) -> str:
        payload = OnPageInput.model_validate(context.inputs)
        if payload.website_id is None:
            workspace.limitation("No website was supplied, so no page could be assessed.")
            return "No on-page assessment was possible: no website is connected."

        # The keyword each page is meant to rank for, as the pipeline mapped it.
        keywords = await context.service("search").list_keywords(payload.brand_id, limit=1000)
        mapping: dict[str, str] = {}
        best: dict[str, float] = {}
        for keyword in keywords:
            if not keyword.mapped_url or keyword.is_branded:
                continue
            if keyword.opportunity_score > best.get(keyword.mapped_url, -1.0):
                mapping[keyword.mapped_url] = keyword.keyword
                best[keyword.mapped_url] = keyword.opportunity_score

        if not mapping:
            workspace.limitation(
                "No keyword is mapped to any page yet, so alignment cannot be judged. "
                "Keyword research maps keywords to pages; run it first."
            )
            return "No page has a mapped keyword, so no on-page alignment was assessed."

        domain = await website_domain(context, payload.website_id)
        facts = await load_brand_facts(context, payload.brand_id, website_domain=domain)
        pages = await load_page_facts(
            context, payload.website_id, limit=payload.max_pages, with_schema=True
        )
        page_by_url = {p.url: p for p in pages}
        report = alignment_report(pages, mapping, brand_name=facts.name)

        if not report:
            workspace.limitation(
                f"{len(mapping)} page(s) have a mapped keyword but none of them is among "
                "the crawled, indexable pages, so none could be assessed."
            )
            return "Mapped pages were not in the crawl, so no alignment was assessed."

        misaligned = [a for a in report if not a.aligned]
        average = round(sum(a.score for a in report) / len(report), 1)
        summary_evidence = workspace.observe(
            evidence_type=EvidenceType.CRAWL_RESULT,
            source="on_page_engine",
            reference=str(payload.website_id),
            observation=(
                f"Assessed keyword alignment on {len(report)} page(s) with a mapped keyword; "
                f"{len(misaligned)} fall below the alignment threshold. Average alignment "
                f"{average}/100."
            ),
            data={"pages": len(report), "misaligned": len(misaligned), "average": average},
        )

        seeds = []
        for alignment in misaligned[: payload.max_findings]:
            page = page_by_url.get(alignment.url)
            page_type = classify_page_type(page).page_type if page else PageType.OTHER
            commercial = page_type in COMMERCIAL_TYPES
            evidence = workspace.observe(
                evidence_type=EvidenceType.CRAWL_RESULT,
                source="on_page_engine",
                reference=alignment.url,
                observation=(
                    f"{alignment.url} scores {alignment.score}/100 for its mapped keyword "
                    f"'{alignment.keyword}'. The keyword's terms are missing from: "
                    + ", ".join(e.replace("_", " ") for e in alignment.missing_from)
                    + "."
                ),
                data=alignment.as_dict(),
            )
            workspace.find(
                key="on_page.misaligned",
                title=f"'{alignment.keyword}' is not clearly signalled on {alignment.url}",
                detail=(
                    f"Missing from {', '.join(alignment.missing_from)}."
                    + (
                        f" Proposed title: '{alignment.proposed_title}'."
                        if alignment.proposed_title
                        else ""
                    )
                ),
                severity="medium" if "title" in alignment.missing_from else "low",
                data=alignment.as_dict(),
                evidence=[evidence],
            )
            seeds.append(
                seed(
                    opportunity_type=OpportunityType.ON_PAGE,
                    title=f"Align {alignment.url} with '{alignment.keyword}'",
                    description=(
                        f"The page is mapped to '{alignment.keyword}' but does not carry it "
                        f"in its {', '.join(alignment.missing_from)}."
                    ),
                    business_impact=7.0 if commercial else 5.0,
                    seo_impact=4.0 + 5.0 * (1 - alignment.score / 100),
                    effort=2.0,
                    confidence=0.75,
                    evidence_refs=[evidence.id, summary_evidence.id],
                    target_url=alignment.url,
                    source_agent=self.manifest.id,
                    data={
                        "keyword": alignment.keyword,
                        "proposed_title": alignment.proposed_title,
                        "meta_guidance": alignment.meta_guidance,
                        # The exact change an executor may apply once approved. Only
                        # the title is concrete; the meta description is left to a
                        # writer and never generated.
                        "change": (
                            {"title": alignment.proposed_title}
                            if alignment.proposed_title
                            else None
                        ),
                    },
                )
            )

        output = OnPageOutput(
            brand_id=str(payload.brand_id),
            pages_assessed=len(report),
            misaligned=len(misaligned),
            average_alignment=average,
            pages=[a.as_dict() for a in report[:100]],
        )
        workspace.outputs["on_page"] = output.model_dump(mode="json")
        workspace.outputs["opportunity_seeds"] = seeds
        workspace.metrics["on_page_pages_assessed"] = float(len(report))
        workspace.metrics["on_page_misaligned"] = float(len(misaligned))

        return (
            f"Assessed {len(report)} page(s) against their mapped keyword: {len(misaligned)} "
            f"do not clearly signal it (average alignment {average}/100). Proposed titles "
            "use only the keyword and brand name; meta descriptions are left to a writer."
        )


AGENT = OnPageAgent
