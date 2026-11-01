"""Topical architecture: hubs, spokes and cannibalisation.

The keyword pipeline clusters keywords and maps each one to its best page. This
engine reads that mapping as a *site structure* and asks two questions:

* **Cannibalisation** — does one topic have several pages competing for it? A
  cluster whose keywords map to more than one URL, or two pages whose titles
  target the same terms, split relevance between pages instead of building it.
* **Hub and spoke** — does each topic have a clear hub, and do its supporting
  pages link to that hub? A spoke that never links to its hub leaves the hub
  without the internal signal that it is the authoritative page.

Everything here is computed from the stored mapping and the observed link
graph. A cluster with no mapped page produces no architecture finding; that
absence is a content gap, which the content gap stage owns.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from seo_engine.engines.keywords.pipeline import content_tokens, jaccard
from seo_engine.engines.seo.pages import PageFacts, key

#: Two pages whose titles overlap this much target the same topic.
TITLE_OVERLAP_THRESHOLD = 0.75


@dataclass(slots=True)
class MappedKeyword:
    keyword: str
    cluster_id: str | None
    cluster_label: str | None
    mapped_url: str | None
    opportunity_score: float = 0.0
    is_head: bool = False


@dataclass(slots=True)
class Cannibalisation:
    topic: str
    cluster_id: str | None
    urls: list[str]
    keywords: list[str]
    basis: str
    recommended_primary: str

    def as_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "cluster_id": self.cluster_id,
            "urls": self.urls,
            "keywords": self.keywords,
            "basis": self.basis,
            "recommended_primary": self.recommended_primary,
        }


@dataclass(slots=True)
class ClusterStructure:
    cluster_id: str
    label: str
    hub_url: str | None
    spokes: list[str] = field(default_factory=list)
    spokes_missing_hub_link: list[str] = field(default_factory=list)
    hub_links_to_spokes: int = 0

    @property
    def healthy(self) -> bool:
        return self.hub_url is not None and not self.spokes_missing_hub_link

    def as_dict(self) -> dict[str, object]:
        return {
            "cluster_id": self.cluster_id,
            "label": self.label,
            "hub_url": self.hub_url,
            "spokes": self.spokes,
            "spokes_missing_hub_link": self.spokes_missing_hub_link,
            "hub_links_to_spokes": self.hub_links_to_spokes,
            "healthy": self.healthy,
        }


def _primary_url(
    urls: list[str], keywords: list[MappedKeyword], pages: dict[str, PageFacts]
) -> str:
    """The page best placed to own the topic: most mapped keyword value, then links in."""
    value: dict[str, float] = defaultdict(float)
    for item in keywords:
        if item.mapped_url:
            value[key(item.mapped_url)] += item.opportunity_score + (50.0 if item.is_head else 0.0)
    return max(
        urls,
        key=lambda u: (
            value.get(key(u), 0.0),
            pages[key(u)].internal_links_in if key(u) in pages else 0,
            -len(u),
        ),
    )


def find_cannibalisation(
    keywords: list[MappedKeyword], pages: list[PageFacts]
) -> list[Cannibalisation]:
    by_key = {key(p.url): p for p in pages}
    findings: list[Cannibalisation] = []
    claimed: set[frozenset[str]] = set()

    # 1. One cluster, several mapped URLs.
    clusters: dict[str, list[MappedKeyword]] = defaultdict(list)
    for item in keywords:
        if item.cluster_id and item.mapped_url:
            clusters[item.cluster_id].append(item)
    for cluster_id, items in clusters.items():
        urls = sorted({i.mapped_url for i in items if i.mapped_url})
        if len(urls) < 2:
            continue
        group = frozenset(key(u) for u in urls)
        claimed.add(group)
        findings.append(
            Cannibalisation(
                topic=items[0].cluster_label or items[0].keyword,
                cluster_id=cluster_id,
                urls=urls,
                keywords=sorted({i.keyword for i in items})[:12],
                basis=(f"keywords in one topic cluster map to {len(urls)} different pages"),
                recommended_primary=_primary_url(urls, items, by_key),
            )
        )

    # 2. Two indexable pages whose titles target the same terms.
    indexable = [p for p in pages if p.is_indexable and p.title]
    for i, left in enumerate(indexable):
        left_tokens = content_tokens(left.title)
        if len(left_tokens) < 2:
            continue
        for right in indexable[i + 1 :]:
            right_tokens = content_tokens(right.title)
            if len(right_tokens) < 2:
                continue
            overlap = jaccard(left_tokens, right_tokens)
            group = frozenset({key(left.url), key(right.url)})
            if overlap < TITLE_OVERLAP_THRESHOLD or any(group <= c for c in claimed):
                continue
            claimed.add(group)
            urls = sorted([left.url, right.url])
            findings.append(
                Cannibalisation(
                    topic=" ".join(sorted(left_tokens & right_tokens)),
                    cluster_id=None,
                    urls=urls,
                    keywords=[],
                    basis=f"page titles overlap {overlap:.0%} in their topical terms",
                    recommended_primary=_primary_url(urls, [], by_key),
                )
            )
    return findings


def cluster_structures(
    keywords: list[MappedKeyword],
    links: list[tuple[str, str]],
) -> list[ClusterStructure]:
    """Hub and spoke health per cluster from the mapping and the link graph.

    ``links`` is (source URL, target URL) for observed internal links.
    """
    graph: dict[str, set[str]] = defaultdict(set)
    for source, target in links:
        graph[key(source)].add(key(target))

    clusters: dict[str, list[MappedKeyword]] = defaultdict(list)
    for item in keywords:
        if item.cluster_id:
            clusters[item.cluster_id].append(item)

    structures: list[ClusterStructure] = []
    for cluster_id, items in sorted(clusters.items()):
        urls = sorted({i.mapped_url for i in items if i.mapped_url})
        label = items[0].cluster_label or items[0].keyword
        if not urls:
            continue
        hub = next((i.mapped_url for i in items if i.is_head and i.mapped_url), None)
        hub = hub or _primary_url(urls, items, {})
        spokes = [u for u in urls if key(u) != key(hub)]
        missing = [s for s in spokes if key(hub) not in graph.get(key(s), set())]
        structures.append(
            ClusterStructure(
                cluster_id=cluster_id,
                label=label,
                hub_url=hub,
                spokes=spokes,
                spokes_missing_hub_link=missing,
                hub_links_to_spokes=sum(1 for s in spokes if key(s) in graph.get(key(hub), set())),
            )
        )
    return structures


__all__ = [
    "TITLE_OVERLAP_THRESHOLD",
    "Cannibalisation",
    "ClusterStructure",
    "MappedKeyword",
    "cluster_structures",
    "find_cannibalisation",
]
