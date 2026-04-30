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


__all__ = ["BM25Retriever", "VectorRetriever", "cosine_similarity", "tokenize"]
