"""Shared types for the attention engine eval.

Dataclass shapes only — no behavior. Frozen wherever possible so a
downstream config can't accidentally mutate fixtures mid-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# Kinds of nodes the corpus generator emits. Mirrors graph node kinds
# but is intentionally a flat string set (not the production enum) so
# the eval stays decoupled from prod schema churn.
NodeKind = Literal[
    "kb_item",      # KbItemRow analog — KB note (any scope tier)
    "decision",     # DecisionRow analog
    "task",         # PlanTask analog
    "risk",         # RiskRow analog
    "stream_turn",  # MessageRow analog — past chat turn
    "person",       # UserRow analog — for skill/authority routing
]

# Scope tier on a corpus item. Mirrors KbItemRow.scope (legacy 'group'
# = Cell scope; see new_concepts.md §6.11).
NodeScope = Literal["personal", "group", "department", "enterprise"]


@dataclass(frozen=True)
class CorpusItem:
    """One node in the synthetic corpus.

    The eval treats the corpus as opaque: configs A/B/C only see what
    they're allowed to see (per scope + membrane rules). Ground truth
    references nodes by `id`.
    """

    id: str
    kind: NodeKind
    scope: NodeScope
    title: str
    content: str
    # Free-form metadata. Configs may inspect for ranking signals
    # (recency, owner, status, citations, tags, etc.).
    metadata: dict[str, Any] = field(default_factory=dict)
    # If True, this node was suppressed by membrane policy (private,
    # superseded, redacted, sensitive). Configs MUST NOT cite a
    # suppressed node — leaks count against the leak_rate metric.
    suppressed: bool = False


@dataclass(frozen=True)
class Query:
    """A user-style question over the corpus.

    `viewer_id` matters: scope filtering and membrane membership depend
    on who's asking. The same query may resolve differently for two
    viewers in the same cell.
    """

    id: str
    viewer_id: str
    text: str
    # Free-form context tag (cell_id / room_id / etc.) so retrieval
    # can scope to the conversation's anchor when relevant.
    scope_anchor: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundTruth:
    """Hand-labeled answer key for a Query.

    `must_appear` and `must_not_appear` are CorpusItem ids. The eval is
    structural — we score whether the right nodes shaped the answer,
    not whether the LLM's prose was "good." Prose quality is for a
    separate downstream eval if needed.
    """

    query_id: str
    must_appear: tuple[str, ...]      # F1 numerator + recall floor
    must_not_appear: tuple[str, ...]  # leak_rate denominator
    # Optional notes for human reviewers — never read by the runner.
    notes: str = ""


@dataclass
class ConfigRunResult:
    """Output of running a single Config over one Query."""

    config: Literal["A", "B", "C"]
    query_id: str
    cited_node_ids: tuple[str, ...]      # what the config used in context
    suppressed_cited: tuple[str, ...]    # leak set (cited ∩ suppressed)
    tokens_in: int
    tokens_out: int
    latency_ms: int
    # Optional: per-node "why was this kept/dropped?" trace. Populated
    # by Config C; A/B leave empty.
    explanations: dict[str, str] = field(default_factory=dict)


@dataclass
class ConfigSummary:
    """Aggregate over all queries for one config × one corpus size."""

    config: Literal["A", "B", "C"]
    corpus_size: int
    n_queries: int
    f1: float
    precision: float
    recall: float
    leak_rate: float       # fraction of queries with ≥1 suppressed leak
    n_leaks: int           # total suppressed nodes cited across queries
    tokens_total: int
    latency_p50_ms: int
    latency_p95_ms: int
    audit_score: float     # 0.0 (no explanations) to 1.0 (every cite has why)
    per_query: list[ConfigRunResult] = field(default_factory=list)
