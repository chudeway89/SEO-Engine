"""robots.txt fetching and parsing.

Written rather than delegated to ``urllib.robotparser`` because we need the
sitemap directives, the crawl-delay, and the ability to report *why* a URL was
skipped — none of which the stdlib parser exposes cleanly.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from seo_engine.schemas.crawl import RobotsPolicy


@dataclass(slots=True)
class _Group:
    agents: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None


class RobotsRules:
    """Parsed robots.txt with the matching semantics Google documents.

    * the most specific user-agent group wins;
    * within a group the longest matching path wins;
    * on a tie, ``Allow`` beats ``Disallow``;
    * ``*`` and ``$`` wildcards are supported.
    """

    def __init__(self, groups: list[_Group], sitemaps: list[str], raw: str = "") -> None:
        self._groups = groups
        self.sitemaps = sitemaps
        self.raw = raw

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[_Group] = []
        sitemaps: list[str] = []
        current: _Group | None = None
        expecting_agent = False

        for raw_line in (text or "").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            key = field_name.strip().lower()
            value = value.strip()

            if key == "user-agent":
                if current is None or not expecting_agent:
                    current = _Group()
                    groups.append(current)
                    expecting_agent = True
                current.agents.append(value.lower())
            elif key in {"allow", "disallow"}:
                expecting_agent = False
                if current is None:
                    current = _Group(agents=["*"])
                    groups.append(current)
                if key == "allow":
                    current.allow.append(value)
                else:
                    current.disallow.append(value)
            elif key == "crawl-delay":
                expecting_agent = False
                if current is not None:
                    with contextlib.suppress(ValueError):
                        current.crawl_delay = float(value)
            elif key == "sitemap":
                if value:
                    sitemaps.append(value)

        return cls(groups, sitemaps, text or "")

    # ------------------------------------------------------------------
    def _group_for(self, user_agent: str) -> _Group | None:
        agent = user_agent.lower()
        best: tuple[int, _Group] | None = None
        wildcard: _Group | None = None

        for group in self._groups:
            for declared in group.agents:
                if declared == "*":
                    if wildcard is None:
                        wildcard = group
                    continue
                # A token match: "seoenginebot" matches "SEOEngineBot/0.1 (+...)".
                if declared and declared in agent and (best is None or len(declared) > best[0]):
                    best = (len(declared), group)
        if best is not None:
            return best[1]
        return wildcard

    def crawl_delay(self, user_agent: str) -> float | None:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None

    def allows(self, url: str, user_agent: str) -> bool:
        group = self._group_for(user_agent)
        if group is None:
            return True

        path = urlparse(url).path or "/"
        if urlparse(url).query:
            path = f"{path}?{urlparse(url).query}"
        path = unquote(path)

        best_allow = _longest_match(group.allow, path)
        best_disallow = _longest_match(group.disallow, path)

        if best_disallow is None:
            return True
        if best_allow is None:
            return False
        # Ties go to Allow, per Google's documented behaviour.
        return best_allow >= best_disallow


def _longest_match(patterns: list[str], path: str) -> int | None:
    best: int | None = None
    for pattern in patterns:
        if pattern == "":
            # "Disallow:" with an empty value means allow everything.
            continue
        if _path_matches(pattern, path):
            length = len(pattern)
            if best is None or length > best:
                best = length
    return best


def _path_matches(pattern: str, path: str) -> bool:
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    regex = "".join(".*" if char == "*" else re.escape(char) for char in pattern)
    return re.match(f"^{regex}{'$' if anchored_end else ''}", path) is not None


async def fetch_robots(client, base_url: str, user_agent: str) -> tuple[RobotsPolicy, RobotsRules]:
    """Fetch and parse robots.txt.

    A missing or unreachable robots.txt means "crawl allowed" — that is the
    documented convention — but the failure is recorded so the audit shows the
    crawl proceeded without a policy rather than silently assuming one.
    """
    robots_url = f"{base_url.rstrip('/')}/robots.txt"
    try:
        response = await client.get(robots_url)
    except Exception as exc:
        return (
            RobotsPolicy(fetched=False, url=robots_url, allows_crawling=True, error=str(exc)),
            RobotsRules([], []),
        )

    if response.status_code >= 400:
        return (
            RobotsPolicy(
                fetched=False,
                url=robots_url,
                allows_crawling=True,
                error=f"HTTP {response.status_code}",
            ),
            RobotsRules([], []),
        )

    text = response.text
    rules = RobotsRules.parse(text)
    return (
        RobotsPolicy(
            fetched=True,
            url=robots_url,
            allows_crawling=rules.allows(base_url, user_agent),
            sitemaps=rules.sitemaps,
            crawl_delay=rules.crawl_delay(user_agent),
            raw=text[:20_000],
        ),
        rules,
    )


__all__ = ["RobotsRules", "fetch_robots"]
