"""Unit tests for the BM25 retriever (slice 1 of §7.2 hybrid stack).

Pure-Python, no LLM calls — these run in the default unit-test sweep,
unlike the `@pytest.mark.eval` harness tests which exercise live
DeepSeek paths.

Coverage:
  * tokenize: en + zh + technical-id + stop-word filtering
  * BM25Retriever: ranks lexical-match items above noise; respects
    title-weighting; honors the candidate_filter mask; handles empty
    inputs without raising.
"""
from __future__ import annotations

import pytest

from tests.eval.attention.retrievers import (
    BM25Retriever,
    VectorRetriever,
    cosine_similarity,
    tokenize,
)
from tests.eval.attention.types import CorpusItem


def _item(
    id_: str,
    *,
    title: str = "",
    content: str = "",
    kind: str = "kb_item",
    scope: str = "group",
) -> CorpusItem:
    return CorpusItem(
        id=id_, kind=kind, scope=scope, title=title, content=content
    )


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


def test_tokenize_handles_en_words():
    toks = tokenize("Signal-chain crystallization decision review")
    assert "signal" in toks
    assert "chain" in toks
    assert "crystallization" in toks
    assert "decision" in toks
    assert "review" in toks


def test_tokenize_filters_stop_words():
    toks = tokenize("This is the answer for the question")
    # 'the' / 'this' / 'for' / 'is' should drop out.
    assert "the" not in toks
    assert "this" not in toks
    assert "for" not in toks
    assert "answer" in toks
    assert "question" in toks


def test_tokenize_emits_cjk_unigrams_and_filters_function_chars():
    toks = tokenize("我们的设计")
    # Function chars 我们的 should be filtered; meaning chars survive.
    assert "设" in toks
    assert "计" in toks
    assert "的" not in toks


def test_tokenize_keeps_technical_ids_intact():
    """`signal_chain`, `D#42`, snake_case names should survive as one token."""
    toks = tokenize("signal_chain v2 references D#42 in the kb")
    assert "signal_chain" in toks
    # `D#42` splits at `#` (a punct char) — `42` is numeric ASCII ≥ 2 chars.
    assert "42" in toks
    # the ASCII single-char "d" is dropped (length < 2 after filter).
    assert "d" not in toks


def test_tokenize_empty_input_returns_empty_list():
    assert tokenize("") == []
    assert tokenize(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BM25Retriever ranking
# ---------------------------------------------------------------------------


def test_bm25_ranks_exact_match_above_unrelated():
    items = [
        _item("a", title="Boss 1 design notes", content="rage-quit 40%"),
        _item("b", title="Inventory rework", content="merge stacks"),
        _item("c", title="Localization plan", content="zh translation"),
    ]
    bm25 = BM25Retriever(items)
    ranked = bm25.top_k("boss", k=5)
    assert ranked, "should retrieve at least one match"
    assert ranked[0][0].id == "a"


def test_bm25_title_weight_pulls_titled_match_above_body_only_match():
    """`_TITLE_WEIGHT=3` means a title-occurrence outranks a body-only one.

    Both items contain `signal_chain` exactly once at their respective
    locations; the title-bearer should win on the same query.
    """
    items = [
        _item(
            "title-hit",
            title="signal_chain crystallization",
            content="generic body text",
        ),
        _item(
            "body-hit",
            title="generic title",
            content="The signal_chain is referenced here",
        ),
    ]
    bm25 = BM25Retriever(items)
    ranked = bm25.top_k("signal_chain", k=5)
    assert [item.id for item, _ in ranked][0] == "title-hit"


def test_bm25_drops_zero_score_candidates():
    """Items with no token overlap return no row, even at k > corpus size."""
    items = [
        _item("a", title="alpha", content="bravo"),
        _item("b", title="charlie", content="delta"),
    ]
    bm25 = BM25Retriever(items)
    ranked = bm25.top_k("zzz_no_match", k=10)
    assert ranked == []


def test_bm25_candidate_filter_mask_skips_invisible_items():
    """The retriever doesn't know scope tiers; the caller hands a mask."""
    items = [
        _item("a", title="boss design", content=""),
        _item("b", title="boss strategy", content=""),
        _item("c", title="boss plan", content=""),
    ]
    bm25 = BM25Retriever(items)
    # Hide 'a' and 'c' — only 'b' should be visible to the rank.
    visible_mask = [False, True, False]
    ranked = bm25.top_k(
        "boss", k=5, candidate_filter=visible_mask
    )
    assert [item.id for item, _ in ranked] == ["b"]


def test_bm25_empty_corpus_returns_empty():
    bm25 = BM25Retriever([])
    assert bm25.top_k("anything", k=5) == []


def test_bm25_zh_query_recovers_zh_titled_item():
    """End-to-end zh path: char-unigram tokenizer + BM25 still ranks
    the topical zh item above unrelated zh items.
    """
    items = [
        _item(
            "z1",
            title="关于 signal-chain 的设计文档",
            content="刚重新看了下 signal-chain 的结晶化部分",
        ),
        _item("z2", title="周报：库存重构", content="合并堆栈的进展"),
        _item("z3", title="本地化计划", content="中文翻译批次"),
    ]
    bm25 = BM25Retriever(items)
    ranked = bm25.top_k("signal-chain 设计", k=3)
    assert ranked
    assert ranked[0][0].id == "z1"


def test_bm25_repeated_query_terms_count_once():
    """Per BM25 spec, scoring is over unique query terms × per-doc tf."""
    items = [
        _item("a", title="signal", content=""),
        _item("b", title="signal noise", content=""),
    ]
    bm25 = BM25Retriever(items)
    once = bm25.top_k("signal", k=5)
    twice = bm25.top_k("signal signal signal", k=5)
    # Same ranking, same scores — repeated query terms are deduped.
    assert [(i.id, round(s, 6)) for i, s in once] == [
        (i.id, round(s, 6)) for i, s in twice
    ]


# ---------------------------------------------------------------------------
# VectorRetriever — pure cosine over precomputed vectors (no API calls).
# ---------------------------------------------------------------------------


def test_vector_retriever_ranks_nearest_neighbor_first():
    """Higher cosine similarity → higher rank."""
    items = [
        _item("a"),  # near to query
        _item("b"),  # orthogonal
        _item("c"),  # opposite direction
    ]
    embeddings = [
        [1.0, 0.1, 0.0],
        [0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0],
    ]
    vec = VectorRetriever(items, embeddings)
    ranked = vec.top_k([1.0, 0.0, 0.0], k=3)
    assert [item.id for item, _ in ranked] == ["a", "b", "c"]


def test_vector_retriever_respects_candidate_filter():
    items = [_item("a"), _item("b"), _item("c")]
    embeddings = [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]]
    vec = VectorRetriever(items, embeddings)
    # Hide 'a' (the closest); expect 'b' to rank first.
    ranked = vec.top_k(
        [1.0, 0.0], k=3, candidate_filter=[False, True, True]
    )
    assert [item.id for item, _ in ranked] == ["b", "c"]


def test_vector_retriever_handles_zero_norm_query():
    """Zero-norm query vector returns no rows rather than dividing by zero."""
    items = [_item("a"), _item("b")]
    embeddings = [[1.0, 0.0], [0.0, 1.0]]
    vec = VectorRetriever(items, embeddings)
    assert vec.top_k([0.0, 0.0], k=5) == []


def test_vector_retriever_length_mismatch_raises():
    items = [_item("a"), _item("b")]
    with pytest.raises(ValueError):
        VectorRetriever(items, [[1.0]])


def test_vector_retriever_empty_corpus_returns_empty():
    vec = VectorRetriever([], [])
    assert vec.top_k([1.0, 0.0], k=5) == []


def test_cosine_similarity_basic():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    # Zero-norm input returns 0 rather than NaN.
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
