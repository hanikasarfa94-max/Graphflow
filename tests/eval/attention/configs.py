"""The three retrieval configurations under test.

Each config is a callable: `(corpus, query) -> ConfigRunResult`. They
produce the same shape so the runner can swap them transparently.

Status:
  * Config A — LIVE: DeepSeek call with full visible corpus in context.
                Reads DEEPSEEK_API_KEY from .env via workgraph_agents.llm.
                One async LLM call per query, sync-bridged with asyncio.run.
  * Config B — LIVE (slice 1): BM25 top-50 → DeepSeek over the survivors.
                Pure-lexical retrieval baseline; vector layer lands in
                slice 2 and the rank-list interface composes via RRF in
                slice 4. See `tests/eval/attention/retrievers.py`.
  * Config C — STUB: returns deterministic top-3 by id with mock audit
                explanations. Real impl wires hybrid retrieval + RRF +
                rule membrane + rank + DeepSeek (§7 stack).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .embeddings import (
    EmbeddingsCache,
    SiliconFlowEmbeddingClient,
    embed_with_cache,
)
from .retrievers import BM25Retriever, VectorRetriever
from .types import ConfigRunResult, CorpusItem, Query


# Synthesizing a `created_at` for items whose corpus row doesn't carry
# one (KB / decision / task / risk in the hand-curated spine; the
# realistic generator already populates `metadata.ts`). The exact
# distribution doesn't matter for the eval — production will replace
# this stub with the real `created_at` column when §7.4 wires up. What
# matters is that timestamps span widely enough that the LLM sees a
# real recency contrast across items of the same topic.
#
# This implementation is intentionally lifted from the experiment
# script (`tests/eval/scripts/test_report_experiments.py`) verbatim,
# math quirk and all: the band-of-minutes-times-60 effectively yields
# ages up to ~12 years for kb_items, ~2 years for stream_turns. The
# spread is what drove the validated +0.137 recall lift at 200 nodes
# (Test 1 in `tests/eval/reports/test_report.md`). A "more correct"
# narrow spread loses that signal — see commit message for diagnosis.
_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
_AGE_BANDS_DAYS = {
    "stream_turn": (1, 14),
    "task": (1, 30),
    "risk": (7, 45),
    "decision": (3, 60),
    "kb_item": (15, 90),
    "person": (1, 365),
}


def _synthetic_ts(item: CorpusItem) -> str:
    """Deterministic ISO timestamp for an item without metadata.ts.

    Hashes the id to a stable offset within the kind's age band. The
    generated padding (`tests/eval/dataset/attention/realistic_padding
    .json`) already carries `metadata.ts`, so this only fires on the
    hand-curated spine for kinds other than stream_turn.

    Math note: the `offset * 60` multiplier on a minutes-domain offset
    is intentional (see module docstring above). Yields a wide
    inter-item time spread that the LLM can use as a recency signal.
    """
    raw = item.metadata.get("ts") if item.metadata else None
    if raw:
        return str(raw)
    h = int(hashlib.sha1(item.id.encode("utf-8")).hexdigest(), 16)
    band = _AGE_BANDS_DAYS.get(item.kind, (1, 90))
    span_days = band[1] - band[0]
    offset = band[0] + (h % (span_days * 24 * 60))
    age = timedelta(minutes=offset * 60)
    return (_NOW - age).isoformat()


# Lazy LLMClient singleton. The agents package isn't on sys.path during
# eval runs because tests/eval/ is run from the repo root, not via the
# api app's import graph. We add it once on first config-A invocation.
_LLM_CLIENT = None


def _get_llm_client():
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        repo_root = Path(__file__).resolve().parents[3]
        agents_src = repo_root / "packages" / "agents" / "src"
        if str(agents_src) not in sys.path:
            sys.path.insert(0, str(agents_src))
        from workgraph_agents.llm import LLMClient  # type: ignore[import-not-found]

        _LLM_CLIENT = LLMClient()
    return _LLM_CLIENT


def _viewer_can_see(item: CorpusItem, viewer_id: str) -> bool:
    """Scope-tier visibility for the viewer.

    Personal items belong to one user — only that user reads them.
    Group / department / enterprise are visible to anyone in the cell /
    department / org. Suppressed items still pass this filter — Config
    A's whole purpose is to test whether pure-LLM-with-everything-visible
    leaks them. The §7.7 floor decision turns on the answer.
    """
    if item.scope == "personal":
        return item.metadata.get("owner") == viewer_id
    return True


def _pack_prompt(
    visible: Sequence[CorpusItem],
    query: Query,
) -> list[dict[str, str]]:
    """Build chat messages for Config A.

    Hand the LLM a JSON listing of visible nodes (id + kind + scope +
    title + content + created_at) and ask for a strict-JSON response
    naming which ids ground the query. response_format=json_object on
    the API call keeps parsing deterministic.

    Timestamps were validated as a +0.137 recall lift at 200 nodes
    (Test 1 in `tests/eval/reports/test_report.md`). Three of five
    chronic-miss queries (q07/q08/q09) recovered with no other change.
    """
    nodes_payload = [
        {
            "id": item.id,
            "kind": item.kind,
            "scope": item.scope,
            "title": item.title,
            "content": item.content,
            "created_at": _synthetic_ts(item),
        }
        for item in visible
    ]
    system = (
        "You are a retrieval assistant for a collaboration platform. "
        "Given a corpus of nodes (KB items, decisions, tasks, risks, "
        "stream turns) and a user query, return ONLY the node ids "
        "whose content directly grounds an answer to the query. Prefer "
        "recent / active content over older / superseded content when "
        "both touch the same fact. Each node carries a `created_at` "
        "ISO timestamp; weight recent content higher when the query "
        "asks about current / latest / still / now state. Older "
        "content for the same fact has likely been superseded. Return "
        'strict JSON of shape {"cited_ids": ["..."], "reasoning": "..."}. '
        "Cite zero ids if nothing grounds the query."
    )
    user = json.dumps(
        {
            "viewer_id": query.viewer_id,
            "query": query.text,
            "scope_anchor": query.scope_anchor,
            "corpus": nodes_payload,
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_cited_ids(content: str, valid_ids: set[str]) -> tuple[str, ...]:
    """Parse the JSON response and filter to ids that exist in the corpus.

    Hallucinated ids (model invents an id not in the corpus) are dropped
    — counting them would inflate leaks falsely. Malformed JSON returns
    an empty cite list, which scores as a recall miss (correctly).
    """
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return ()
    raw = payload.get("cited_ids") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return ()
    return tuple(
        str(x) for x in raw if isinstance(x, str) and x in valid_ids
    )


def config_a_llm_only(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Pure LLM with everything visible to the viewer (LIVE — DeepSeek).

    No retrieval, no membrane filter, no rerank. The LLM gets the full
    set of nodes the viewer is technically allowed to see (scope-tier
    accessible + their own personal items, including any suppressed
    ones) and must decide which to cite.

    The §7.7 ship-floor decision rule (PLAN-Next.md §N.1.5) hinges on
    this config's leak_rate: if Config A cites any must_not_appear node,
    membrane post-filter ships mandatorily — regardless of what F1
    looks like elsewhere.

    Sync wrapper around the async LLMClient so the existing sync
    runner (run_config → config_fn) works unchanged. asyncio.run per
    query is fine for dev-time eval (12 queries × ~5-10s each ≈ 1-2
    min total); production retrieval would use a single event loop.
    """
    visible = [
        item for item in corpus if _viewer_can_see(item, query.viewer_id)
    ]
    visible_ids = {item.id for item in visible}
    suppressed_ids = {item.id for item in corpus if item.suppressed}

    client = _get_llm_client()
    messages = _pack_prompt(visible, query)

    started = time.monotonic()
    result = asyncio.run(
        client.complete(
            messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    cited = _parse_cited_ids(result.content, visible_ids)
    suppressed_cited = tuple(sorted(set(cited) & suppressed_ids))

    return ConfigRunResult(
        config="A",
        query_id=query.id,
        cited_node_ids=cited,
        suppressed_cited=suppressed_cited,
        tokens_in=result.prompt_tokens,
        tokens_out=result.completion_tokens,
        latency_ms=elapsed_ms,
    )


def config_b_bm25(
    corpus: Sequence[CorpusItem],
    query: Query,
    *,
    k: int = 50,
) -> ConfigRunResult:
    """BM25 top-k → DeepSeek over the survivors (LIVE — slice 1).

    Pure lexical baseline: builds a fresh BM25 index over the visible
    pool, retrieves the top-k items, then hands them (and only them)
    to the LLM with the same prompt frame Config A uses. The §7.7
    membrane gate runs *before* retrieval (visibility filter); BM25
    ranks within what the viewer is allowed to see.

    Slice 1 of the §7.2 hybrid stack. Vector / graph-neighbor /
    recency / pinned land in subsequent slices and compose via RRF
    (slice 4). At that point Config B can keep its lexical-baseline
    role while Config C carries the full hybrid.

    Index-per-query is wasted work in production — the index would
    be built once per project and incrementally maintained — but at
    eval scale (538 nodes × ~12 queries) it's microseconds and keeps
    the call site dependency-free.
    """
    started = time.monotonic()
    visible = [
        item for item in corpus if _viewer_can_see(item, query.viewer_id)
    ]
    visible_ids = {item.id for item in visible}
    suppressed_ids = {item.id for item in corpus if item.suppressed}

    retriever = BM25Retriever(visible)
    ranked = retriever.top_k(query.text, k=k)
    candidates = [item for item, _score in ranked]

    if not candidates:
        # No lexical signal at all — return early with a recall miss
        # rather than burn an LLM call on an empty prompt.
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ConfigRunResult(
            config="B",
            query_id=query.id,
            cited_node_ids=(),
            suppressed_cited=(),
            tokens_in=0,
            tokens_out=0,
            latency_ms=elapsed_ms,
        )

    client = _get_llm_client()
    messages = _pack_prompt(candidates, query)
    result = asyncio.run(
        client.complete(
            messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    cited = _parse_cited_ids(result.content, visible_ids)
    suppressed_cited = tuple(sorted(set(cited) & suppressed_ids))

    return ConfigRunResult(
        config="B",
        query_id=query.id,
        cited_node_ids=cited,
        suppressed_cited=suppressed_cited,
        tokens_in=result.prompt_tokens,
        tokens_out=result.completion_tokens,
        latency_ms=elapsed_ms,
    )


def config_c_full_stack(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Full §7 stack: hybrid retrieval + RRF + membrane filter + rank.

    STUB: returns a deterministic 'top-3 by id' from the viewer-visible
    pool with audit explanations populated, demonstrating the audit-
    score axis where Config C should pull ahead. Real impl wires:
      * BM25 + vector + graph-neighbor (§7.2 hybrid retrieval)
      * RRF fusion (§7.2)
      * Rule-based membrane filter — drops anything `suppressed=True`
        (§7.7; the only ship-floor regardless of eval outcome)
      * Explainable rank with weighted features (§7.4)
      * Context-bundle assembly (§7.8)
    """
    started = time.monotonic()
    visible = [
        item
        for item in corpus
        if _viewer_can_see(item, query.viewer_id) and not item.suppressed
    ][:3]
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


# ---------------------------------------------------------------------------
# Vector-only config (slice 2). Not in CONFIGS — driven by its own eval
# script for the slice-2 baseline measurement. Slice 4's hybrid (Config C)
# will compose this with BM25 + graph + recency + pinned via RRF.
# ---------------------------------------------------------------------------


def _embedding_text(item: CorpusItem) -> str:
    """Concat title + content for embedding.

    Title is repeated twice — same intuition as BM25's title weight:
    the document title is stronger semantic signal than buried body
    content. (Less aggressive than BM25's ×3 because vector models
    don't double-count the same way TF does.)
    """
    title = (item.title or "").strip()
    body = (item.content or "").strip()
    if title and body:
        return f"{title}\n{title}\n{body}"
    return title or body


def make_config_b_vector_only(
    corpus: Sequence[CorpusItem],
    *,
    cache_path: "Path | None" = None,
):
    """Factory: build a Config-B-shaped vector-only callable.

    Embedding the corpus is one-time work amortized across every query
    in the run, so we factor it out of the per-query function. Returns
    a callable matching the `(corpus, query) -> ConfigRunResult` shape
    the runner expects.

    `cache_path` defaults to `tests/eval/dataset/attention/
    qwen3_embeddings.json`. Reusable across runs — only new content
    triggers an API call.
    """
    repo_root = Path(__file__).resolve().parents[3]
    if cache_path is None:
        cache_path = (
            repo_root
            / "tests"
            / "eval"
            / "dataset"
            / "attention"
            / "qwen3_embeddings.json"
        )

    cache = EmbeddingsCache(cache_path)
    client = SiliconFlowEmbeddingClient()

    item_texts = [_embedding_text(item) for item in corpus]
    item_vectors = asyncio.run(embed_with_cache(item_texts, cache, client))
    retriever = VectorRetriever(corpus, item_vectors)

    def _config_b_vector_only(
        _corpus: Sequence[CorpusItem],
        query: Query,
        *,
        k: int = 50,
    ) -> ConfigRunResult:
        """Vector top-k → DeepSeek over the survivors (LIVE — slice 2).

        Same prompt frame as Config A and Config B/BM25, just retrieving
        candidates by cosine similarity instead of BM25 score. The
        membrane gate runs first (visibility filter), then vector
        ranks among visible items.
        """
        started = time.monotonic()
        visible_mask = [
            _viewer_can_see(item, query.viewer_id) for item in corpus
        ]
        visible_ids = {
            item.id for item, ok in zip(corpus, visible_mask) if ok
        }
        suppressed_ids = {item.id for item in corpus if item.suppressed}

        # Embed the query (cached so re-runs of the same query set are
        # zero-API).
        q_vectors = asyncio.run(
            embed_with_cache([query.text], cache, client)
        )
        q_vec = q_vectors[0]
        ranked = retriever.top_k(
            q_vec, k=k, candidate_filter=visible_mask
        )
        candidates = [item for item, _score in ranked]

        if not candidates:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return ConfigRunResult(
                config="B",
                query_id=query.id,
                cited_node_ids=(),
                suppressed_cited=(),
                tokens_in=0,
                tokens_out=0,
                latency_ms=elapsed_ms,
            )

        llm = _get_llm_client()
        messages = _pack_prompt(candidates, query)
        result = asyncio.run(
            llm.complete(
                messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        cited = _parse_cited_ids(result.content, visible_ids)
        suppressed_cited = tuple(sorted(set(cited) & suppressed_ids))

        return ConfigRunResult(
            config="B",
            query_id=query.id,
            cited_node_ids=cited,
            suppressed_cited=suppressed_cited,
            tokens_in=result.prompt_tokens,
            tokens_out=result.completion_tokens,
            latency_ms=elapsed_ms,
        )

    return _config_b_vector_only


CONFIGS = {
    "A": config_a_llm_only,
    "B": config_b_bm25,
    "C": config_c_full_stack,
}
