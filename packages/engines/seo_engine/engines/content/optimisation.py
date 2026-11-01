"""Optimisation edits for a draft that passed evaluation with weaknesses.

The evaluator says *what* scored low. This engine turns each weak, non-blocking
criterion into a concrete, reviewable edit against the draft and its brief:
which heading to add, which brief question is unanswered, which internal link
is missing, which structured-data type the brief calls for, which term is
over-used. It edits nothing itself — every item is a proposal a writer applies,
so the evaluated version stays exactly what was evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from seo_engine.engines.keywords.pipeline import content_tokens
from seo_engine.schemas.content import ContentBrief, ContentDraft, ContentEvaluation

#: Criteria below this score are worth an edit even if they passed.
WEAK_SCORE = 75.0


@dataclass(slots=True)
class OptimisationEdit:
    criterion: str
    edit_type: str
    target: str
    proposal: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "criterion": self.criterion,
            "edit_type": self.edit_type,
            "target": self.target,
            "proposal": self.proposal,
            "reason": self.reason,
        }


def optimisation_edits(
    draft: ContentDraft, brief: ContentBrief, evaluation: ContentEvaluation
) -> list[OptimisationEdit]:
    edits: list[OptimisationEdit] = []
    body = (draft.body_markdown or "\n".join(s.body for s in draft.sections)).lower()
    body_tokens = content_tokens(body)
    headings = " ".join(s.heading for s in draft.sections).lower()
    heading_tokens = content_tokens(headings)

    def weak(name: str) -> bool:
        item = evaluation.criterion(name)
        return item is not None and item.score < WEAK_SCORE

    if weak("completeness"):
        for section in brief.required_sections:
            if not content_tokens(section) & heading_tokens:
                edits.append(
                    OptimisationEdit(
                        "completeness",
                        "add_section",
                        "headings",
                        f"Add a section headed '{section}'.",
                        "The brief requires this section and no heading covers it.",
                    )
                )
        for question in brief.questions_to_answer:
            tokens = content_tokens(question)
            if tokens and len(tokens & body_tokens) / len(tokens) < 0.6:
                edits.append(
                    OptimisationEdit(
                        "completeness",
                        "answer_question",
                        "body",
                        f"Answer: {question}",
                        "The brief lists this question and the draft does not answer it.",
                    )
                )

    if weak("internal_linking"):
        linked = {link.url for link in draft.internal_links}
        for link in brief.internal_links:
            if link.url not in linked:
                edits.append(
                    OptimisationEdit(
                        "internal_linking",
                        "add_internal_link",
                        link.url,
                        f"Link to {link.url} with anchor text '{link.anchor_text}'.",
                        link.reason or "The brief names this page as a related internal page.",
                    )
                )

    if weak("structured_data_suitability") and not draft.schema_recommendation:
        edits.append(
            OptimisationEdit(
                "structured_data_suitability",
                "add_structured_data",
                "schema",
                f"Add structured data appropriate to a {brief.content_type.value}.",
                "The draft carries no structured-data recommendation.",
            )
        )

    if weak("readability"):
        item = evaluation.criterion("readability")
        edits.append(
            OptimisationEdit(
                "readability",
                "simplify",
                "body",
                "Shorten long sentences and split dense paragraphs.",
                item.detail if item else "Readability scored low.",
            )
        )

    if evaluation.keyword_stuffing_detected:
        edits.append(
            OptimisationEdit(
                "originality",
                "reduce_repetition",
                "body",
                "Replace repeated uses of the most frequent term with natural variants.",
                "The evaluator detected keyword stuffing.",
            )
        )

    if brief.primary_keyword:
        keyword_tokens = content_tokens(brief.primary_keyword)
        if keyword_tokens and not keyword_tokens <= content_tokens(draft.title):
            edits.append(
                OptimisationEdit(
                    "search_intent",
                    "retitle",
                    "title",
                    f"Include '{brief.primary_keyword}' in the title.",
                    "The title does not carry the brief's primary keyword.",
                )
            )

    if weak("conversion_relevance") and brief.cta and (draft.cta or "").strip() != brief.cta:
        edits.append(
            OptimisationEdit(
                "conversion_relevance",
                "add_cta",
                "body",
                f"Close with the brief's call to action: {brief.cta}",
                "The draft's next step does not match the brief.",
            )
        )
    return edits


__all__ = ["WEAK_SCORE", "OptimisationEdit", "optimisation_edits"]
