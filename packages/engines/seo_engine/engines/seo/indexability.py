"""Index coverage reconciliation.

The technical audit flags individual pages that are noindexed or missing from
the sitemap. This engine reconciles the three views a site owner actually has
of what *should* be indexed and asks where they disagree:

* what the sitemap declares,
* what the crawl observed (status, robots directives, canonical),
* what the business says matters (service and location landing URLs), and,
  when Search Console is connected, which URLs are earning impressions.

A disagreement between declared intent and observed state is the finding. A
priority landing page that cannot be indexed outranks any number of minor
issues, so priority is carried through to severity.

URLs the sitemap lists but the crawl never reached are reported as *unverified*,
not as problems: a bounded crawl not reaching a URL says nothing about it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from seo_engine.engines.seo.pages import PageFacts, key


class IndexState(StrEnum):
    INDEXABLE = "indexable"
    NOINDEX = "noindex"
    CANONICALISED = "canonicalised"
    REDIRECT = "redirect"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


def classify_state(page: PageFacts) -> IndexState:
    """Map the crawler's stored indexability onto one coverage state."""
    status = page.status_code or 0
    reason = (page.indexability_reason or "").lower()
    if page.indexability == "error" or status == 0:
        return IndexState.UNKNOWN
    if status >= 500:
        return IndexState.SERVER_ERROR
    if status >= 400:
        return IndexState.CLIENT_ERROR
    if 300 <= status < 400 or "redirect" in reason:
        return IndexState.REDIRECT
    robots = {d.lower() for d in page.meta_robots}
    if robots & {"noindex", "none"} or "noindex" in reason:
        return IndexState.NOINDEX
    if "robots" in reason or page.indexability in {"blocked", "disallowed"}:
        return IndexState.BLOCKED
    if page.indexability == "canonicalised" or (
        page.canonical_url and key(page.canonical_url) != key(page.url)
    ):
        return IndexState.CANONICALISED
    if page.indexability == "indexable":
        return IndexState.INDEXABLE
    return IndexState.UNKNOWN


@dataclass(slots=True)
class CoverageIssue:
    issue: str
    url: str
    state: str
    severity: str
    detail: str
    priority_label: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "issue": self.issue,
            "url": self.url,
            "state": self.state,
            "severity": self.severity,
            "detail": self.detail,
            "priority_label": self.priority_label,
        }


@dataclass(slots=True)
class CoverageReport:
    states: dict[str, int] = field(default_factory=dict)
    issues: list[CoverageIssue] = field(default_factory=list)
    sitemap_urls: int = 0
    sitemap_unverified: list[str] = field(default_factory=list)
    pages_observed: int = 0
    gsc_compared: bool = False

    def by_issue(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.issue] = counts.get(issue.issue, 0) + 1
        return counts


def reconcile(
    pages: Iterable[PageFacts],
    *,
    sitemap_urls: Iterable[str] = (),
    priority_urls: dict[str, str] | None = None,
    gsc_urls: Iterable[str] | None = None,
) -> CoverageReport:
    """Reconcile declared, observed and business-priority index intent."""
    observed = {key(p.url): p for p in pages}
    states = {k: classify_state(p) for k, p in observed.items()}
    declared = {key(u) for u in sitemap_urls if u}
    priorities = {key(u): label for u, label in (priority_urls or {}).items() if u}

    report = CoverageReport(
        sitemap_urls=len(declared),
        pages_observed=len(observed),
        gsc_compared=gsc_urls is not None,
    )
    for state in states.values():
        report.states[state.value] = report.states.get(state.value, 0) + 1

    # 1. Declared in the sitemap, observed as not indexable.
    for url_key in sorted(declared & set(observed)):
        state = states[url_key]
        if state is IndexState.INDEXABLE:
            continue
        report.issues.append(
            CoverageIssue(
                issue="sitemap_lists_non_indexable_url",
                url=observed[url_key].url,
                state=state.value,
                severity="high" if url_key in priorities else "medium",
                detail=(
                    f"The sitemap asks for this URL to be indexed, but the crawl observed "
                    f"it as {state.value.replace('_', ' ')}. The two signals contradict "
                    "each other."
                ),
                priority_label=priorities.get(url_key),
            )
        )

    # 2. Declared but never reached: unverified, not a problem.
    report.sitemap_unverified = sorted(declared - set(observed))[:200]

    # 3. Indexable and linked, but absent from a sitemap that exists.
    if declared:
        for url_key, page in sorted(observed.items()):
            if states[url_key] is IndexState.INDEXABLE and url_key not in declared:
                report.issues.append(
                    CoverageIssue(
                        issue="indexable_url_missing_from_sitemap",
                        url=page.url,
                        state=IndexState.INDEXABLE.value,
                        severity="medium" if url_key in priorities else "low",
                        detail=(
                            "The page is indexable and reachable by links but the sitemap "
                            "does not declare it, so the site's declared and actual index "
                            "intent differ."
                        ),
                        priority_label=priorities.get(url_key),
                    )
                )

    # 4. Business-priority URLs that cannot be indexed, or were never observed.
    for url_key, label in sorted(priorities.items()):
        priority_page = observed.get(url_key)
        if priority_page is None:
            report.issues.append(
                CoverageIssue(
                    issue="priority_url_not_observed",
                    url=url_key,
                    state=IndexState.UNKNOWN.value,
                    severity="medium",
                    detail=(
                        f"'{label}' names this URL as its landing page, but the crawl did "
                        "not reach it. It may be unlinked or beyond the crawl limits; its "
                        "state has not been assumed either way."
                    ),
                    priority_label=label,
                )
            )
            continue
        state = states[url_key]
        if state is not IndexState.INDEXABLE:
            report.issues.append(
                CoverageIssue(
                    issue="priority_url_not_indexable",
                    url=priority_page.url,
                    state=state.value,
                    severity="critical",
                    detail=(
                        f"'{label}' depends on this landing page, and it is "
                        f"{state.value.replace('_', ' ')}. Search engines cannot show it."
                    ),
                    priority_label=label,
                )
            )

    # 5. Canonicals that point at something that is not indexable itself.
    for url_key, page in sorted(observed.items()):
        if states[url_key] is not IndexState.CANONICALISED or not page.canonical_url:
            continue
        target = observed.get(key(page.canonical_url))
        if target is not None and states[key(target.url)] is not IndexState.INDEXABLE:
            report.issues.append(
                CoverageIssue(
                    issue="canonical_target_not_indexable",
                    url=page.url,
                    state=IndexState.CANONICALISED.value,
                    severity="high",
                    detail=(
                        f"The canonical points to {target.url}, which is itself "
                        f"{states[key(target.url)].value.replace('_', ' ')}, so neither "
                        "URL can be indexed."
                    ),
                )
            )

    # 6. Search Console impressions on URLs the crawl saw as non-indexable.
    if gsc_urls is not None:
        for url in sorted({key(u) for u in gsc_urls if u}):
            earning = observed.get(url)
            if earning is not None and states[url] in {
                IndexState.NOINDEX,
                IndexState.CLIENT_ERROR,
                IndexState.SERVER_ERROR,
                IndexState.REDIRECT,
            }:
                report.issues.append(
                    CoverageIssue(
                        issue="earning_url_not_indexable",
                        url=earning.url,
                        state=states[url].value,
                        severity="high",
                        detail=(
                            "Search Console reports impressions for this URL, but the crawl "
                            f"now observes it as {states[url].value.replace('_', ' ')}. "
                            "Visibility it currently earns is at risk."
                        ),
                    )
                )

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    report.issues.sort(key=lambda i: (severity_order.get(i.severity, 4), i.issue, i.url))
    return report


__all__ = ["CoverageIssue", "CoverageReport", "IndexState", "classify_state", "reconcile"]
