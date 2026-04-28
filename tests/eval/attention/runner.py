"""Eval orchestrator — runs one Config over a corpus + query set,
producing a ConfigSummary.

Usage:
    summaries = run_all_configs(corpus_size=200, queries=load_queries())
    write_report(summaries, path="attention_eval_report.json")

Pure orchestration; the heavy lifting (LLM calls, retrieval) lives in
configs.py. Metrics live in metrics.py. Both swap implementations
without touching this file.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import yaml

from .configs import CONFIGS
from .corpus import build_corpus
from .metrics import summarize
from .types import ConfigRunResult, ConfigSummary, GroundTruth, Query


REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_QUERIES_PATH = (
    REPO_ROOT / "tests" / "eval" / "dataset" / "attention" / "seed_queries.yaml"
)


def load_seed_queries(
    path: Path = SEED_QUERIES_PATH,
) -> tuple[list[Query], dict[str, GroundTruth]]:
    """Load the YAML fixture into Query + GroundTruth pairs.

    Fixture shape (one document per file containing a list):
        - id: q01
          viewer_id: u_alice
          text: "..."
          scope_anchor: {cell_id: c_demo}
          must_appear: [n00012, n00045]
          must_not_appear: [n00099]
          notes: "..."
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    queries: list[Query] = []
    truths: dict[str, GroundTruth] = {}
    for entry in raw or []:
        q = Query(
            id=entry["id"],
            viewer_id=entry["viewer_id"],
            text=entry["text"],
            scope_anchor=entry.get("scope_anchor", {}),
        )
        truths[q.id] = GroundTruth(
            query_id=q.id,
            must_appear=tuple(entry.get("must_appear", [])),
            must_not_appear=tuple(entry.get("must_not_appear", [])),
            notes=entry.get("notes", ""),
        )
        queries.append(q)
    return queries, truths


def run_config(
    *,
    config_name: str,
    corpus_size: int,
    queries: Sequence[Query],
    truth_by_query: dict[str, GroundTruth],
    seed: int = 42,
) -> ConfigSummary:
    """Run one config over the corpus + queries; return a summary."""
    config_fn = CONFIGS[config_name]
    corpus = build_corpus(size=corpus_size, seed=seed)
    results: list[ConfigRunResult] = []
    for query in queries:
        results.append(config_fn(corpus, query))
    return summarize(config_name, corpus_size, results, truth_by_query)


def run_all_configs(
    *,
    corpus_size: int,
    queries: Sequence[Query],
    truth_by_query: dict[str, GroundTruth],
    seed: int = 42,
) -> list[ConfigSummary]:
    """Sweep A / B / C at one corpus size."""
    return [
        run_config(
            config_name=name,
            corpus_size=corpus_size,
            queries=queries,
            truth_by_query=truth_by_query,
            seed=seed,
        )
        for name in ("A", "B", "C")
    ]


def write_report(
    summaries: Sequence[ConfigSummary],
    *,
    path: Path,
) -> None:
    """Dump summaries as JSON for downstream comparison / dashboards."""
    payload = [
        {**asdict(s), "per_query": [asdict(r) for r in s.per_query]}
        for s in summaries
    ]
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
