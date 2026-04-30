"""RetrievalService — production §7.2 retrieval primitive.

Slice 5a of pickup #4. Wraps the BM25 + frecency-multiplier
primitives in `_retrieval_primitives.py` over real KbItemRow / etc.
rows. First consumer: `SkillsService._kb_search` (commit follows).

Architecture (slice 5a — BM25-only):

    RetrievalService.retrieve_kb_items(project_id, query, viewer_user_id, k)
      ─► pull viewer-visible KbItemRows (KbItemRepository.list_visible_for_user)
      ─► drop drafts/rejected/archived (matches existing _kb_search filter)
      ─► adapt to RetrievalDoc (id + title + content + frecency cols)
      ─► BM25Retriever.top_k(query, k=k * 2)            # over-fetch
      ─► apply frecency_multiplier per row               # §7.4
      ─► sort by adjusted score, return top-k

Slice 5b adds vector retrieval + RRF over BM25+vector. Slice 5c
wires the service into LicenseContextService.build_slice for agent
prompt assembly.

Index strategy (slice 5a): rebuild per call. KbItemRepository read
+ BM25 index construction at 5K rows is well under 100ms — well
inside the human-perceptible budget for a kb_search hit. When
retrieval moves to the chat hot path (slice 5c), we'll cache the
index per project with invalidation on row writes.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    KbItemRepository,
    KbItemRow,
    session_scope,
)

from ._retrieval_primitives import (
    BM25Retriever,
    RetrievalDoc,
    frecency_multiplier,
)

_log = logging.getLogger("workgraph.api.retrieval")

# Default candidate pool — over-fetches relative to caller's k so the
# frecency multiplier has a meaningful pool to re-rank within. ×2 is a
# pragmatic floor; tuning is a slice-5b concern once vector is in.
_OVERFETCH_FACTOR = 2

# Cap on the absolute candidate pool so a runaway request can't pull
# every kb item in a 5K-cell into memory.
_MAX_CANDIDATE_POOL = 200

# How many KbItemRows the repository fetches per call. Production cells
# top out at ~5K kb items per the Path B economic model; 1000 is the
# 80th-percentile working set the tightener feeds BM25.
_REPO_LIST_LIMIT = 1000


class RetrievalCandidate:
    """One ranked retrieval hit + the row + the score breakdown.

    `bm25_score` is the raw BM25 number; `frecency_multiplier` is the
    [1.0, 2.0] multiplier applied per §7.4; `score` is their product.
    Carries the underlying KbItemRow so callers don't need a second DB
    read to render the result.
    """

    __slots__ = ("row", "score", "bm25_score", "frecency_mult")

    def __init__(
        self,
        *,
        row: KbItemRow,
        bm25_score: float,
        frecency_mult: float,
    ) -> None:
        self.row = row
        self.bm25_score = bm25_score
        self.frecency_mult = frecency_mult
        self.score = bm25_score * frecency_mult


class RetrievalService:
    """Per-project §7.2 retrieval. Slice 5a is BM25-only over kb items.

    Stateless — every retrieve_kb_items call rebuilds the index from
    fresh DB rows. This is fine at slice-5a's call-site (kb_search,
    LLM-tool invocation, ~1 call per agent turn) and avoids cache
    invalidation complexity. Slice 5c will introduce a per-project
    cached index when retrieval moves to the chat hot path.
    """

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def retrieve_kb_items(
        self,
        *,
        project_id: str,
        query: str,
        viewer_user_id: str | None = None,
        k: int = 10,
    ) -> list[RetrievalCandidate]:
        """BM25 + frecency over kb items in the project.

        `query` is the raw user / LLM-emitted search string — bilingual
        zh + en supported by the tokenizer. Empty / whitespace-only
        queries return an empty list rather than an arbitrary recency
        slice (caller can fall back if needed).

        `viewer_user_id` controls visibility:
          * None (default) → GROUP-SCOPE ONLY. Matches the legacy
            `_kb_search` contract where results may persist into shared
            streams; including a user's personal items would leak them
            cross-viewer.
          * non-None → group items + that user's personal items.

        Filters applied BEFORE BM25 (matching the existing
        `_kb_search` semantics in services/skills.py):
          * scope: per `viewer_user_id` rule above
          * status not in {archived, draft, rejected}

        Filters applied AFTER BM25:
          * zero-score candidates dropped (no signal)
          * frecency multiplier re-ranks within over-fetched pool
          * top-k returned
        """
        q = (query or "").strip()
        if not q:
            return []

        try:
            k_val = max(1, int(k))
        except (TypeError, ValueError):
            k_val = 10

        async with session_scope(self._sessionmaker) as session:
            repo = KbItemRepository(session)
            if viewer_user_id:
                rows = await repo.list_visible_for_user(
                    project_id=project_id,
                    viewer_user_id=viewer_user_id,
                    limit=_REPO_LIST_LIMIT,
                )
            else:
                rows = await repo.list_group_for_project(
                    project_id=project_id,
                    limit=_REPO_LIST_LIMIT,
                )

        live_rows = [
            r for r in rows
            if r.status not in ("archived", "draft", "rejected")
        ]
        if not live_rows:
            return []

        docs = [_kb_row_to_doc(r) for r in live_rows]
        retriever = BM25Retriever(docs)

        # Over-fetch from BM25 so the frecency multiplier has room to
        # reorder within the candidate pool. The substring scan in the
        # legacy _kb_search returned at most 20; we cap at 200 to keep
        # per-call work bounded even for k=20 callers.
        pool_size = min(_MAX_CANDIDATE_POOL, k_val * _OVERFETCH_FACTOR)
        bm25_hits = retriever.top_k(q, k=pool_size)
        if not bm25_hits:
            return []

        # Hydrate each hit with the underlying row + frecency multiplier.
        row_by_id = {r.id: r for r in live_rows}
        candidates: list[RetrievalCandidate] = []
        for doc, bm25_score in bm25_hits:
            row = row_by_id.get(doc.id)
            if row is None:
                # Defensive — shouldn't happen since docs were built
                # from live_rows above.
                continue
            mult = frecency_multiplier(
                access_count=row.access_count,
                last_accessed_at=row.last_accessed_at,
            )
            candidates.append(
                RetrievalCandidate(
                    row=row,
                    bm25_score=bm25_score,
                    frecency_mult=mult,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k_val]


def _kb_row_to_doc(row: KbItemRow) -> RetrievalDoc:
    """Adapt KbItemRow → RetrievalDoc.

    Two row shapes coexist on KbItemRow (post-F4 fold):
      * `source='ingest'` rows carry classified raw_content +
        classification_json.summary
      * user-authored rows carry title + content_md

    For BM25 ingest rows mix `summary` (short, human label) into the
    title slot so titled-match weighting helps; raw_content is the
    body. User-authored rows pass title + content_md straight through.
    """
    if row.source == "ingest":
        classification = dict(row.classification_json or {})
        summary = str(classification.get("summary") or "").strip()
        # Synthesize a title-like string from the summary so the BM25
        # title-weight isn't wasted on these rows. raw_content stays
        # as the body.
        title = summary or (row.raw_content or "")[:80]
        content = row.raw_content or ""
    else:
        title = row.title or ""
        content = row.content_md or ""
    return RetrievalDoc(
        id=row.id,
        title=title,
        content=content,
        last_accessed_at=row.last_accessed_at,
        access_count=row.access_count,
    )


__all__ = ["RetrievalCandidate", "RetrievalService"]
