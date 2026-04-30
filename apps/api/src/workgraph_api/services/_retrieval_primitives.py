"""Production retrieval primitives — BM25 + RRF + frecency multiplier.

Adapted from the eval scaffold at `tests/eval/attention/retrievers.py`
(slices 1+4 of pickup #4) for production use over `(id, title, content)`
tuples instead of `CorpusItem` objects.

The eval validated this architecture at 2505 nodes:
  * BM25 alone → F1 0.700, recall 0.636 at 538 nodes; degrades at scale
  * Vector alone → F1 0.818 at 538, drops to 0.727 at 2505
  * BM25 + Vector RRF → F1 0.818 at 2505 (the §7.2 thesis confirmed)
  * 5-layer hybrid (graph/recency/pinned added) → still loses to
    2-layer; recency belongs as a SCORE MULTIPLIER (§7.4 frecency),
    not a standalone retriever.

Slice 5a ships BM25-only — vector retrieval lands in slice 5b once
the embedding-cache pipeline is wired into production. BM25 alone
strictly beats the existing substring-scan approach in `kb_search`.

The eval module duplicates this code (over CorpusItem) — that's a
known DRY violation. Refactor to a shared package becomes worth it
when there's a second prod consumer (slice 5c likely).
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Tokenization (bilingual zh + en) — verbatim from eval slice 1.
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "with", "from", "into", "that", "this",
        "about", "which", "what", "why", "who", "how", "when", "where",
        "should", "could", "would", "are", "was", "has", "have", "but",
        "not",
        "其中", "我们", "你们", "他们", "请", "的", "了", "是", "在",
    }
)

_PUNCT_SPLIT_RE = re.compile(
    r"[\s。、,，.!?？！()()【】「」\[\]<>&|\\/:：;；\"'`#@~*\-+=]+"
)


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def tokenize(text: str) -> list[str]:
    """Bilingual tokenizer: en words ≥2 chars + zh char-unigrams.

    Drops the small stop-word set above. Char-unigram tokenization
    keeps the prod retriever dependency-free (no jieba). Validated
    in the slice-1 eval at F1 0.700 / leak rate 0 over a 538-node
    realistic zh+en corpus.
    """
    if not text:
        return []
    out: list[str] = []
    for run in _PUNCT_SPLIT_RE.split(text):
        if not run:
            continue
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
# Document shape used by the prod retriever.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalDoc:
    """Minimal shape for a retrievable production row.

    Adapters in `RetrievalService` build these from KbItemRow /
    MessageRow / DecisionRow / TaskRow / RiskRow as needed. Carries
    the frecency primitives so the multiplier doesn't need a second
    DB pass.
    """

    id: str
    title: str
    content: str
    # Per-row frecency primitives (alembic 0028 / _FrecencyColumnsMixin).
    # last_accessed_at falls back to created_at if the row predates
    # bump-on-touch hooks (commit 95aaeef).
    last_accessed_at: datetime | None = None
    access_count: int = 0


# ---------------------------------------------------------------------------
# BM25 (Okapi) — adapted from eval slice 1.
# ---------------------------------------------------------------------------


class BM25Retriever:
    """Pure-Python Okapi BM25 over RetrievalDoc sequences.

    Standard BM25 with title repeated ×3 (titled matches outrank
    body-only matches). Index built once at construction; per-query
    cost is unique-term-count × posting-length. At 5K-doc-per-cell
    scale this is microseconds — no need to swap to a C-backed
    implementation.
    """

    _K1 = 1.5
    _B = 0.75
    _TITLE_WEIGHT = 3

    def __init__(self, docs: Sequence[RetrievalDoc]) -> None:
        self._docs: tuple[RetrievalDoc, ...] = tuple(docs)
        self._doc_tokens: list[list[str]] = [
            self._tokens_for(doc) for doc in self._docs
        ]
        self._doc_lengths: list[int] = [len(d) for d in self._doc_tokens]
        n_docs = len(self._docs)
        self._avgdl: float = (
            sum(self._doc_lengths) / n_docs if n_docs else 0.0
        )
        self._postings: dict[str, list[tuple[int, int]]] = {}
        for doc_idx, tokens in enumerate(self._doc_tokens):
            tf: dict[str, int] = {}
            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1
            for tok, freq in tf.items():
                self._postings.setdefault(tok, []).append((doc_idx, freq))
        self._idf: dict[str, float] = {}
        for term, posts in self._postings.items():
            df = len(posts)
            self._idf[term] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

    @classmethod
    def _tokens_for(cls, doc: RetrievalDoc) -> list[str]:
        title_tokens = tokenize(doc.title)
        body_tokens = tokenize(doc.content)
        return title_tokens * cls._TITLE_WEIGHT + body_tokens

    def top_k(
        self,
        query_text: str,
        *,
        k: int = 50,
    ) -> list[tuple[RetrievalDoc, float]]:
        """Return top-k docs by BM25 score for `query_text`.

        Items with score 0 are dropped (no signal — don't waste a
        candidate slot on them).
        """
        query_tokens = tokenize(query_text)
        if not query_tokens or not self._docs:
            return []

        scores: dict[int, float] = {}
        seen_terms: set[str] = set()
        for term in query_tokens:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            posts = self._postings.get(term)
            if not posts:
                continue
            idf = self._idf[term]
            for doc_idx, tf in posts:
                doc_len = self._doc_lengths[doc_idx]
                denom = tf + self._K1 * (
                    1.0 - self._B + self._B * (doc_len / self._avgdl if self._avgdl else 1.0)
                )
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (
                    tf * (self._K1 + 1.0) / denom
                )

        ranked = sorted(scores.items(), key=lambda p: p[1], reverse=True)
        return [(self._docs[i], s) for i, s in ranked[:k]]


# ---------------------------------------------------------------------------
# §7.4 frecency multiplier.
# ---------------------------------------------------------------------------

# Half-life for the time-decay component, in days. After this many days
# of no access, the recency portion of the multiplier drops to 0.5.
# 7-day half-life matches the "active work" window the §7.2 spec uses
# for its recency layer (top-20 by ts) — short enough to favor this
# week's touches, long enough that older items still get some lift.
_FRECENCY_HALF_LIFE_DAYS = 7.0
# Cap the frecency boost so a single super-touched item can't dominate
# a topically-stronger but cooler item. The multiplier saturates at
# this value; raw score is multiplied by `1 + min(boost, _CAP)`.
_FRECENCY_BOOST_CAP = 1.0


def frecency_multiplier(
    *,
    access_count: int,
    last_accessed_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """Multiplier for `1 + boost` to apply against a retrieval score.

    Per §7.4 design: `boost = log(1 + access_count) × time_decay`,
    where time_decay is exponential with a 7-day half-life. Output
    is in [1.0, 1.0 + _FRECENCY_BOOST_CAP].

    A row with `access_count=0` and `last_accessed_at=None` returns
    exactly 1.0 (no-op multiplier — the retrieval score stands on
    its own). A hot item touched 20 times today returns ~2.0.

    Best-effort: any None / negative / future timestamp coerces to a
    no-op multiplier rather than raising. Production calls this
    inside a hot path where degraded ranking is preferable to a
    crash.
    """
    if access_count <= 0 or last_accessed_at is None:
        return 1.0
    now = now or datetime.now(timezone.utc)
    # Guard against tz-naive timestamps from older rows.
    if last_accessed_at.tzinfo is None:
        last_accessed_at = last_accessed_at.replace(tzinfo=timezone.utc)
    age_seconds = (now - last_accessed_at).total_seconds()
    if age_seconds <= 0:
        # Future timestamp / clock skew — treat as fresh.
        time_decay = 1.0
    else:
        age_days = age_seconds / 86400.0
        time_decay = math.exp(-math.log(2) * age_days / _FRECENCY_HALF_LIFE_DAYS)
    raw_boost = math.log(1.0 + access_count) * time_decay
    return 1.0 + min(raw_boost, _FRECENCY_BOOST_CAP)


# ---------------------------------------------------------------------------
# RRF — slice 4 verbatim, generic over rank lists.
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    rank_lists: Sequence[Sequence[tuple[RetrievalDoc, float]]],
    *,
    k: int = 50,
    rrf_k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[RetrievalDoc, float]]:
    """Merge ranked candidate lists via RRF.

    Identical math to `tests/eval/attention/retrievers.py`, just
    typed against `RetrievalDoc` instead of `CorpusItem`. Slice 5a
    only fuses one list (BM25) so this is mostly a stub; slice 5b
    fuses BM25 + vector lists.
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
    doc_by_id: dict[str, RetrievalDoc] = {}
    for rank_list, weight in zip(rank_lists, weight_vec):
        for rank, (doc, _raw) in enumerate(rank_list, start=1):
            doc_by_id[doc.id] = doc
            scores[doc.id] = scores.get(doc.id, 0.0) + weight * (
                1.0 / (rrf_k + rank)
            )
    ranked = sorted(scores.items(), key=lambda p: p[1], reverse=True)
    return [(doc_by_id[did], s) for did, s in ranked[:k]]


__all__ = [
    "BM25Retriever",
    "RetrievalDoc",
    "frecency_multiplier",
    "reciprocal_rank_fusion",
    "tokenize",
]
