"""Phase 2.A — active-membrane external-world tools.

Three thin wrappers the cron / paste path calls:
    * fetch_url      — HTTP fetch + HTML-to-text, used by both paste + RSS.
    * rss_subscribe  — minimal feed parser (no feedparser dep).
    * web_search     — Tavily wrapper, env-gated via TAVILY_API_KEY.

None of these touch the DB. They produce structured payloads that
`services/membrane_ingest.py` feeds into MembraneAgent.classify before
anything becomes a MembraneSignalRow.
"""
from __future__ import annotations

from .fetch_url import FetchResult, fetch_url
from .rss_subscribe import RssItem, rss_subscribe
from .web_search import SearchHit, web_search

__all__ = [
    "fetch_url",
    "FetchResult",
    "rss_subscribe",
    "RssItem",
    "web_search",
    "SearchHit",
]
