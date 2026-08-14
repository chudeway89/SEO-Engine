"""HTML parsing and extraction.

Everything the technical SEO engine needs is extracted here, once, from the
parsed tree: metadata, headings, links, images, hreflang, structured data,
readable text and the accessibility signals used by the agentic-web audit.

The extracted body text is returned as a plain string on :class:`CrawlPage` but
is *always* re-wrapped in ``UntrustedContent`` before it can reach an agent —
see ``CrawlPage.untrusted_text`` and ``AgentContextBuilder.add_external``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from seo_engine.schemas.crawl import (
    AccessibilitySignals,
    CrawlPage,
    Heading,
    HreflangEntry,
    Image,
    Link,
)
from seo_engine.shared.ids import utcnow
from seo_engine.shared.untrusted import scan_for_injection

#: Elements whose text is not page copy.
_NON_CONTENT_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")

_LANDMARK_TAGS = ("main", "nav", "header", "footer", "aside", "article", "section")

_WHITESPACE = re.compile(r"\s+")


def normalise_url(url: str, base: str | None = None) -> str:
    """Absolute, fragment-free, consistently formed URL."""
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    netloc = parsed.netloc.lower()
    if (parsed.scheme == "http" and netloc.endswith(":80")) or (
        parsed.scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]
    path = parsed.path or "/"
    return parsed._replace(netloc=netloc, path=path).geturl()


def registrable_domain(url_or_host: str) -> str:
    host = urlparse(url_or_host).netloc or url_or_host
    return host.split("@")[-1].split(":")[0].lower().removeprefix("www.")


def is_same_site(url: str, allowed_domains: set[str], *, include_subdomains: bool) -> bool:
    host = registrable_domain(url)
    if host in allowed_domains:
        return True
    if include_subdomains:
        return any(host.endswith(f".{domain}") for domain in allowed_domains)
    return False


class PageParser:
    """Turns an HTTP response into a fully populated :class:`CrawlPage`."""

    def __init__(self, *, allowed_domains: set[str], include_subdomains: bool = False) -> None:
        self.allowed_domains = allowed_domains
        self.include_subdomains = include_subdomains

    def parse(
        self,
        *,
        url: str,
        html: str,
        status_code: int,
        content_type: str | None = None,
        final_url: str | None = None,
        depth: int = 0,
        discovered_from: str | None = None,
        redirect_chain: list[str] | None = None,
        response_time_ms: int | None = None,
        x_robots_tag: list[str] | None = None,
    ) -> CrawlPage:
        base = final_url or url
        soup = BeautifulSoup(html, "lxml")

        text_content = self._extract_text(soup)
        page = CrawlPage(
            url=url,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            depth=depth,
            discovered_from=discovered_from,
            title=self._title(soup),
            meta_description=self._meta(soup, "description"),
            meta_robots=self._robots_directives(soup),
            x_robots_tag=[d.strip().lower() for d in (x_robots_tag or [])],
            canonical_url=self._canonical(soup, base),
            lang=self._lang(soup),
            headings=self._headings(soup),
            links=self._links(soup, base),
            images=self._images(soup, base),
            hreflang=self._hreflang(soup, base),
            schema_blocks=self._structured_data(soup),
            open_graph=self._open_graph(soup),
            text_content=text_content,
            word_count=len(text_content.split()),
            content_hash=hashlib.sha256(text_content.encode()).hexdigest(),
            html_bytes=len(html.encode("utf-8", "ignore")),
            response_time_ms=response_time_ms,
            redirect_chain=redirect_chain or [],
            accessibility=self._accessibility(soup, text_content),
            fetched_at=utcnow(),
        )
        # Detect, at the point of extraction, whether this page is trying to
        # talk to the model.  Recorded as data; never acted on.
        page.injection_findings = [f.to_dict() for f in scan_for_injection(text_content)]
        return page

    # ------------------------------------------------------------------
    def _title(self, soup: BeautifulSoup) -> str | None:
        tag = soup.find("title")
        return _clean(tag.get_text()) if tag else None

    def _meta(self, soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
        if tag and tag.get("content"):
            return _clean(str(tag["content"]))
        return None

    def _robots_directives(self, soup: BeautifulSoup) -> list[str]:
        directives: list[str] = []
        for tag in soup.find_all("meta"):
            name = str(tag.get("name", "")).lower()
            # `googlebot` is a robots directive too, and is frequently the one
            # that actually carries `noindex`.
            if name in {"robots", "googlebot"} and tag.get("content"):
                directives.extend(
                    d.strip().lower() for d in str(tag["content"]).split(",") if d.strip()
                )
        return list(dict.fromkeys(directives))

    def _canonical(self, soup: BeautifulSoup, base: str) -> str | None:
        for tag in soup.find_all("link", href=True):
            if _has_rel(tag, "canonical"):
                return normalise_url(str(tag["href"]), base)
        return None

    def _lang(self, soup: BeautifulSoup) -> str | None:
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            return str(html_tag["lang"]).strip()
        return None

    def _headings(self, soup: BeautifulSoup) -> list[Heading]:
        headings: list[Heading] = []
        for level in range(1, 7):
            for tag in soup.find_all(f"h{level}"):
                text = _clean(tag.get_text())
                if text:
                    headings.append(Heading(level=level, text=text[:500]))
        return headings

    def _links(self, soup: BeautifulSoup, base: str) -> list[Link]:
        links: list[Link] = []
        seen: set[tuple[str, str]] = set()
        for tag in soup.find_all("a"):
            href = tag.get("href")
            if not href:
                continue
            href = str(href).strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                continue
            absolute = normalise_url(href, base)
            if not urlparse(absolute).scheme.startswith("http"):
                continue
            anchor = _clean(tag.get_text())[:500]
            key = (absolute, anchor)
            if key in seen:
                continue
            seen.add(key)
            rel_attr = tag.get("rel") or []
            rel = [r.lower() for r in (rel_attr if isinstance(rel_attr, list) else [rel_attr])]
            links.append(
                Link(
                    url=absolute,
                    anchor_text=anchor,
                    rel=rel,
                    is_internal=is_same_site(
                        absolute, self.allowed_domains, include_subdomains=self.include_subdomains
                    ),
                )
            )
        return links

    def _images(self, soup: BeautifulSoup, base: str) -> list[Image]:
        images: list[Image] = []
        for tag in soup.find_all("img"):
            src = tag.get("src") or tag.get("data-src")
            if not src:
                continue
            alt = tag.get("alt")
            images.append(
                Image(
                    src=normalise_url(str(src), base),
                    # An absent alt attribute and alt="" are different things:
                    # the latter is a valid decorative-image declaration.
                    alt=None if alt is None else str(alt),
                    title=str(tag["title"]) if tag.get("title") else None,
                    width=_int_or_none(tag.get("width")),
                    height=_int_or_none(tag.get("height")),
                    loading=str(tag["loading"]) if tag.get("loading") else None,
                )
            )
        return images

    def _hreflang(self, soup: BeautifulSoup, base: str) -> list[HreflangEntry]:
        entries: list[HreflangEntry] = []
        for tag in soup.find_all("link", href=True):
            if not _has_rel(tag, "alternate"):
                continue
            lang = tag.get("hreflang")
            href = tag.get("href")
            if lang and href:
                entries.append(
                    HreflangEntry(lang=str(lang).strip(), url=normalise_url(str(href), base))
                )
        return entries

    def _structured_data(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
            raw = tag.string or tag.get_text()
            if not raw or not raw.strip():
                blocks.append(
                    {"_format": "json-ld", "_parse_error": "empty JSON-LD block", "_raw": ""}
                )
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                # Invalid structured data is a finding, not something to discard.
                blocks.append(
                    {
                        "_format": "json-ld",
                        "_parse_error": f"invalid JSON: {exc.msg} (line {exc.lineno})",
                        "_raw": raw[:2000],
                    }
                )
                continue
            for item in parsed if isinstance(parsed, list) else [parsed]:
                if isinstance(item, dict):
                    blocks.append({"_format": "json-ld", **item})
        for tag in soup.find_all(attrs={"itemscope": True}):
            item_type = tag.get("itemtype")
            if item_type:
                blocks.append({"_format": "microdata", "@type": str(item_type).split("/")[-1]})
        return blocks

    def _open_graph(self, soup: BeautifulSoup) -> dict[str, str]:
        data: dict[str, str] = {}
        for tag in soup.find_all("meta", attrs={"property": re.compile("^og:", re.I)}):
            if tag.get("content"):
                data[str(tag["property"]).lower()] = str(tag["content"])[:500]
        return data

    def _extract_text(self, soup: BeautifulSoup) -> str:
        clone = BeautifulSoup(str(soup), "lxml")
        for tag in clone.find_all(_NON_CONTENT_TAGS):
            tag.decompose()
        body = clone.find("body") or clone
        return _clean(body.get_text(" "))

    def _accessibility(self, soup: BeautifulSoup, text: str) -> AccessibilitySignals:
        buttons = soup.find_all("button") + soup.find_all(
            "input", attrs={"type": re.compile("^(button|submit|reset)$", re.I)}
        )
        named_buttons = sum(1 for b in buttons if _accessible_name(b))
        links = soup.find_all("a", href=True)
        named_links = sum(1 for a in links if _accessible_name(a))

        controls = soup.find_all(["input", "select", "textarea"])
        controls = [c for c in controls if str(c.get("type", "")).lower() != "hidden"]
        labelled = sum(1 for c in controls if _has_label(soup, c))

        images = soup.find_all("img")
        landmarks = [tag for tag in _LANDMARK_TAGS if soup.find(tag)]
        scripts = soup.find_all("script")

        return AccessibilitySignals(
            semantic_landmarks=landmarks,
            buttons_total=len(buttons),
            buttons_with_accessible_name=named_buttons,
            links_total=len(links),
            links_with_accessible_name=named_links,
            forms_total=len(soup.find_all("form")),
            form_controls_total=len(controls),
            form_controls_labelled=labelled,
            images_total=len(images),
            images_with_alt=sum(1 for i in images if i.get("alt") is not None),
            has_main_landmark=bool(soup.find("main") or soup.find(attrs={"role": "main"})),
            has_skip_link=any("skip" in _clean(a.get_text()).lower()[:40] for a in links[:5]),
            heading_order_valid=_heading_order_valid(soup),
            aria_roles=sorted(
                {str(t["role"]).lower() for t in soup.find_all(attrs={"role": True})}
            ),
            tabindex_positive_count=sum(
                1
                for t in soup.find_all(attrs={"tabindex": True})
                if _int_or_none(t.get("tabindex")) and int(t["tabindex"]) > 0
            ),
            script_tags=len(scripts),
            noscript_present=bool(soup.find("noscript")),
            body_text_chars=len(text),
            # Very little text alongside many scripts is the signature of a page
            # whose content only exists after JavaScript runs.
            rendered_by_javascript=len(text) < 200 and len(scripts) >= 3,
        )


# ---------------------------------------------------------------------------
def _has_rel(tag: Tag, value: str) -> bool:
    """Check a rel token.

    BeautifulSoup exposes ``rel`` as a list, but passes each element separately
    to an attribute filter, so a naive ``rel=lambda v: value in v`` silently
    matches nothing.  Normalising here avoids that trap.
    """
    rel = tag.get("rel") or []
    tokens = rel if isinstance(rel, list) else str(rel).split()
    return value.lower() in {str(token).lower() for token in tokens}


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _accessible_name(tag: Tag) -> str:
    for attribute in ("aria-label", "title", "alt", "value"):
        value = tag.get(attribute)
        if value and str(value).strip():
            return str(value).strip()
    if tag.get("aria-labelledby"):
        return str(tag["aria-labelledby"])
    text = _clean(tag.get_text())
    if text:
        return text
    image = tag.find("img")
    if image is not None and image.get("alt"):
        return str(image["alt"])
    return ""


def _has_label(soup: BeautifulSoup, control: Tag) -> bool:
    if control.get("aria-label") or control.get("aria-labelledby") or control.get("title"):
        return True
    control_id = control.get("id")
    if control_id and soup.find("label", attrs={"for": control_id}):
        return True
    return control.find_parent("label") is not None


def _heading_order_valid(soup: BeautifulSoup) -> bool:
    levels = [int(t.name[1]) for t in soup.find_all(re.compile("^h[1-6]$"))]
    previous = 0
    for level in levels:
        if previous and level > previous + 1:
            return False
        previous = level
    return True


__all__ = [
    "PageParser",
    "is_same_site",
    "normalise_url",
    "registrable_domain",
]
