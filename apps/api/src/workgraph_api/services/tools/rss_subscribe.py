"""rss_subscribe — inline RSS/Atom parser (no feedparser dep).

Feeds are overwhelmingly boring: an `<item>` (RSS) or `<entry>` (Atom)
wrapping a title, link, description/summary, and published/pubDate. We
cover the fields the rest of the pipeline actually uses — the
MembraneAgent classifier reads `title` + `summary` when they're present
and falls back to `url` on the fetched content.

Reasons not to pull in feedparser:
  * Spec forbids heavy new deps.
  * Feedparser is ~700 KB and ships a second HTML parser we don't need —
    we already have the html.parser stripping inside fetch_url.py.
  * Real feeds deliver the same 5 fields; the gnarly bits feedparser
    handles are namespaces we don't cite.

Failure modes return `[]` and log once. Rationale mirrors fetch_url:
one bad feed must not abort a whole cron scan.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from workgraph_api.services.ssrf_guard import SSRFBlocked, safe_get

_log = logging.getLogger("workgraph.api.tools.rss")

_MAX_BYTES = 2_000_000  # 2 MB cap — generous for even pathological feeds.
_MAX_ITEMS = 25  # we classify each hit, so bound the per-feed burst.
_DEFAULT_USER_AGENT = "WorkGraphBot/1.0 (+https://graphflow.flyflow.love)"
_DEFAULT_TIMEOUT_S = 10

# Namespaces commonly found in Atom feeds. We accept both namespaced and
# plain tag names by stripping namespaces before comparison.
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


@dataclass(slots=True)
class RssItem:
    url: str
    title: str
    summary: str
    published_at: str  # ISO-ish; empty string if the feed didn't supply

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "published_at": self.published_at,
        }


def _localname(tag: str) -> str:
    # `{namespace}localname` -> `localname`; already-local tag passes through.
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _first_text(el: ET.Element, *names: str) -> str:
    """Return stripped text of the first child whose localname matches."""
    wanted = set(names)
    for child in el:
        if _localname(child.tag) in wanted:
            t = (child.text or "").strip()
            if t:
                return t
    return ""


def _first_href(el: ET.Element, *names: str) -> str:
    """Atom-style `<link href="..."/>` extraction."""
    wanted = set(names)
    for child in el:
        if _localname(child.tag) in wanted:
            href = child.attrib.get("href") or child.attrib.get("HREF")
            if href:
                return href.strip()
            # RSS puts the URL as child text.
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def _strip_html(s: str) -> str:
    if not s:
        return ""
    # Fast-path: the summary field is often HTML with <p>/<br>. A regex
    # tag-strip is fine for this field's scale (bounded by the item cap).
    no_tags = re.sub(r"<[^>]+>", " ", s)
    no_tags = re.sub(r"\s+", " ", no_tags).strip()
    return no_tags[:1000]


def _parse_items(root: ET.Element) -> list[RssItem]:
    out: list[RssItem] = []
    # Both `<item>` (RSS 2.0) and `<entry>` (Atom) live under the root.
    # .iter() includes the root itself, which is fine — we just check name.
    for el in root.iter():
        name = _localname(el.tag)
        if name not in ("item", "entry"):
            continue
        url = _first_href(el, "link")
        if not url:
            # RSS `<guid isPermaLink="true">` can stand in for a URL.
            url = _first_text(el, "guid")
        if not url:
            continue
        title = _first_text(el, "title")
        summary_raw = _first_text(
            el, "description", "summary", "content"
        )
        summary = _strip_html(summary_raw)
        published = _first_text(
            el, "pubDate", "published", "updated", "dc:date"
        )
        out.append(
            RssItem(
                url=url,
                title=title[:300],
                summary=summary,
                published_at=published[:64],
            )
        )
        if len(out) >= _MAX_ITEMS:
            break
    return out


async def rss_subscribe(
    feed_url: str,
    *,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    user_agent: str = _DEFAULT_USER_AGENT,
    max_items: int = _MAX_ITEMS,
) -> list[RssItem]:
    """Fetch + parse a feed. Returns up to `max_items` entries.

    Returns `[]` on any network / parse error so the cron path can move on
    to the next feed cleanly. The caller is responsible for dedup against
    existing MembraneSignalRow rows (source_identifier = item.url).
    """
    if not feed_url or not feed_url.lower().startswith(("http://", "https://")):
        return []
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            headers=headers,
        ) as client:
            resp = await safe_get(client, feed_url)
    except SSRFBlocked as exc:
        # Same translation as fetch_url: return empty so the cron path
        # moves on. The subscription endpoint caller treats `[]` as a
        # "no items" signal — not ideal for feedback on a blocked URL,
        # but the router-level validation (adding a subscription) can
        # do its own pre-flight check if sharper feedback is needed.
        _log.info(
            "rss blocked by ssrf guard",
            extra={"feed": feed_url, "reason": str(exc)},
        )
        return []
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        _log.info(
            "rss fetch error",
            extra={"feed": feed_url, "error": type(exc).__name__},
        )
        return []
    except Exception:
        _log.exception("rss unexpected fetch error", extra={"feed": feed_url})
        return []
    if resp.status_code >= 400:
        _log.info(
            "rss non-2xx",
            extra={"feed": feed_url, "status": resp.status_code},
        )
        return []

    body = resp.content[:_MAX_BYTES]
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        _log.info(
            "rss parse error",
            extra={"feed": feed_url, "error": str(exc)[:120]},
        )
        return []

    items = _parse_items(root)
    return items[:max_items]


__all__ = ["rss_subscribe", "RssItem"]
