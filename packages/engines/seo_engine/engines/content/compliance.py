"""Content compliance against the brand's own rules.

Checks a draft against what the customer has said must never be published:

* **prohibited claims** recorded in the brand graph;
* **forbidden terminology** from the voice profile;
* **unverified claims** — statements the brief marked as needing a source the
  platform never fetched — which block outright in a regulated category;
* **absolute outcome language** in a regulated category.

Matching is deliberately literal and explainable: a block names the phrase that
triggered it. The brief's own "Claims that must not appear" section, which a
structured outline reproduces as an instruction to the writer, is excluded from
the scan — quoting a prohibition is not making the claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.schemas.content import ContentDraft
from seo_engine.schemas.enums import HIGH_RISK_CATEGORIES, RiskCategory

#: Sections that carry instructions to the writer rather than published copy.
INSTRUCTION_SECTIONS = frozenset(
    {"claims that must not appear", "approved claims available to the writer"}
)

#: A prohibited claim matches when the draft sentence carries this share of its terms.
CLAIM_MATCH_THRESHOLD = 0.8

ABSOLUTE_OUTCOME = re.compile(
    r"\b(guarantee[sd]?|100% (accurate|effective|safe)|risk[- ]free|always works|cures?|"
    r"never fails|completely safe)\b",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(slots=True)
class ComplianceResult:
    compliant: bool
    violations: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_approval: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "compliant": self.compliant,
            "violations": self.violations,
            "warnings": self.warnings,
            "requires_approval": self.requires_approval,
        }


def publishable_text(draft: ContentDraft) -> str:
    """The copy a visitor would read, without writer instructions."""
    if draft.sections:
        parts = [
            f"{s.heading}\n{s.body}"
            for s in draft.sections
            if s.heading.strip().lower() not in INSTRUCTION_SECTIONS
        ]
        return "\n".join([draft.title, draft.meta_description, *parts])
    body = draft.body_markdown or ""
    for heading in INSTRUCTION_SECTIONS:
        body = re.sub(rf"(?ims)^##\s*{re.escape(heading)}\s*$.*?(?=^##\s|\Z)", "", body)
    return "\n".join([draft.title, draft.meta_description, body])


def check_compliance(
    draft: ContentDraft,
    *,
    prohibited_claims: list[str],
    forbidden_terms: list[str],
    risk_category: RiskCategory | str,
) -> ComplianceResult:
    text = publishable_text(draft)
    lowered = text.lower()
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    category = RiskCategory(risk_category)
    regulated = category in HIGH_RISK_CATEGORIES
    result = ComplianceResult(compliant=True)

    for claim in prohibited_claims:
        tokens = content_tokens(claim)
        if not tokens:
            continue
        exact = claim.strip().lower().rstrip(".") in lowered
        near = any(
            len(tokens & content_tokens(sentence)) / len(tokens) >= CLAIM_MATCH_THRESHOLD
            for sentence in sentences
        )
        if exact or near:
            result.violations.append(
                {
                    "rule": "prohibited_claim",
                    "match": claim,
                    "detail": "The draft makes a claim the brand has prohibited.",
                }
            )

    for term in forbidden_terms:
        if term and re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", lowered):
            result.violations.append(
                {
                    "rule": "forbidden_terminology",
                    "match": term,
                    "detail": "The voice profile forbids this term.",
                }
            )

    if draft.unverified_claims:
        if regulated:
            result.violations.append(
                {
                    "rule": "unverified_claim_in_regulated_content",
                    "match": draft.unverified_claims[0],
                    "detail": (
                        f"{len(draft.unverified_claims)} statement(s) rest on sources the "
                        f"platform has not verified, in {category.value} content."
                    ),
                }
            )
        else:
            result.warnings.append(
                f"{len(draft.unverified_claims)} statement(s) rest on unverified sources."
            )

    if regulated:
        for match in sorted({m.group(0).lower() for m in ABSOLUTE_OUTCOME.finditer(text)}):
            result.violations.append(
                {
                    "rule": "absolute_outcome_language",
                    "match": match,
                    "detail": f"Absolute outcome language is not permitted in {category.value} content.",
                }
            )

    result.compliant = not result.violations
    return result


__all__ = [
    "ABSOLUTE_OUTCOME",
    "INSTRUCTION_SECTIONS",
    "ComplianceResult",
    "check_compliance",
    "publishable_text",
]
