"""RetrievalService — production §7.2 retrieval primitive.

Slices 5a (BM25 only) + 5b (BM25 + vector via RRF). Slice 5c will
wire it into LicenseContextService.build_slice for agent prompt
assembly.

Pipeline (slice 5b — RRF when embeddings wired, BM25 fallback else):

    RetrievalService.retrieve_kb_items(project_id, query, viewer_user_id, k)
      ─► pull viewer-visible KbItemRows
      ─► drop drafts/rejected/archived
      ─► adapt to RetrievalDoc (id + title + content + frecency cols)
      ─► BM25Retriever.top_k(query, k=pool)
      ─► IF embedding_client wired AND cache reasonably warm:
            ensure all docs + query are embedded (lazy fill, capped)
            VectorRetriever.top_k(query_vec, k=pool)
            reciprocal_rank_fusion([bm25_hits, vector_hits], weights)
         ELSE:
            bm25_hits as the fused list
      ─► apply frecency_multiplier per row (§7.4)
      ─► sort by adjusted score, return top-k

When the embedding cache is COLD (more misses than `_INLINE_EMBED_CAP`),
slice 5b falls back to BM25-only for that call. Callers can warm the
cache explicitly via `warm_kb_items()` (CLI or boot hook). This keeps
per-call latency bounded at the cost of degraded ranking on the very
first call against a cold project.

Eval-validated weights (slice 4 / 2505-node corpus): BM25 1.0, vector
1.0. The RRF f1 jumps from 0.700 (BM25 alone) / 0.727 (vector alone)
to 0.818 fused. Heavier weighting on vector hurts at this scale.

Index strategy: rebuild per call (slices 5a/5b). At 5K rows BM25
index is <100ms; vector index is just a list-lookup over cached
embeddings. Per-project caching with write-invalidation lands in
slice 5c when retrieval moves to the chat hot path.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    KbItemRepository,
    KbItemRow,
    session_scope,
)

from ._embeddings import (
    EmbeddingClient,
    EmbeddingsCache,
    content_hash,
    embed_with_cache,
)
from ._retrieval_primitives import (
    BM25Retriever,
    RetrievalDoc,
    VectorRetriever,
    frecency_multiplier,
    reciprocal_rank_fusion,
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

# Slice 5b — when more docs than this need embedding inline on a single
# `retrieve_kb_items` call, fall back to BM25-only this time and let an
# explicit `warm_kb_items` call (CLI / boot hook) handle bulk warming.
# Bounded by SF embedding latency: 50 docs at concurrency 16 ≈ 4 batches
# × ~1.5s = ~6s — well above human-perceptible budget but acceptable
# for an LLM-tool call. Tune down if production p95 latency suffers.
_INLINE_EMBED_CAP = 50

# Slice 5b — RRF weights for BM25 + vector. Validated by the slice-4
# eval at 2505 nodes: equal weights (1.0 / 1.0) produced F1=0.818 vs
# vector-alone 0.727 / BM25-alone 0.700. Heavier weighting on either
# layer hurt in the eval; left at 1:1 here.
_RRF_WEIGHT_BM25 = 1.0
_RRF_WEIGHT_VECTOR = 1.0

# Default cache file for kb-item embeddings. Single global file —
# content-hash-keyed means duplicate text across projects dedupes
# naturally. Garbage collection of orphaned hashes (e.g. when a kb item
# is deleted or edited) is a future concern; embeddings don't expire
# on their own.
_DEFAULT_CACHE_PATH = Path("data/embeddings/kb_items.json")


class RetrievalCandidate:
    """One ranked retrieval hit + the row + the score breakdown.

    `pre_freq_score` is the BM25 number when retrieval ran in BM25-only
    mode, or the RRF fused score when both layers ran. `frecency_mult`
    is the [1.0, 2.0] multiplier applied per §7.4. `score` is their
    product — what the candidates are sorted on.

    `retrieval_mode` documents which path produced the score so callers
    (and tests) can tell BM25-only fallbacks from full RRF runs.
    Carries the underlying KbItemRow so callers don't need a second DB
    read to render the result.
    """

    __slots__ = ("row", "score", "pre_freq_score", "frecency_mult", "retrieval_mode")

    def __init__(
        self,
        *,
        row: KbItemRow,
        pre_freq_score: float,
        frecency_mult: float,
        retrieval_mode: str,
    ) -> None:
        self.row = row
        self.pre_freq_score = pre_freq_score
        self.frecency_mult = frecency_mult
        self.score = pre_freq_score * frecency_mult
        self.retrieval_mode = retrieval_mode


class RetrievalService:
    """Per-project §7.2 retrieval over kb items.

    Slice 5a shipped BM25-only. Slice 5b adds vector + RRF fusion when
    an EmbeddingClient + cache are wired (production: SiliconFlow +
    `data/embeddings/kb_items.json`); falls back to BM25-only when not
    (legacy callers, tests that skip the embedding stub, or when a
    project's cache is too cold to fill inline).

    Stateless: every retrieve_kb_items call rebuilds the indices from
    fresh DB rows + cache reads. Fine at slice-5a/b's call-site
    (kb_search, ~1 call per agent turn). Per-project caching with
    write-invalidation lands in slice 5c when retrieval moves to the
    chat hot path.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        *,
        embedding_client: EmbeddingClient | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedding_client = embedding_client
        # Cache is constructed even when embedding_client is None so
        # `warm_kb_items` and tests can pre-populate the cache without
        # needing the client. retrieve_kb_items only consults the
        # cache when embedding_client is present.
        self._cache_path = cache_path or _DEFAULT_CACHE_PATH
        self._cache: EmbeddingsCache | None = None

    def _get_cache(self) -> EmbeddingsCache:
        """Lazy-construct the cache on first access.

        Avoids the disk read at process startup. Reload-from-disk on
        every call would defeat the cache; production wiring keeps
        one RetrievalService instance for the process lifetime.
        """
        if self._cache is None:
            self._cache = EmbeddingsCache(self._cache_path)
        return self._cache

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

        # Over-fetch from BM25 so the frecency multiplier (and vector
        # layer if wired) have room to reorder within the candidate
        # pool. Cap at 200 to keep per-call work bounded.
        pool_size = min(_MAX_CANDIDATE_POOL, k_val * _OVERFETCH_FACTOR)
        bm25_hits = retriever.top_k(q, k=pool_size)
        if not bm25_hits:
            return []

        # Slice 5b — try the vector layer if embeddings are wired.
        # Falls back to BM25-only on cache miss / capped fill / errors.
        retrieval_mode = "bm25"
        ranked = bm25_hits
        if self._embedding_client is not None:
            vector_hits = await self._maybe_vector_top_k(
                docs=docs, query=q, k=pool_size
            )
            if vector_hits is not None:
                ranked = reciprocal_rank_fusion(
                    [bm25_hits, vector_hits],
                    k=pool_size,
                    weights=[_RRF_WEIGHT_BM25, _RRF_WEIGHT_VECTOR],
                )
                retrieval_mode = "bm25+vector"

        # Hydrate each hit with the underlying row + frecency multiplier.
        row_by_id = {r.id: r for r in live_rows}
        candidates: list[RetrievalCandidate] = []
        for doc, pre_freq_score in ranked:
            row = row_by_id.get(doc.id)
            if row is None:
                continue
            mult = frecency_multiplier(
                access_count=row.access_count,
                last_accessed_at=row.last_accessed_at,
            )
            candidates.append(
                RetrievalCandidate(
                    row=row,
                    pre_freq_score=pre_freq_score,
                    frecency_mult=mult,
                    retrieval_mode=retrieval_mode,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k_val]

    async def _maybe_vector_top_k(
        self,
        *,
        docs: list[RetrievalDoc],
        query: str,
        k: int,
    ) -> list[tuple[RetrievalDoc, float]] | None:
        """Try to produce a vector rank list. Return None on fallback.

        Fallback conditions (caller drops to BM25-only):
          * embedding client raises (network, auth, rate limit)
          * the corpus has more cache misses than `_INLINE_EMBED_CAP`
            (don't burn ~30s embedding 5K docs on a single query)
          * any per-doc embedding ends up zero-norm (defensive)
        """
        cache = self._get_cache()
        # Map each doc to (content_hash, embedding_text). Embedding
        # text mirrors the eval's `_embedding_text` helper — title is
        # repeated twice so it's a stronger signal in the embedding.
        embed_inputs: list[tuple[RetrievalDoc, str, str]] = []
        for doc in docs:
            text = _embedding_text(doc)
            embed_inputs.append((doc, content_hash(text), text))

        misses = [
            (d, h, t) for d, h, t in embed_inputs if not cache.has(h)
        ]
        if len(misses) > _INLINE_EMBED_CAP:
            _log.info(
                "retrieval._maybe_vector_top_k: %d/%d cache misses exceeds cap %d "
                "— BM25-only this call (call warm_kb_items to fill cache)",
                len(misses),
                len(docs),
                _INLINE_EMBED_CAP,
            )
            return None

        # Embed query first; if that fails, fall back early before
        # paying the cost of doc-side embedding.
        query_text = query.strip()
        try:
            query_vectors = await embed_with_cache(
                [query_text], cache, self._embedding_client
            )
        except Exception:
            _log.exception(
                "retrieval._maybe_vector_top_k: query embed failed — BM25-only"
            )
            return None
        if not query_vectors or not query_vectors[0]:
            return None
        query_vector = query_vectors[0]

        # Embed any missing doc texts inline. embed_with_cache returns
        # vectors in input order — but the cache also serves cached
        # ones, so the result is the full doc-vector sequence parallel
        # to embed_inputs.
        try:
            doc_vectors = await embed_with_cache(
                [t for _d, _h, t in embed_inputs],
                cache,
                self._embedding_client,
            )
        except Exception:
            _log.exception(
                "retrieval._maybe_vector_top_k: doc embed failed — BM25-only"
            )
            return None

        vec_retriever = VectorRetriever(
            [d for d, _h, _t in embed_inputs], doc_vectors
        )
        return vec_retriever.top_k(query_vector, k=k)

    async def warm_kb_items(self, *, project_id: str) -> int:
        """Eagerly embed every group-scope kb item in `project_id`.

        Use case: post-deploy warmer / cron / startup hook. Avoids the
        BM25-only fallback path in retrieve_kb_items by ensuring the
        cache is full before queries arrive. Returns the number of
        new embeddings written (0 = already warm).

        No-op when no embedding client is wired.
        """
        if self._embedding_client is None:
            return 0

        async with session_scope(self._sessionmaker) as session:
            rows = await KbItemRepository(session).list_group_for_project(
                project_id=project_id, limit=_REPO_LIST_LIMIT
            )
        live_rows = [
            r for r in rows
            if r.status not in ("archived", "draft", "rejected")
        ]
        if not live_rows:
            return 0

        cache = self._get_cache()
        size_before = cache.size
        docs = [_kb_row_to_doc(r) for r in live_rows]
        texts = [_embedding_text(d) for d in docs]
        try:
            await embed_with_cache(texts, cache, self._embedding_client)
        except Exception:
            _log.exception(
                "retrieval.warm_kb_items: embed failed for project %s",
                project_id,
            )
            return 0
        return cache.size - size_before


def _embedding_text(doc: RetrievalDoc) -> str:
    """Concat title + content for embedding (title weighted ×2).

    Same intuition as BM25's title weight: title is a stronger
    semantic signal than buried body. Less aggressive than BM25's
    ×3 because vector models don't double-count the same way TF
    does. Matches the eval's `_embedding_text` helper verbatim so
    cache contents are interchangeable across eval and prod runs.
    """
    title = (doc.title or "").strip()
    body = (doc.content or "").strip()
    if title and body:
        return f"{title}\n{title}\n{body}"
    return title or body


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
