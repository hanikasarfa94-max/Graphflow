"""fetch_url — minimal HTTP fetch + HTML-to-text for Phase 2.A.

Called from two places:
    1. User-paste path    — a project member drops a link, we fetch once.
    2. Active-scan cron   — web_search returns URLs, we fetch each hit.

Design choices:
  * httpx is already in the dev group — no new dependency.
  * HTML stripping uses stdlib html.parser — we don't pull in bs4/lxml
    just for a 30-line tag stripper.
  * content_text is trimmed to 4000 chars, matching the existing
    MembraneService RAW_CONTENT_MAX_CHARS guard so the downstream
    MembraneAgent prompt surface area stays bounded.
  * content_hash is sha256 of the raw-fetched text so future re-visits
    can dedup on content (URL-level dedup lives in MembraneSignalRow).
  * Failures (network, non-200, oversize) return None and log once —
    the caller decides whether to surface the error. Paste path should
    bubble up a 400; cron silently skips.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

_log = logging.getLogger("workgraph.api.tools.fetch_url")

# Hard cap on how much HTML we will pull down. Anything larger is almost
# certainly a video / binary / noise page. The prompt-trim to 4000 chars
# happens after extraction; this cap guards transport.
_MAX_BYTES = 1_500_000

# Stored and prompt-facing content cap. Matches the existing
# MembraneService.RAW_CONTENT_MAX_CHARS so the prompt-injection surface
# area is unchanged.
_MAX_CHARS = 4000

_DEFAULT_USER_AGENT = "WorkGraphBot/1.0 (+https://graphflow.flyflow.love)"

# Tags whose inner text we should drop outright when flattening to text.
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "iframe", "head"}
)


@dataclass(slots=True)
class FetchResult:
    url: str
    title: str
    content_text: str
    content_hash: str
    fetched_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "content_text": self.content_text,
            "content_hash": self.content_hash,
            "fetched_at": self.fetched_at,
        }


class _TextExtractor(HTMLParser):
    """Flatten an HTML document to (title, body_text).

    Deliberately simple:
      * <title> text goes into `.title`
      * <script>/<style>/etc. contents are dropped
      * every other tag's character data is concatenated with single spaces
      * block-level tags (div, p, br, li, h[1-6]) insert a newline to
        preserve paragraph boundaries so the LLM gets coherent text
    """

    _BLOCKS = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "tr",
            "section",
            "article",
            "header",
            "footer",
            "nav",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = True
        if t in _SKIP_TAGS:
            self._skip_depth += 1
        if t in self._BLOCKS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
        if t in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if t in self._BLOCKS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title += data
            return
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse any whitespace run (spaces / tabs / newlines) to a
        # single space, then re-split paragraph breaks on double-newlines.
        cleaned = re.sub(r"[ \t]+", " ", raw)
        cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
        # Strip per-line leading/trailing whitespace.
        lines = [ln.strip() for ln in cleaned.splitlines()]
        return "\n".join(ln for ln in lines if ln)


def _looks_like_html(content_type: str | None, body: str) -> bool:
    ct = (content_type or "").lower()
    if "html" in ct or "xml" in ct:
        return True
    # Some feeds / APIs omit content-type. If we see a leading `<` on the
    # first non-whitespace character, assume markup.
    head = body[:256].lstrip()
    return head.startswith("<")


async def fetch_url(
    url: str,
    *,
    timeout_s: int = 10,
    user_agent: str = _DEFAULT_USER_AGENT,
    max_bytes: int = _MAX_BYTES,
    max_chars: int = _MAX_CHARS,
) -> FetchResult | None:
    """Fetch `url`, return FetchResult or None on any failure.

    `None` is the "don't surface this" signal — callers log + skip. Raising
    would be wrong for the cron path (one bad feed must not stop a whole
    scan); paste path translates None into a 400 at the router level.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        _log.info("fetch_url skipped non-http url", extra={"url": url})
        return None

    headers = {"User-Agent": user_agent, "Accept": "text/html,application/xml,*/*"}
    try:
        async with httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        _log.info(
            "fetch_url network error",
            extra={"url": url, "error": type(exc).__name__},
        )
        return None
    except Exception:
        _log.exception("fetch_url unexpected error", extra={"url": url})
        return None

    if resp.status_code >= 400:
        _log.info(
            "fetch_url non-2xx",
            extra={"url": url, "status": resp.status_code},
        )
        return None

    raw_bytes = resp.content[:max_bytes]
    # Prefer charset from headers; httpx picks a default when unknown.
    encoding = resp.encoding or "utf-8"
    try:
        body = raw_bytes.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        body = raw_bytes.decode("utf-8", errors="replace")

    content_type = resp.headers.get("content-type")
    if _looks_like_html(content_type, body):
        parser = _TextExtractor()
        try:
            parser.feed(body)
            parser.close()
        except Exception:
            _log.exception("fetch_url html parse failed", extra={"url": url})
            # Fall through to raw text — better to ingest something than nothing.
            title = ""
            text = body
        else:
            title = (parser.title or "").strip()
            text = parser.text()
    else:
        # Plain text / JSON / whatever — keep as-is.
        title = ""
        text = body

    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return FetchResult(
        url=url,
        title=title[:300],
        content_text=text,
        content_hash=digest,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["fetch_url", "FetchResult"]
