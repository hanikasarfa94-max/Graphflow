"""The three retrieval configurations under test.

Each config is a callable: `(corpus, query) -> ConfigRunResult`. They
produce the same shape so the runner can swap them transparently.

Status:
  * Config A — LIVE: DeepSeek call with full visible corpus in context.
                Reads DEEPSEEK_API_KEY from .env via workgraph_agents.llm.
                One async LLM call per query, sync-bridged with asyncio.run.
  * Config B — STUB: returns deterministic top-3 by id. Real impl will
                use a sentence-transformer (chromadb in-memory) + DeepSeek.
  * Config C — STUB: returns deterministic top-3 by id with mock audit
                explanations. Real impl wires hybrid retrieval + RRF +
                rule membrane + rank + DeepSeek (§7 stack).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .types import ConfigRunResult, CorpusItem, Query


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
    title + content) and ask for a strict-JSON response naming which
    ids ground the query. response_format=json_object on the API call
    keeps parsing deterministic.
    """
    nodes_payload = [
        {
            "id": item.id,
            "kind": item.kind,
            "scope": item.scope,
            "title": item.title,
            "content": item.content,
        }
        for item in visible
    ]
    system = (
        "You are a retrieval assistant for a collaboration platform. "
        "Given a corpus of nodes (KB items, decisions, tasks, risks, "
        "stream turns) and a user query, return ONLY the node ids "
        "whose content directly grounds an answer to the query. Prefer "
        "recent / active content over older / superseded content when "
        "both touch the same fact. Return strict JSON of shape "
        '{"cited_ids": ["..."], "reasoning": "..."}. Cite zero ids if '
        "nothing grounds the query."
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


def config_b_vector_only(
    corpus: Sequence[CorpusItem],
    query: Query,
) -> ConfigRunResult:
    """Top-K vector retrieval, then LLM.

    STUB: returns a deterministic 'top-3 by id' from the viewer-visible
    pool. Real impl will use a sentence-transformer via the existing
    workgraph_agents embedding hook (or chromadb).
    """
    started = time.monotonic()
    visible = [
        item
        for item in corpus
        if _viewer_can_see(item, query.viewer_id) and not item.suppressed
    ][:3]
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


CONFIGS = {
    "A": config_a_llm_only,
    "B": config_b_vector_only,
    "C": config_c_full_stack,
}
