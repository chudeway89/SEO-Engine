"""Executors for approved SEO changes to live pages.

An executor applies exactly the change a person approved — nothing more — and
only through the brand's connected CMS adapter. Each executor needs a concrete
*change specification* carried on the action (``payload["change"]``): the new
title, the link to add. A recommendation that says "improve the title" without
saying what to is not executable, and the executor says so instead of inventing
a value (``ChangeNotSpecified``).

Changes the platform has no safe, general way to apply (structured data,
redirects) raise ``ChangeNotSupported`` with the reason; the action stays
approved for a person to apply by hand.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from seo_engine.integrations.base import CMSAdapter
from seo_engine.schemas.enums import ActionType


class ChangeNotSpecified(Exception):
    """The approved action does not say what the new value is."""


class ChangeNotSupported(Exception):
    """No executor applies this kind of change automatically."""


@dataclass(slots=True)
class ChangeResult:
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    mode: str | None = None
    notice: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "skipped": self.skipped,
            "mode": self.mode,
            "notice": self.notice,
        }


EXECUTABLE = frozenset({ActionType.METADATA_UPDATE.value, ActionType.INTERNAL_LINK_ADD.value})

UNSUPPORTED_REASONS: dict[str, str] = {
    ActionType.SCHEMA_UPDATE.value: (
        "structured data lives in the theme or an SEO plugin, which the CMS content API "
        "does not expose; it must be applied by a person"
    ),
    ActionType.REDIRECT_CREATE.value: (
        "redirects are server or plugin configuration, not page content; they must be "
        "applied by a person"
    ),
}


def missing_specification(
    action_type: str, target: dict[str, Any], change: dict[str, Any] | None
) -> str | None:
    """Why an approved action cannot be applied as specified, or ``None`` if it can.

    Checked before execution starts, so an unspecified change is reported and
    left approved rather than marked failed.
    """
    change = change or {}
    if action_type == ActionType.METADATA_UPDATE.value:
        if not target.get("url") or not str(change.get("title") or "").strip():
            return (
                "no exact new title was specified; a person must supply it before the "
                "change can be applied"
            )
        return None
    if action_type == ActionType.INTERNAL_LINK_ADD.value:
        if not (target.get("url") or change.get("to_url")) or not change.get("from_urls"):
            return "the target page and the linking pages are not both specified"
        if not str(change.get("anchor_text") or "").strip():
            return "no anchor text was specified"
        return None
    return UNSUPPORTED_REASONS.get(action_type, f"no executor exists for {action_type}")


async def apply_change(
    cms: CMSAdapter, *, action_type: str, target: dict[str, Any], change: dict[str, Any]
) -> ChangeResult:
    if action_type == ActionType.METADATA_UPDATE.value:
        return await _metadata(cms, target, change)
    if action_type == ActionType.INTERNAL_LINK_ADD.value:
        return await _internal_links(cms, target, change)
    raise ChangeNotSupported(
        UNSUPPORTED_REASONS.get(action_type, f"no executor exists for {action_type}")
    )


async def _metadata(
    cms: CMSAdapter, target: dict[str, Any], change: dict[str, Any]
) -> ChangeResult:
    url = target.get("url")
    title = str(change.get("title") or "").strip()
    if not url or not title:
        raise ChangeNotSpecified(
            "the approved change names no page or no new title; a person must supply the "
            "exact title before it can be applied"
        )
    page = await cms.find_page(url=url)
    response = await cms.update_page(
        external_id=page.payload["id"], page_type=page.payload["type"], fields={"title": title}
    )
    return ChangeResult(
        applied=[
            {
                "url": url,
                "external_id": page.payload["id"],
                "field": "title",
                "before": page.payload.get("title", ""),
                "after": title,
            }
        ],
        mode=response.mode.value,
        notice=response.notice,
    )


async def _internal_links(
    cms: CMSAdapter, target: dict[str, Any], change: dict[str, Any]
) -> ChangeResult:
    to_url = target.get("url") or change.get("to_url")
    sources = [str(u) for u in change.get("from_urls") or [] if u]
    anchor = str(change.get("anchor_text") or "").strip()
    if not to_url or not sources or not anchor:
        raise ChangeNotSpecified(
            "the approved change does not name the target page, the linking pages and the "
            "anchor text; all three are needed to add a link"
        )

    result = ChangeResult()
    link = f'<p><a href="{html.escape(str(to_url), quote=True)}">{html.escape(anchor)}</a></p>'
    for source in sources:
        page = await cms.find_page(url=source)
        content = str(page.payload.get("content") or "")
        if str(to_url).rstrip("/") in content:
            result.skipped.append({"url": source, "reason": "the page already links to the target"})
            continue
        response = await cms.update_page(
            external_id=page.payload["id"],
            page_type=page.payload["type"],
            fields={"content": f"{content.rstrip()}\n\n{link}\n"},
        )
        result.mode, result.notice = response.mode.value, response.notice
        result.applied.append(
            {"url": source, "external_id": page.payload["id"], "field": "content", "added": link}
        )
    return result


__all__ = [
    "EXECUTABLE",
    "UNSUPPORTED_REASONS",
    "ChangeNotSpecified",
    "ChangeNotSupported",
    "ChangeResult",
    "apply_change",
    "missing_specification",
]
