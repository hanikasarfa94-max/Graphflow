"""MembraneIngestService — Phase 2.A active-side orchestration.

The existing `services/membrane.py` handles the *receiving* side: a
(source_kind, source_identifier, raw_content) arrives and flows through
MembraneAgent.classify + the auto-approve gate. This module builds the
*fetching* side the vision §5.12 active membrane needs:

    1. User paste           — project member drops a URL in the composer
    2. RSS subscription     — per-project feed rows polled on a cron
    3. Active search        — cron invents queries, fires Tavily

All three entry points converge on `MembraneService.ingest`, so the
existing prompt-injection defense, auto-approve gate, and dedup logic
are preserved. This service NEVER mutates the graph directly — it only
adds MembraneSignalRow proposals that still need human confirmation
through the existing membrane-card UX.

Security contract (mirrors services/license_lint.py precedent):
  * Externally-ingested content is classified by MembraneAgent before
    any routing decision, and MembraneAgent's system prompt tells the
    LLM to treat the content as data, not instructions.
  * Soft-blocks (safety_notes non-empty / confidence < 0.7 / proposed
    action == 'flag-for-review') keep status='pending-review' — the
    human-confirmable default.
  * The owner-only subscription / scan-now routes mean only a trusted
    project member can *configure* external feeds. Ingest itself is
    open to any member (anyone can drop a link for their project).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    KbIngestRepository,
    MembraneSubscriptionRepository,
    ProjectRow,
    session_scope,
)
from sqlalchemy import select

from .license_context import LicenseContextService
from .membrane import MembraneService
from .tools import fetch_url, rss_subscribe, web_search

_log = logging.getLogger("workgraph.api.membrane_ingest")

# Max chars we feed MembraneAgent per item. Mirrors RAW_CONTENT_MAX_CHARS
# inside services/membrane.py — the service trims again defensively, but
# we keep the prompt small from the start.
_MAX_CONTENT_CHARS = 4000

# How many active-scan queries the cron generates per project per run.
# 3–5 balances signal surface against LLM/Tavily cost.
_ACTIVE_QUERIES_MIN = 3
_ACTIVE_QUERIES_MAX = 5

# Regex used by the user-paste path to extract a URL from a casual note
# ("check this out: https://..."). Kept in this module so both the
# router and the composer client can share the contract via a tested
# Python path. Intentionally permissive: we fetch first, let the HTTP
# layer bounce bogus URLs.
_URL_RE = re.compile(
    r"https?://[^\s<>\"'\[\]{}]+",
    flags=re.IGNORECASE,
)


def extract_first_url(text: str) -> str | None:
    """Return the first http(s) URL in `text`, or None."""
    if not text:
        return None
    m = _URL_RE.search(text)
    return m.group(0) if m else None


def _normalize_url(url: str) -> str:
    """Strip obvious tracking noise + trailing punctuation.

    We do NOT lowercase — paths are case-sensitive. We do drop common
    utm_* params because the dedup key is (project_id, source_identifier),
    and we'd rather two paste-throughs of `?utm_source=twitter` vs
    `?utm_source=slack` dedup.
    """
    url = url.strip().rstrip(".,;:!?")
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    if not query:
        return base
    kept = [
        kv
        for kv in query.split("&")
        if kv and not kv.lower().startswith(("utm_", "ref=", "ref_src="))
    ]
    if not kept:
        return base
    return f"{base}?{'&'.join(kept)}"


class MembraneIngestService:
    """Active-side orchestration. Holds no state — all persistence goes
    through MembraneService / MembraneSubscriptionRepository.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        membrane_service: MembraneService,
        license_context_service: LicenseContextService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._membrane = membrane_service
        self._license_context = license_context_service

    # ---- URL paste --------------------------------------------------

    async def ingest_url(
        self,
        *,
        project_id: str,
        url: str,
        source_user_id: str | None,
        note: str | None = None,
        source_kind: str = "user-drop",
    ) -> dict[str, Any]:
        """Fetch `url`, classify, persist a MembraneSignalRow proposal.

        Returns the MembraneService.ingest shape:
            {ok, created, routed_count, signal, classified?}
        or {ok: False, error: 'fetch_failed' | 'project_not_found'}.
        """
        normalized = _normalize_url(url)

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}

            # Dedup pre-check — same (project, URL) returns existing row
            # without a fresh fetch. MembraneService.ingest will dedup
            # again, but skipping the HTTP round-trip saves latency.
            existing = await KbIngestRepository(session).find_by_source(
                project_id=project_id,
                source_identifier=normalized,
            )
            if existing is not None:
                return {
                    "ok": True,
                    "created": False,
                    "routed_count": 0,
                    "signal": self._membrane._signal_payload(existing),
                    "classified": bool(existing.classification_json),
                }

        fetch = await fetch_url(normalized)
        if fetch is None:
            return {"ok": False, "error": "fetch_failed"}

        raw_content = self._build_raw(
            title=fetch.title, body=fetch.content_text, note=note
        )
        return await self._membrane.ingest(
            project_id=project_id,
            source_kind=source_kind,
            source_identifier=normalized,
            raw_content=raw_content,
            ingested_by_user_id=source_user_id,
        )

    # ---- Subscription CRUD ------------------------------------------

    async def create_subscription(
        self,
        *,
        project_id: str,
        kind: str,
        url_or_query: str,
        created_by_user_id: str | None,
    ) -> dict[str, Any]:
        if kind not in ("rss", "search_query"):
            return {"ok": False, "error": "invalid_kind"}
        val = (url_or_query or "").strip()
        if not val:
            return {"ok": False, "error": "empty_value"}
        if kind == "rss" and not val.lower().startswith(("http://", "https://")):
            return {"ok": False, "error": "invalid_rss_url"}
        if len(val) > 1000:
            return {"ok": False, "error": "value_too_long"}

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}
            row = await MembraneSubscriptionRepository(session).create(
                project_id=project_id,
                kind=kind,
                url_or_query=val,
                created_by_user_id=created_by_user_id,
            )
            payload = _subscription_payload(row)
        return {"ok": True, "subscription": payload}

    async def list_subscriptions(
        self, project_id: str, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await MembraneSubscriptionRepository(
                session
            ).list_for_project(project_id, active_only=active_only)
            return [_subscription_payload(r) for r in rows]

    async def deactivate_subscription(
        self, *, project_id: str, sub_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = MembraneSubscriptionRepository(session)
            row = await repo.get(sub_id)
            if row is None or row.project_id != project_id:
                return {"ok": False, "error": "not_found"}
            row.active = False
            await session.flush()
            return {"ok": True, "subscription": _subscription_payload(row)}

    # ---- RSS polling ------------------------------------------------

    async def poll_rss_subscriptions(
        self, project_id: str
    ) -> dict[str, Any]:
        """Iterate active RSS subscriptions for this project; ingest new items.

        Returns {ok, polled, new_signals}. Dedup against existing signals
        is handled inside MembraneService.ingest.
        """
        async with session_scope(self._sessionmaker) as session:
            subs = await MembraneSubscriptionRepository(
                session
            ).list_for_project(project_id)
        rss_subs = [s for s in subs if s.kind == "rss"]
        polled = 0
        new_signals = 0
        for sub in rss_subs:
            try:
                items = await rss_subscribe(sub.url_or_query)
            except Exception:
                _log.exception(
                    "rss poll crashed for subscription",
                    extra={"sub_id": sub.id},
                )
                continue
            polled += 1
            for item in items:
                normalized = _normalize_url(item.url)
                raw = self._build_raw(
                    title=item.title,
                    body=item.summary,
                    note=None,
                )
                outcome = await self._membrane.ingest(
                    project_id=project_id,
                    source_kind="rss",
                    source_identifier=normalized,
                    raw_content=raw,
                    ingested_by_user_id=None,
                )
                if outcome.get("ok") and outcome.get("created"):
                    new_signals += 1
            # Record last_polled so the UI can show "polled 5 min ago".
            async with session_scope(self._sessionmaker) as session:
                await MembraneSubscriptionRepository(session).mark_polled(
                    sub.id
                )
        return {"ok": True, "polled": polled, "new_signals": new_signals}

    # ---- Active web-search scan -------------------------------------

    async def run_active_scan(
        self, project_id: str
    ) -> dict[str, Any]:
        """Generate queries from project context, fire web_search, ingest hits.

        Each hit becomes a MembraneSignalRow proposal scoped to this
        project. Tavily env-unset returns [] cleanly (web_search is
        env-gated), so this is safe to wire as a cron in dev without
        any secret.
        """
        queries = await self._build_scan_queries(project_id)
        hits_total = 0
        new_signals = 0
        seen_urls: set[str] = set()
        for query in queries:
            try:
                hits = await web_search(query, max_results=5)
            except Exception:
                _log.exception(
                    "web_search crashed", extra={"query": query}
                )
                continue
            for hit in hits:
                url = _normalize_url(hit.url)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                hits_total += 1
                raw = self._build_raw(
                    title=hit.title,
                    body=hit.snippet,
                    note=f"matched query: {query}",
                )
                outcome = await self._membrane.ingest(
                    project_id=project_id,
                    source_kind="rss",  # reuses an existing allowed kind
                    source_identifier=url,
                    raw_content=raw,
                    ingested_by_user_id=None,
                )
                if outcome.get("ok") and outcome.get("created"):
                    new_signals += 1

        # Also poll standing search_query subscriptions explicitly, so
        # the owner's pinned queries refresh on the same tick.
        async with session_scope(self._sessionmaker) as session:
            subs = await MembraneSubscriptionRepository(
                session
            ).list_for_project(project_id)
        for sub in [s for s in subs if s.kind == "search_query"]:
            try:
                hits = await web_search(sub.url_or_query, max_results=5)
            except Exception:
                _log.exception(
                    "web_search (sub) crashed", extra={"sub_id": sub.id}
                )
                continue
            for hit in hits:
                url = _normalize_url(hit.url)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                hits_total += 1
                raw = self._build_raw(
                    title=hit.title,
                    body=hit.snippet,
                    note=f"matched subscription: {sub.url_or_query}",
                )
                outcome = await self._membrane.ingest(
                    project_id=project_id,
                    source_kind="rss",
                    source_identifier=url,
                    raw_content=raw,
                    ingested_by_user_id=None,
                )
                if outcome.get("ok") and outcome.get("created"):
                    new_signals += 1
            async with session_scope(self._sessionmaker) as session:
                await MembraneSubscriptionRepository(session).mark_polled(
                    sub.id
                )

        return {
            "ok": True,
            "queries": queries,
            "hits": hits_total,
            "new_signals": new_signals,
        }

    # ---- internals --------------------------------------------------

    async def _build_scan_queries(self, project_id: str) -> list[str]:
        """Produce 3-5 search queries seeded by project context.

        Strategy: derive a handful of keyword candidates from the project
        title + its recent decisions / commitments / wiki items (via
        LicenseContextService.build_slice so we respect the tier model —
        the cron runs as a synthetic full-tier viewer because the signals
        it emits will be re-scoped per-recipient downstream).

        A proper LLM-based generator is nice-to-have but out of scope for
        the MVP: the MembraneAgent still filters irrelevant hits, and the
        owner can pin standing search_query subscriptions for precision.
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return []
            title = project.title or ""

        # Slice for recent-decision context. `build_slice` expects a viewer
        # uid; pass the project id as a synthetic "system" to get the
        # full-tier raw slice (observer scope would hide too much at
        # cron time).
        try:
            slice_ = await self._license_context._raw_slice(project_id)
        except Exception:
            _log.exception(
                "license context raw slice failed",
                extra={"project_id": project_id},
            )
            slice_ = {}

        candidates: list[str] = []
        if title.strip():
            candidates.append(title.strip())

        decisions = slice_.get("decisions") or []
        for d in decisions[:3]:
            rationale = (d.get("rationale") or "").strip()
            if rationale:
                candidates.append(f"{title} {rationale[:80]}".strip())

        graph = slice_.get("graph") or {}
        for goal in (graph.get("goals") or [])[:2]:
            gtitle = (goal.get("title") or "").strip()
            if gtitle:
                candidates.append(f"{title} {gtitle}".strip()[:140])
        for risk in (graph.get("risks") or [])[:2]:
            rtitle = (risk.get("title") or "").strip()
            if rtitle:
                candidates.append(f"{title} {rtitle}".strip()[:140])

        # De-dup preserving order, bound to min/max.
        seen: set[str] = set()
        dedup: list[str] = []
        for q in candidates:
            q_norm = q.lower().strip()
            if not q_norm or q_norm in seen:
                continue
            seen.add(q_norm)
            dedup.append(q)
            if len(dedup) >= _ACTIVE_QUERIES_MAX:
                break

        # If we didn't reach the floor, keep going with the title as the
        # fallback (we still emit at least one query so the scan isn't a
        # no-op on cold projects — Tavily just returns fewer hits).
        while len(dedup) < _ACTIVE_QUERIES_MIN and title.strip():
            filler = f"{title} updates"
            if filler.lower() in seen:
                break
            seen.add(filler.lower())
            dedup.append(filler)

        return dedup[:_ACTIVE_QUERIES_MAX]

    @staticmethod
    def _build_raw(*, title: str, body: str, note: str | None) -> str:
        """Compose the raw_content blob fed to MembraneAgent.classify.

        Prefix with title + optional note so the classifier has framing
        context. Downstream trimmed to _MAX_CONTENT_CHARS.
        """
        parts: list[str] = []
        if note:
            parts.append(f"[note] {note}")
        if title:
            parts.append(f"[title] {title}")
        if body:
            parts.append(body)
        blob = "\n".join(p for p in parts if p).strip()
        if len(blob) > _MAX_CONTENT_CHARS:
            blob = blob[:_MAX_CONTENT_CHARS]
        return blob


def _subscription_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "url_or_query": row.url_or_query,
        "created_by_user_id": row.created_by_user_id,
        "active": bool(row.active),
        "last_polled_at": (
            row.last_polled_at.isoformat() if row.last_polled_at else None
        ),
        "created_at": (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


__all__ = [
    "MembraneIngestService",
    "extract_first_url",
]
