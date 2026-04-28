"""The three retrieval configurations under test.

Each config is a callable: `(corpus, query) -> ConfigRunResult`. They
produce the same shape so the runner can swap them transparently.

STUB status: all three return placeholder ConfigRunResults. Real
implementations:
  * Config A — DeepSeek call with full corpus in context
  * Config B — vector index (likely chromadb in-memory) + DeepSeek
  * Config C — hybrid retrieval + RRF + rule membrane + ranked
                cands + DeepSeek

The stubs let runner.py + test_attention_eval.py wire end-to-end so
later commits only need to fill in the config bodies, not change
shapes.
"""
from __future__ import annotations

import time
from collections.abc import Sequence

from .types import ConfigRunResult, CorpusItem, Query


def config_a_llm_only(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Pure LLM with everything visible in context.

    No retrieval. No filtering. Cites everything the viewer is
    *technically* allowed to see (suppressed=False) and lets the LLM
    use whatever it wants.

    STUB: cites the first 5 visible items and reports zero latency /
    zero tokens. Real impl will pack the full corpus into a DeepSeek
    request and parse cited node ids back from the response.
    """
    started = time.monotonic()
    visible = [item.id for item in corpus if not item.suppressed]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConfigRunResult(
        config="A",
        query_id=query.id,
        cited_node_ids=tuple(visible[:5]),
        suppressed_cited=(),
        tokens_in=0,
        tokens_out=0,
        latency_ms=elapsed_ms,
    )


def config_b_vector_only(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Top-K vector retrieval, then LLM.

    STUB: returns a deterministic 'top-3 by id' since there's no real
    embedding yet. Real impl will use a sentence-transformer via the
    existing workgraph_agents embedding hook (or chromadb).
    """
    started = time.monotonic()
    visible = [item for item in corpus if not item.suppressed][:3]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConfigRunResult(
        config="B",
        query_id=query.id,
        cited_node_ids=tuple(item.id for item in visible),
        suppressed_cited=(),
        tokens_in=0,
        tokens_out=0,
        latency_ms=elapsed_ms,
    )


def config_c_full_stack(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Full §7 stack: hybrid retrieval + RRF + membrane filter + rank.

    STUB: returns a deterministic 'top-3 by id' with audit
    explanations populated, demonstrating the audit-score axis where
    Config C should pull ahead. Real impl wires:
      * BM25 + vector + graph-neighbor (§7.2 hybrid retrieval)
      * RRF fusion (§7.2)
      * Rule-based membrane filter — drops anything `suppressed=True`
        (§7.7; the only ship-floor regardless of eval outcome)
      * Explainable rank with weighted features (§7.4)
      * Context-bundle assembly (§7.8)
    """
    started = time.monotonic()
    visible = [item for item in corpus if not item.suppressed][:3]
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return ConfigRunResult(
        config="C",
        query_id=query.id,
        cited_node_ids=tuple(item.id for item in visible),
        suppressed_cited=(),
        tokens_in=0,
        tokens_out=0,
        latency_ms=elapsed_ms,
        explanations={
            item.id: f"stub: kept by §7 stack (kind={item.kind})"
            for item in visible
        },
    )


CONFIGS = {
    "A": config_a_llm_only,
    "B": config_b_vector_only,
    "C": config_c_full_stack,
}
