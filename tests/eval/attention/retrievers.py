"""§7.2 hybrid retrieval primitives — slices 1-3.

The §7 stack composes five retrievers via RRF (`new_concepts.md §7.2`):

  * **BM25 / lexical** — exact-match strength: task ids, member names,
    technical terms, decision ids, API names. Slice 1.
  * **Vector similarity** — semantic neighbors via Qwen3-Embedding-8B
    (multilingual). Slice 2.
  * Graph-neighbor expansion — relationship-driven candidates. Slice 3.
  * Recent active nodes — last-N-day touch boost. Slice 3.
  * User-pinned — explicit anchors. Slice 3.

Each retriever returns `[(item, score)]` ranked descending by score.
RRF (slice 4) merges rank lists without needing the scales to align,
so we don't try to calibrate raw scores across retrievers — just the
within-retriever ordering matters.

BM25 is dep-free Python; the vector retriever calls SiliconFlow via
the openai SDK (already a dep) and caches embeddings to disk so the
eval scaffold keeps fast iteration. A production wiring (slice 5)
can swap to a tuned C-backed BM25 + a real vector DB; the rank-list
interface stays stable.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

from .types import CorpusItem


# ---------------------------------------------------------------------------
# Tokenization (bilingual zh + en).
# ---------------------------------------------------------------------------

# Light stop-word set — the most common EN function words plus the
# four highest-frequency CJK function characters that swamp BM25 IDF
# without carrying meaning. This is a pragmatic minimum, not a full
# lexicon: BM25's IDF naturally down-weights everything else common,
# so we only filter what would otherwise dominate token counts on
# short documents.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "about",
        "which",
        "what",
        "why",
        "who",
        "how",
        "when",
        "where",
        "should",
        "could",
        "would",
        "are",
        "was",
        "has",
        "have",
        "but",
        "not",
        "其中",
        "我们",
        "你们",
        "他们",
        "请",
        "的",
        "了",
        "是",
        "在",
    }
)


# Punctuation + structural marks (en + zh) that should split tokens
# but not appear as tokens themselves.
_PUNCT_SPLIT_RE = re.compile(
    r"[\s。、,，.!?？！()()【】「」\[\]<>&|\\/:：;；\"'`#@~*\-+=]+"
)


def _is_cjk(ch: str) -> bool:
    """True for CJK unified ideographs (zh hanzi range).

    Covers the bulk of Chinese text. Doesn't try to handle Japanese
    kana / hangul — the corpus is zh+en, not the full CJK family.
    """
    return "一" <= ch <= "鿿"


def tokenize(text: str) -> list[str]:
    """Bilingual tokenizer for BM25.

    Strategy:
      * Split on punctuation + whitespace into runs.
      * For each run: emit lowercase ASCII chunks of length ≥ 2 as
        single tokens (covers en words, technical terms, numeric ids
        like `D#42`, snake_case names like `signal_chain`).
      * For each CJK char in the run, emit it as a unigram token.
        Char-unigram is the simplest tokenizer that gives reasonable
        BM25 recall on Chinese text without a heavyweight segmenter
        like jieba. The tradeoff vs bigrams: more recall, lower
        precision — RRF fusion downstream pulls precision back up
        from the other retrievers.
      * Drop stop-words and 1-char ASCII (CJK 1-char tokens stay).

    Returns the token list in document order (not deduplicated — BM25
    uses raw term frequency).
    """
    if not text:
        return []
    out: list[str] = []
    for run in _PUNCT_SPLIT_RE.split(text):
        if not run:
            continue
        # Walk the run splitting at CJK ↔ non-CJK transitions so
        # ASCII chunks stay together while CJK chars emit individually.
        buf: list[str] = []
        for ch in run:
            if _is_cjk(ch):
                if buf:
                    word = "".join(buf).lower()
                    if len(word) >= 2 and word not in _STOP_WORDS:
                        out.append(word)
                    buf = []
                if ch not in _STOP_WORDS:
                    out.append(ch)
            else:
                buf.append(ch)
        if buf:
            word = "".join(buf).lower()
            if len(word) >= 2 and word not in _STOP_WORDS:
                out.append(word)
    return out


# ---------------------------------------------------------------------------
# BM25 (Okapi).
# ---------------------------------------------------------------------------


class BM25Retriever:
    """Pure-Python BM25 over a CorpusItem sequence.

    Per `new_concepts.md §7.2`, lexical retrieval is one of five layers
    that compose into the final hybrid candidate set. BM25 specifically
    earns its place by being strongest on the things vector search is
    weakest on — exact ids, technical terms, member names.

    Standard Okapi BM25 with a small twist: title text contributes
    `_TITLE_WEIGHT` repetitions to the document so a query that exactly
    matches a node's title ranks above a node that mentions the term in
    body but isn't titled with it. Validated as a "free" precision
    booster on every BM25 corpus people study.

    Construction is one pass over the corpus to build the inverted
    index + per-doc length table; subsequent `top_k` calls reuse the
    index. Cost: O(N × avg_tokens) once; O(|query_tokens| × avg_postings)
    per query.
    """

    # k1 controls term-frequency saturation (higher = more weight to
    # repeated terms). b controls length normalization (1 = full, 0 =
    # none). Defaults are the canonical BM25 numbers; tuning is a
    # separate concern once we have multi-retriever evals to compare.
    _K1 = 1.5
    _B = 0.75
    # Title repetition factor — see class docstring.
    _TITLE_WEIGHT = 3

    def __init__(self, corpus: Sequence[CorpusItem]) -> None:
        self._items: tuple[CorpusItem, ...] = tuple(corpus)
        self._doc_tokens: list[list[str]] = [
            self._tokens_for(item) for item in self._items
        ]
        self._doc_lengths: list[int] = [len(d) for d in self._doc_tokens]
        n_docs = len(self._items)
        self._avgdl: float = (
            sum(self._doc_lengths) / n_docs if n_docs else 0.0
        )
        # Term → list[(doc_idx, term_freq)]. Kept sorted by doc_idx so
        # the per-query loop is cache-friendly even for the longer
        # postings (function characters that survived stop-word
        # filtering, common product nouns, etc.).
        self._postings: dict[str, list[tuple[int, int]]] = {}
        for doc_idx, tokens in enumerate(self._doc_tokens):
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            for tok, freq in tf.items():
                self._postings.setdefault(tok, []).append((doc_idx, freq))
        # IDF per term cached at construction time so per-query work
        # is just postings traversal + arithmetic.
        self._idf: dict[str, float] = {}
        for term, posts in self._postings.items():
            df = len(posts)
            # +1 in the denominator avoids div-by-zero and matches the
            # +1 in the canonical BM25+ smoothing for IDF.
            self._idf[term] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

    @classmethod
    def _tokens_for(cls, item: CorpusItem) -> list[str]:
        """Tokenize one CorpusItem with title weighting applied."""
        title_tokens = tokenize(item.title)
        body_tokens = tokenize(item.content)
        return title_tokens * cls._TITLE_WEIGHT + body_tokens

    def top_k(
        self,
        query_text: str,
        *,
        k: int = 50,
        candidate_filter: "Iterable[bool] | None" = None,
    ) -> list[tuple[CorpusItem, float]]:
        """Return the top-k items by BM25 score for `query_text`.

        `candidate_filter` is an optional boolean iterable parallel to
        the corpus — True = candidate, False = skip. Lets the caller
        scope to viewer-visible items without forcing this retriever
        to know about scope tiers (separation of concerns: retrieval
        ranks; the membrane gate decides who can see what).

        Items with score 0 are dropped — no point handing the LLM a
        zero-evidence candidate and burning tokens on it.
        """
        query_tokens = tokenize(query_text)
        if not query_tokens or not self._items:
            return []

        keep_mask: list[bool] | None = (
            list(candidate_filter) if candidate_filter is not None else None
        )

        scores: dict[int, float] = {}
        seen_query_terms: set[str] = set()
        for term in query_tokens:
            if term in seen_query_terms:
                # Repeated query terms add no extra info under standard
                # BM25 (the formula is per unique term × per-doc tf).
                continue
            seen_query_terms.add(term)
            posts = self._postings.get(term)
            if not posts:
                continue
            idf = self._idf[term]
            for doc_idx, tf in posts:
                if keep_mask is not None and not keep_mask[doc_idx]:
                    continue
                doc_len = self._doc_lengths[doc_idx]
                denom = tf + self._K1 * (
                    1.0 - self._B + self._B * (doc_len / self._avgdl if self._avgdl else 1.0)
                )
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (
                    tf * (self._K1 + 1.0) / denom
                )

        ranked = sorted(scores.items(), key=lambda p: p[1], reverse=True)
        return [(self._items[i], s) for i, s in ranked[:k]]


# ---------------------------------------------------------------------------
# Vector retrieval (Qwen3-Embedding-8B via SiliconFlow).
# ---------------------------------------------------------------------------


class VectorRetriever:
    """Cosine-similarity retrieval over precomputed embeddings.

    Construction takes the corpus + a parallel list of embedding
    vectors (one per item, same length). The embedding step is
    factored out into `tests/eval/attention/embeddings.py` so the
    cache can be reused across slices and the retriever stays
    sync — no asyncio.run inside per-query scoring.

    Per `new_concepts.md §7.2`, vector retrieval covers exactly what
    BM25 misses: semantic neighbors that don't share surface tokens.
    The two retrievers compose via RRF in slice 4.
    """

    def __init__(
        self,
        corpus: Sequence[CorpusItem],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(corpus) != len(embeddings):
            raise ValueError(
                f"corpus/embeddings length mismatch: "
                f"{len(corpus)} vs {len(embeddings)}"
            )
        self._items: tuple[CorpusItem, ...] = tuple(corpus)
        # Pre-normalize so per-query scoring is one dot product per
        # candidate instead of a divide. Matters more in production
        # than at eval scale, but it costs nothing here.
        self._unit_vectors: list[tuple[float, ...]] = [
            _l2_normalize(v) for v in embeddings
        ]

    def top_k(
        self,
        query_embedding: Sequence[float],
        *,
        k: int = 50,
        candidate_filter: "Iterable[bool] | None" = None,
    ) -> list[tuple[CorpusItem, float]]:
        """Return top-k items by cosine similarity to `query_embedding`.

        `candidate_filter` mirrors BM25Retriever — boolean iterable
        parallel to the corpus, True = candidate.
        """
        if not self._items:
            return []
        q = _l2_normalize(query_embedding)
        if not q:
            return []
        keep_mask: list[bool] | None = (
            list(candidate_filter) if candidate_filter is not None else None
        )
        scores: list[tuple[int, float]] = []
        for idx, doc_vec in enumerate(self._unit_vectors):
            if keep_mask is not None and not keep_mask[idx]:
                continue
            # Dot product on unit vectors == cosine similarity.
            score = sum(a * b for a, b in zip(q, doc_vec))
            scores.append((idx, score))
        scores.sort(key=lambda p: p[1], reverse=True)
        return [(self._items[i], s) for i, s in scores[:k]]


def _l2_normalize(vec: Sequence[float]) -> tuple[float, ...]:
    """Return `vec / ||vec||`. Returns empty on zero-norm input."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return ()
    return tuple(x / norm for x in vec)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for two raw (un-normalized) vectors.

    Convenience for tests / one-off comparisons. Production-style
    bulk scoring goes through VectorRetriever which pre-normalizes.
    """
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


# ---------------------------------------------------------------------------
# Graph-neighbor expansion (slice 3).
# ---------------------------------------------------------------------------

# Match `@kb_some_id` or `@u_some_id` in body text — the lightweight
# explicit-reference convention the realistic corpus uses. Trailing
# `\w*` (not `+`) so single-letter ids like `@a` still match — they
# don't appear in the realistic corpus but they do in unit tests, and
# the regex shouldn't disagree with itself across scales.
_AT_MENTION_RE = re.compile(r"@([a-zA-Z]\w*)")


class GraphNeighborRetriever:
    """Edge-aware expansion from a seed set.

    Per `new_concepts.md §7.2`, graph-neighbor catches what neither BM25
    nor vector finds: items downstream of a known-relevant seed via
    explicit references, supersede chains, or strong tag overlap. The
    classic example: a query matches one decision lexically, and the
    *implementing tasks* (linked only via the decision's id, not via
    shared text) come back as neighbors.

    Edge sources extracted from each item:
      * `@kb_xxx` / `@u_xxx` mentions in body text (regex)
      * `metadata.supersedes` — list of older ids this item replaces
      * `metadata.tags` — Jaccard overlap with the seed's tag set,
        weighted lower because tag overlap is a fuzzier signal than
        an explicit reference

    Edge weights:
      * explicit @-mention: 1.0
      * supersede edge:     0.8
      * tag-Jaccard:        up to 0.5 (Jaccard × 0.5)

    The retriever sums edge weights across all incoming seed-edges to
    a candidate, then ranks. Seeds themselves are excluded from the
    output (they're already ranked by the upstream retriever that
    produced them).
    """

    _W_MENTION = 1.0
    _W_SUPERSEDE = 0.8
    _W_TAG_JACCARD = 0.5

    def __init__(self, corpus: Sequence[CorpusItem]) -> None:
        self._items: tuple[CorpusItem, ...] = tuple(corpus)
        self._by_id: dict[str, CorpusItem] = {it.id: it for it in self._items}
        # Pre-extract per-item: mentioned ids, supersedes ids, tag set.
        self._mentions: dict[str, set[str]] = {}
        self._supersedes: dict[str, set[str]] = {}
        self._tags: dict[str, frozenset[str]] = {}
        for it in self._items:
            mentioned = {
                f"@{m}" for m in _AT_MENTION_RE.findall(it.content or "")
            }
            # Resolve `@kb_foo` / `@u_foo` to bare id `kb_foo` / `u_foo`.
            self._mentions[it.id] = {
                ref[1:] for ref in mentioned if ref[1:] in self._by_id
            }
            meta = it.metadata or {}
            sup = meta.get("supersedes")
            self._supersedes[it.id] = (
                {s for s in sup if s in self._by_id}
                if isinstance(sup, list)
                else set()
            )
            tags = meta.get("tags") or []
            self._tags[it.id] = frozenset(
                str(t).lower() for t in tags if isinstance(t, str)
            )

    def top_k(
        self,
        seed_ids: Iterable[str],
        *,
        k: int = 30,
        candidate_filter: "Iterable[bool] | None" = None,
    ) -> list[tuple[CorpusItem, float]]:
        """Return top-k neighbors of `seed_ids` ranked by summed edge weight.

        Empty seed set → empty result (graph-neighbor needs an anchor).
        """
        seeds = {s for s in seed_ids if s in self._by_id}
        if not seeds or not self._items:
            return []
        keep_mask: list[bool] | None = (
            list(candidate_filter) if candidate_filter is not None else None
        )
        idx_by_id = {it.id: idx for idx, it in enumerate(self._items)}

        scores: dict[str, float] = {}

        # Outgoing mentions / supersedes from each seed → those targets
        # are neighbors. Plus incoming: items that mention or supersede
        # this seed. Both directions count — graph-neighbor is undirected
        # for the retrieval pass (production may distinguish). Targets
        # that are themselves seeds are excluded — the upstream retriever
        # has already ranked them.
        for seed_id in seeds:
            for tgt in self._mentions.get(seed_id, set()):
                if tgt in seeds:
                    continue
                scores[tgt] = scores.get(tgt, 0.0) + self._W_MENTION
            for tgt in self._supersedes.get(seed_id, set()):
                if tgt in seeds:
                    continue
                scores[tgt] = scores.get(tgt, 0.0) + self._W_SUPERSEDE

        for src_id in self._by_id:
            if src_id in seeds:
                continue
            outgoing = self._mentions.get(src_id, set()) | self._supersedes.get(
                src_id, set()
            )
            inbound_seed_hits = outgoing & seeds
            if inbound_seed_hits:
                # Reverse mention edge counts the same as forward — we're
                # surfacing items that reference one of our seeds.
                scores[src_id] = scores.get(src_id, 0.0) + self._W_MENTION * len(
                    inbound_seed_hits
                )

        # Tag-Jaccard expansion: union of all seed tag sets is the
        # query "topic"; score each non-seed item by Jaccard similarity
        # to it. Cheaper than per-seed pairwise (and more honest about
        # "which topic cluster is the query in").
        seed_tag_union: frozenset[str] = frozenset()
        for seed_id in seeds:
            seed_tag_union = seed_tag_union | self._tags.get(seed_id, frozenset())
        if seed_tag_union:
            for it in self._items:
                if it.id in seeds:
                    continue
                cand_tags = self._tags.get(it.id, frozenset())
                if not cand_tags:
                    continue
                inter = len(seed_tag_union & cand_tags)
                if inter == 0:
                    continue
                union = len(seed_tag_union | cand_tags)
                jaccard = inter / union
                scores[it.id] = (
                    scores.get(it.id, 0.0) + self._W_TAG_JACCARD * jaccard
                )

        # Apply visibility mask + sort by score desc.
        ranked: list[tuple[str, float]] = []
        for cand_id, score in scores.items():
            if score <= 0.0:
                continue
            if keep_mask is not None:
                idx = idx_by_id.get(cand_id)
                if idx is None or not keep_mask[idx]:
                    continue
            ranked.append((cand_id, score))
        ranked.sort(key=lambda p: p[1], reverse=True)
        return [(self._by_id[cid], s) for cid, s in ranked[:k]]


# ---------------------------------------------------------------------------
# Recency retriever (slice 3).
# ---------------------------------------------------------------------------


def _parse_ts(raw: Any) -> datetime | None:
    """Best-effort ISO-8601 parser. Returns None on anything unparseable."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    try:
        # fromisoformat handles "2026-04-26T19:40:00+00:00" but not
        # the trailing "Z" alone — normalize before parsing.
        s = raw.rstrip("Z") + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class RecencyRetriever:
    """Top-k items by recency. Constant per-query: it's a sorted slice.

    Per §7.2, recency is the "what's hot right now" axis — surfaces
    nodes the team has touched in the last few days even if no other
    retriever ranks them. The frecency primitives shipped in 387aef6
    (`last_accessed_at` + `access_count`) will replace pure recency
    with `log(1 + access_count) × time_decay` once §7.4 wires up
    (slice 5 in production); the eval scaffold stands in with raw
    `metadata.ts` since access counts are 0 across a synthetic corpus.
    """

    def __init__(self, corpus: Sequence[CorpusItem]) -> None:
        self._items: tuple[CorpusItem, ...] = tuple(corpus)
        # Pre-sort once by ts descending. Items with no parseable ts
        # fall to the end with a sentinel datetime.min.
        sentinel = datetime(1970, 1, 1, tzinfo=timezone.utc)
        with_ts = [
            (idx, _parse_ts((it.metadata or {}).get("ts")) or sentinel)
            for idx, it in enumerate(self._items)
        ]
        with_ts.sort(key=lambda pair: pair[1], reverse=True)
        self._sorted_indices: list[int] = [idx for idx, _ in with_ts]
        self._ts_by_idx: dict[int, datetime] = {idx: ts for idx, ts in with_ts}

    def top_k(
        self,
        *,
        k: int = 20,
        candidate_filter: "Iterable[bool] | None" = None,
    ) -> list[tuple[CorpusItem, float]]:
        """Return top-k visible items by recency.

        Score is the unix epoch seconds of the timestamp — only the
        ordering matters for RRF, but a numeric score keeps the
        rank-list interface uniform with BM25 / vector / graph.
        """
        keep_mask: list[bool] | None = (
            list(candidate_filter) if candidate_filter is not None else None
        )
        out: list[tuple[CorpusItem, float]] = []
        for idx in self._sorted_indices:
            if keep_mask is not None and not keep_mask[idx]:
                continue
            ts = self._ts_by_idx[idx]
            out.append((self._items[idx], ts.timestamp()))
            if len(out) >= k:
                break
        return out


# ---------------------------------------------------------------------------
# Pinned retriever (slice 3).
# ---------------------------------------------------------------------------


class PinnedRetriever:
    """Returns explicitly-pinned items in pin order.

    Per §7.2, user-pinned nodes are the "always include" anchor — the
    user has told the system "this thing matters, no matter what the
    score-fusion says." In production this comes from a pin table; in
    the eval it's whatever the caller passes via `top_k(pinned_ids)`.

    Score is a descending integer so the RRF rank is stable across
    however many pins were supplied (rank 1 = first pin).
    """

    def __init__(self, corpus: Sequence[CorpusItem]) -> None:
        self._items: tuple[CorpusItem, ...] = tuple(corpus)
        self._by_id: dict[str, CorpusItem] = {it.id: it for it in self._items}
        self._idx_by_id: dict[str, int] = {
            it.id: idx for idx, it in enumerate(self._items)
        }

    def top_k(
        self,
        pinned_ids: Iterable[str],
        *,
        k: int = 10,
        candidate_filter: "Iterable[bool] | None" = None,
    ) -> list[tuple[CorpusItem, float]]:
        keep_mask: list[bool] | None = (
            list(candidate_filter) if candidate_filter is not None else None
        )
        out: list[tuple[CorpusItem, float]] = []
        seen: set[str] = set()
        for rank, pid in enumerate(pinned_ids):
            if pid in seen:
                continue
            seen.add(pid)
            item = self._by_id.get(pid)
            if item is None:
                continue
            if keep_mask is not None:
                idx = self._idx_by_id[pid]
                if not keep_mask[idx]:
                    continue
            # Higher score for earlier pins so the rank-list is sorted.
            out.append((item, float(len(self._items) - rank)))
            if len(out) >= k:
                break
        return out


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (slice 4).
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    rank_lists: Sequence[Sequence[tuple[CorpusItem, float]]],
    *,
    k: int = 50,
    rrf_k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[CorpusItem, float]]:
    """Merge ranked candidate lists via Reciprocal Rank Fusion.

    RRF (`new_concepts.md §7.2`) merges rank-only signals from
    heterogeneous retrievers without needing the raw scores to share
    a scale. Score for each item is `Σ_i weight_i × 1 / (rrf_k + rank_i)`
    where rank is 1-indexed within each list and absent items
    contribute 0 from that retriever.

    `rrf_k=60` is the standard Cormack/Clarke default — keeps lower
    ranks contributing meaningfully so a top-50 list isn't
    dominated by the top-3 of any one retriever.

    `weights` lets the caller emphasize one retriever (e.g. pinned 2.0
    so an explicit anchor outranks any organic match). Defaults to
    1.0 for every input list.

    Items returned in fused-score-descending order, capped at `k`.
    Identity is by `item.id` so two retrievers reporting the same
    item dedupe naturally.
    """
    if not rank_lists:
        return []
    weight_vec: list[float] = (
        [1.0] * len(rank_lists)
        if weights is None
        else [float(w) for w in weights]
    )
    if len(weight_vec) != len(rank_lists):
        raise ValueError(
            f"weights length {len(weight_vec)} != rank_lists length {len(rank_lists)}"
        )

    scores: dict[str, float] = {}
    item_by_id: dict[str, CorpusItem] = {}
    for rank_list, weight in zip(rank_lists, weight_vec):
        for rank, (item, _raw_score) in enumerate(rank_list, start=1):
            item_by_id[item.id] = item
            scores[item.id] = scores.get(item.id, 0.0) + weight * (
                1.0 / (rrf_k + rank)
            )

    ranked = sorted(scores.items(), key=lambda p: p[1], reverse=True)
    return [(item_by_id[cid], s) for cid, s in ranked[:k]]


__all__ = [
    "BM25Retriever",
    "GraphNeighborRetriever",
    "PinnedRetriever",
    "RecencyRetriever",
    "VectorRetriever",
    "cosine_similarity",
    "reciprocal_rank_fusion",
    "tokenize",
]
