"""Synthetic corpus generator for the attention engine eval.

Builds a fake cell with KB + decisions + tasks + stream turns at three
sizes (200 / 1000 / 5000) so the eval can sweep the curve where
pure-LLM-with-everything-in-context starts breaking down.

Determinism: seeded RNG. Two runs at the same size produce identical
corpora — required for before/after comparisons across config tweaks.

The corpus is intentionally NOT a fixture of real production data:
  * keeps the dataset shippable (no PII, no membership leaks)
  * lets us tune the suppressed-vs-visible ratio for leak-rate stress
  * makes ground-truth labeling tractable (small enough vocabulary
    that a human can hand-label 30-50 queries against it)

Stub status (2026-04-29): the function returns a placeholder shape so
runner.py can exercise end-to-end. Real corpus content is the next
unit of work — needs: bilingual zh+en text bodies, realistic
decision/task lineage, scope-tier mix that exercises the membrane
suppress path, and at least a few intentionally-stale nodes for
recency-decay testing.
"""
from __future__ import annotations

import random
from collections.abc import Iterable

from .types import CorpusItem, NodeKind


# Mix of node kinds in a typical cell. Tweaked so a 200-node corpus has
# enough decisions/tasks for graph-neighbor retrieval to bite — pure
# kb-item-only corpora would let Config B (vector-only) look better
# than it would in production.
DEFAULT_KIND_MIX: dict[NodeKind, float] = {
    "kb_item": 0.45,
    "stream_turn": 0.25,
    "task": 0.12,
    "decision": 0.08,
    "risk": 0.06,
    "person": 0.04,
}

# Approximate fraction of nodes that should be suppressed (private to
# someone else / superseded / redacted). Drives the leak-rate stress
# test. 15% means a ~30-node "must not leak" pool in a 200-node corpus
# — large enough to be statistically meaningful without overwhelming.
DEFAULT_SUPPRESS_FRACTION = 0.15


def build_corpus(
    *,
    size: int,
    seed: int = 42,
    kind_mix: dict[NodeKind, float] | None = None,
    suppress_fraction: float = DEFAULT_SUPPRESS_FRACTION,
) -> list[CorpusItem]:
    """Generate a synthetic corpus of `size` nodes.

    STUB: emits placeholder items with deterministic ids. Real text
    bodies + lineage + scope-tier distribution land in a follow-up
    commit alongside the seed queries.
    """
    rng = random.Random(seed)
    mix = kind_mix or DEFAULT_KIND_MIX
    kinds, weights = zip(*mix.items())

    items: list[CorpusItem] = []
    for i in range(size):
        kind = rng.choices(kinds, weights=weights, k=1)[0]
        suppressed = rng.random() < suppress_fraction
        # Stub content — replaced by a real generator that emits
        # plausible KB notes / decision summaries / task descriptions
        # with bilingual fragments and citation links.
        items.append(
            CorpusItem(
                id=f"n{i:05d}",
                kind=kind,
                scope="group",  # all-Cell for now; tier mix lands later
                title=f"[stub {kind} #{i}]",
                content=f"placeholder body for {kind} {i}",
                metadata={"seed": seed, "index": i},
                suppressed=suppressed,
            )
        )
    return items


def split_visible_and_suppressed(
    corpus: Iterable[CorpusItem],
) -> tuple[list[CorpusItem], list[CorpusItem]]:
    """Split helper for the leak-rate metric harness."""
    visible: list[CorpusItem] = []
    suppressed: list[CorpusItem] = []
    for item in corpus:
        (suppressed if item.suppressed else visible).append(item)
    return visible, suppressed
