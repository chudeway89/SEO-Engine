"""The content quality gate.

The evaluator (CNT-007) scores a draft against its brief. The gate decides
whether the draft may go to a human for approval at all. It blocks on things no
score should average away:

* the evaluation failed, or never ran on this version;
* the "draft" is a structured outline, not prose (no model was configured);
* it substantially duplicates another of the brand's assets or a live page;
* it is thin against its own brief's target length;
* it repeats a template so closely that it reads as scaled, near-identical
  content (location or keyword swaps over one body) — the pattern search
  engines treat as doorway pages and Rule 13 forbids.

Compliance (prohibited claims, forbidden terminology, unverified claims in a
regulated category) is the policy guardian's job, not this gate's: keeping the
two separate means a reviewer always knows *which* standard a block came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from seo_engine.engines.content.generation import OUTLINE_MARKER
from seo_engine.engines.keywords.pipeline import content_tokens, jaccard
from seo_engine.schemas.content import ContentBrief, ContentDraft, ContentEvaluation
from seo_engine.schemas.enums import HIGH_RISK_CATEGORIES

SHINGLE_SIZE = 5
NEAR_DUPLICATE_THRESHOLD = 0.6
THIN_SHARE_OF_TARGET = 0.4

_WORD = re.compile(r"[a-z0-9']+")


def shingles(text: str, size: int = SHINGLE_SIZE) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def is_template_variant(left: set[str], right: set[str]) -> bool:
    """Two titles that are one template with a term swapped (a city, a keyword).

    Short titles make a ratio threshold useless — swapping one word of four is
    already only 60% overlap — so the rule is structural: the titles share all
    but at most one term each, and at least two terms.
    """
    if left == right or not left or not right:
        return False
    shared = len(left & right)
    return shared >= 2 and shared >= max(len(left), len(right)) - 1


def is_outline(draft: ContentDraft) -> bool:
    return OUTLINE_MARKER in (draft.body_markdown or "")


@dataclass(slots=True)
class GateResult:
    passed: bool
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_human_review: bool = True
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "blocking": self.blocking,
            "warnings": self.warnings,
            "requires_human_review": self.requires_human_review,
            "checks": self.checks,
        }


def quality_gate(
    draft: ContentDraft,
    brief: ContentBrief,
    *,
    evaluation: ContentEvaluation | None,
    other_bodies: dict[str, str] | None = None,
    sibling_titles: list[str] | None = None,
) -> GateResult:
    """Decide whether a draft may be put in front of a human approver."""
    result = GateResult(passed=False)
    body = draft.body_markdown or "\n".join(s.body for s in draft.sections)

    # 1. Evaluation.
    if evaluation is None:
        result.blocking.append("The draft has not been evaluated; the gate does not guess.")
    elif not evaluation.passed:
        result.blocking.append(
            f"The evaluation failed (score {evaluation.overall_score:.0f}"
            + (
                f"; blocking: {', '.join(evaluation.blocking_failures)}"
                if evaluation.blocking_failures
                else ""
            )
            + ")."
        )
    result.checks["evaluation_passed"] = bool(evaluation and evaluation.passed)

    # 2. Outline, not prose.
    outline = is_outline(draft)
    result.checks["is_outline"] = outline
    if outline:
        result.blocking.append(
            "This is a structured outline, not written prose: no language model was "
            "configured to write it. A writer must supply the copy before review."
        )

    # 3. Duplication against the brand's other assets and live pages.
    mine = shingles(body)
    worst_url, worst = None, 0.0
    for ref, other in (other_bodies or {}).items():
        overlap = jaccard(mine, shingles(other))
        if overlap > worst:
            worst_url, worst = ref, overlap
    result.checks["max_duplicate_overlap"] = round(worst, 3)
    if worst >= NEAR_DUPLICATE_THRESHOLD and not outline:
        result.blocking.append(
            f"The draft shares {worst:.0%} of its five-word sequences with {worst_url}; "
            "it duplicates existing content rather than adding to it."
        )

    # 4. Thin against its own brief.
    # Lowercased first: the pattern is lowercase-only, so capitalised words would
    # otherwise lose letters and acronyms would not be counted at all.
    words = len(_WORD.findall(body.lower()))
    result.checks["word_count"] = words
    if (
        not outline
        and brief.target_word_count
        and words < THIN_SHARE_OF_TARGET * brief.target_word_count
    ):
        result.blocking.append(
            f"The draft has {words} words against a brief target of "
            f"{brief.target_word_count}; it is too thin to serve the intent the brief set."
        )

    # 5. Scaled-template pattern.
    title_tokens = content_tokens(draft.title)
    near_identical = [
        title
        for title in (sibling_titles or [])
        if title_tokens
        and title.strip().lower() != draft.title.strip().lower()
        and is_template_variant(title_tokens, content_tokens(title))
    ]
    result.checks["near_identical_titles"] = near_identical[:10]
    if len(near_identical) >= 2:
        result.blocking.append(
            f"{len(near_identical)} other assets have near-identical titles "
            f"({'; '.join(near_identical[:3])}). Publishing variants of one template "
            "is scaled content, not new information."
        )
    elif near_identical:
        result.warnings.append(
            f"Another asset has a near-identical title ('{near_identical[0]}'); confirm "
            "the two serve different intents."
        )

    if evaluation is not None:
        result.warnings.extend(evaluation.warnings)
        if evaluation.keyword_stuffing_detected:
            result.warnings.append("The evaluator detected keyword stuffing.")

    # Nothing publishes itself: every draft goes to a person, and regulated
    # categories are marked so the approver knows the higher bar applies.
    result.requires_human_review = True
    result.checks["regulated_category"] = brief.risk_category in HIGH_RISK_CATEGORIES
    result.passed = not result.blocking
    return result


__all__ = [
    "NEAR_DUPLICATE_THRESHOLD",
    "GateResult",
    "is_outline",
    "is_template_variant",
    "quality_gate",
    "shingles",
]
