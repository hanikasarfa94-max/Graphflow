"""web_search — Tavily wrapper, env-gated.

Called by the active-scan cron. Tavily returns a concise list of search
hits (title, url, snippet) which the cron then feeds to fetch_url +
MembraneAgent.classify.

Env gate:
    TAVILY_API_KEY unset  → every call returns [] and logs once at info
    TAVILY_API_KEY set    → POST to https://api.tavily.com/search

The env gate means dev + CI can run without a Tavily key; the test
suite uses the monkeypatchable `_search_impl` hook to stub a deterministic
response without any network access.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

_log = logging.getLogger("workgraph.api.tools.web_search")

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_DEFAULT_TIMEOUT_S = 15
_ENV_MISSING_LOGGED = False


@dataclass(slots=True)
class SearchHit:
    url: str
    title: str
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "snippet": self.snippet}


def _log_missing_key_once() -> None:
    # Shared state so a cron running every 30 min doesn't spam info lines.
    global _ENV_MISSING_LOGGED
    if _ENV_MISSING_LOGGED:
        return
    _ENV_MISSING_LOGGED = True
    _log.info(
        "web_search: TAVILY_API_KEY unset — returning [] for every query "
        "(set the env var to enable the active-scan cron)"
    )


async def _tavily_post(
    *, query: str, api_key: str, max_results: int, timeout_s: int
) -> list[SearchHit]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        # Tavily's defaults include the raw text snippet which is what we
        # feed MembraneAgent; explicit for clarity.
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(_TAVILY_ENDPOINT, json=payload)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        _log.info(
            "tavily network error",
            extra={"error": type(exc).__name__},
        )
        return []
    except Exception:
        _log.exception("tavily unexpected error")
        return []
    if resp.status_code >= 400:
        _log.info(
            "tavily non-2xx",
            extra={"status": resp.status_code, "body": resp.text[:200]},
        )
        return []
    try:
        data = resp.json()
    except ValueError:
        _log.info("tavily response not json")
        return []
    results = data.get("results") or []
    hits: list[SearchHit] = []
    for item in results[:max_results]:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            SearchHit(
                url=url,
                title=(item.get("title") or "").strip()[:300],
                snippet=(item.get("content") or item.get("snippet") or "").strip()[
                    :1000
                ],
            )
        )
    return hits


async def web_search(
    query: str,
    *,
    max_results: int = 5,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> list[SearchHit]:
    """Fire one web search. Returns up to `max_results` hits or []."""
    query = (query or "").strip()
    if not query:
        return []
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        _log_missing_key_once()
        return []
    return await _tavily_post(
        query=query,
        api_key=api_key,
        max_results=max_results,
        timeout_s=timeout_s,
    )


__all__ = ["web_search", "SearchHit"]
