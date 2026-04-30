"""Unit tests for the §7.2 hybrid retrieval primitives (slices 1-3).

Pure-Python, no LLM / embedding API calls — these run in the default
unit-test sweep, unlike the `@pytest.mark.eval` harness tests which
exercise live DeepSeek paths.

Coverage:
  * tokenize: en + zh + technical-id + stop-word filtering
  * BM25Retriever (slice 1): lexical ranking, title weighting, mask,
    empty inputs.
  * VectorRetriever (slice 2): cosine ranking, mask, zero-norm,
    length-mismatch.
  * GraphNeighborRetriever (slice 3): @-mention edges, supersedes
    edges, tag-Jaccard expansion.
  * RecencyRetriever (slice 3): ts ordering, mask, missing-ts fallback.
  * PinnedRetriever (slice 3): pin-order preservation, dedupe,
    unknown-id skip.
"""
from __future__ import annotations

import pytest

from tests.eval.attention.retrievers import (
    BM25Retriever,
    GraphNeighborRetriever,
    PinnedRetriever,
    RecencyRetriever,
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
    metadata: dict | None = None,
) -> CorpusItem:
    return CorpusItem(
        id=id_,
        kind=kind,
        scope=scope,
        title=title,
        content=content,
        metadata=dict(metadata or {}),
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


# ---------------------------------------------------------------------------
# GraphNeighborRetriever — slice 3.
# ---------------------------------------------------------------------------


def test_graph_neighbor_finds_at_mention_target():
    """Item B mentions @kb_a in body → kb_a is a neighbor of any seed
    that includes B.
    """
    items = [
        _item("kb_a", title="canonical KB note"),
        _item(
            "kb_b",
            title="follow-up note",
            content="See @kb_a for the original spec.",
        ),
        _item("kb_c", title="unrelated"),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(["kb_b"], k=5)
    assert [item.id for item, _ in ranked] == ["kb_a"]


def test_graph_neighbor_finds_inbound_mentions():
    """Seed kb_a has no outbound edges, but kb_b mentions it — kb_b is
    surfaced as an inbound neighbor.
    """
    items = [
        _item("kb_a", title="seed note"),
        _item(
            "kb_b",
            title="referencing note",
            content="builds on @kb_a",
        ),
        _item("kb_c", title="unrelated"),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(["kb_a"], k=5)
    assert [item.id for item, _ in ranked] == ["kb_b"]


def test_graph_neighbor_supersedes_edge_pulls_old_version():
    items = [
        _item(
            "dec_new",
            title="updated decision",
            metadata={"supersedes": ["dec_old"]},
        ),
        _item("dec_old", title="superseded"),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(["dec_new"], k=5)
    # Following the supersedes edge from dec_new lands on dec_old.
    assert [item.id for item, _ in ranked] == ["dec_old"]


def test_graph_neighbor_tag_jaccard_links_topical_items():
    items = [
        _item(
            "a",
            title="Postgres pool sizing",
            metadata={"tags": ["infra", "postgres"]},
        ),
        _item(
            "b",
            title="Postgres replication",
            metadata={"tags": ["infra", "postgres", "replication"]},
        ),
        _item(
            "c",
            title="Localization plan",
            metadata={"tags": ["i18n", "frontend"]},
        ),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(["a"], k=5)
    # b shares 2/3 tags with a; c shares 0. Only b should surface.
    assert [item.id for item, _ in ranked] == ["b"]


def test_graph_neighbor_excludes_seeds_from_output():
    items = [
        _item("a", title="alpha"),
        _item("b", title="bravo", content="@a"),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(["a", "b"], k=5)
    # Neither a nor b should appear — both are seeds.
    assert [item.id for item, _ in ranked] == []


def test_graph_neighbor_empty_seeds_returns_empty():
    items = [_item("a"), _item("b", content="@a")]
    g = GraphNeighborRetriever(items)
    assert g.top_k([], k=5) == []


def test_graph_neighbor_respects_candidate_filter():
    items = [
        _item("a", title="seed"),
        _item("b", title="hidden neighbor", content="@a"),
        _item("c", title="visible neighbor", content="@a"),
    ]
    g = GraphNeighborRetriever(items)
    ranked = g.top_k(
        ["a"], k=5, candidate_filter=[True, False, True]
    )
    assert [item.id for item, _ in ranked] == ["c"]


# ---------------------------------------------------------------------------
# RecencyRetriever — slice 3.
# ---------------------------------------------------------------------------


def test_recency_orders_by_ts_descending():
    items = [
        _item("old", metadata={"ts": "2026-01-01T00:00:00+00:00"}),
        _item("mid", metadata={"ts": "2026-03-15T00:00:00+00:00"}),
        _item("new", metadata={"ts": "2026-04-20T00:00:00+00:00"}),
    ]
    r = RecencyRetriever(items)
    ranked = r.top_k(k=5)
    assert [item.id for item, _ in ranked] == ["new", "mid", "old"]


def test_recency_handles_zulu_z_suffix():
    """ISO `2026-04-20T19:40:00Z` should parse, not silently fall to sentinel."""
    items = [
        _item("z", metadata={"ts": "2026-04-20T19:40:00Z"}),
        _item("none", metadata={}),  # parses to sentinel epoch-zero
    ]
    r = RecencyRetriever(items)
    ranked = r.top_k(k=5)
    assert [item.id for item, _ in ranked] == ["z", "none"]


def test_recency_respects_candidate_filter():
    items = [
        _item("a", metadata={"ts": "2026-04-20T00:00:00+00:00"}),
        _item("b", metadata={"ts": "2026-04-19T00:00:00+00:00"}),
        _item("c", metadata={"ts": "2026-04-18T00:00:00+00:00"}),
    ]
    r = RecencyRetriever(items)
    # Hide the most recent (a). Should surface b then c.
    ranked = r.top_k(k=5, candidate_filter=[False, True, True])
    assert [item.id for item, _ in ranked] == ["b", "c"]


def test_recency_caps_at_k():
    items = [
        _item(
            f"i{n}", metadata={"ts": f"2026-04-{20 - n:02d}T00:00:00+00:00"}
        )
        for n in range(10)
    ]
    r = RecencyRetriever(items)
    ranked = r.top_k(k=3)
    assert len(ranked) == 3


# ---------------------------------------------------------------------------
# PinnedRetriever — slice 3.
# ---------------------------------------------------------------------------


def test_pinned_returns_items_in_pin_order():
    items = [_item("a"), _item("b"), _item("c")]
    p = PinnedRetriever(items)
    ranked = p.top_k(["c", "a"], k=5)
    assert [item.id for item, _ in ranked] == ["c", "a"]
    # Higher score for earlier pins.
    assert ranked[0][1] > ranked[1][1]


def test_pinned_dedupes_repeated_ids():
    items = [_item("a"), _item("b")]
    p = PinnedRetriever(items)
    ranked = p.top_k(["a", "a", "b"], k=5)
    assert [item.id for item, _ in ranked] == ["a", "b"]


def test_pinned_skips_unknown_ids_silently():
    items = [_item("a")]
    p = PinnedRetriever(items)
    ranked = p.top_k(["zzz", "a"], k=5)
    assert [item.id for item, _ in ranked] == ["a"]


def test_pinned_respects_candidate_filter():
    items = [_item("a"), _item("b")]
    p = PinnedRetriever(items)
    ranked = p.top_k(["a", "b"], k=5, candidate_filter=[False, True])
    assert [item.id for item, _ in ranked] == ["b"]


def test_pinned_empty_pin_list_returns_empty():
    items = [_item("a"), _item("b")]
    p = PinnedRetriever(items)
    assert p.top_k([], k=5) == []
