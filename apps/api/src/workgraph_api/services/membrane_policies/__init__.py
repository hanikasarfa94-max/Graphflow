"""Membrane policy registry — internal package.

The public entry point is `MembraneService` in
`workgraph_api.services.membrane`. This package holds the decomposed
per-candidate-kind policy logic, deterministic helpers, and LLM
pretext builders that the facade orchestrates.

See `docs/membrane-reorg.md` for the boundary semantics and
`docs/architecture-organization.md §Phase B` for why this package
exists. Read order for new contributors:

  1. `base.py`              — shared types (MembraneCandidate /
                              MembraneReview / MembraneContext) +
                              the MembranePolicy Protocol.
  2. `deterministic.py`     — title-normalization, numeric-claim
                              conflict, topic-token helpers shared
                              by every policy.
  3. `pretext.py`           — LLM review-packet builders shared
                              between live policies and the M2 audit.
  4. `kb_policy.py`         — kb_item_group review.
  5. `task_policy.py`       — task_promote review.
  6. `decision_policy.py`   — decision_crystallize review (advisory).
  7. `manual_create_policy.py` — manual_room / manual_skill_change /
                                 manual_invite (non-owner stages a
                                 write).
  8. The facade in `membrane.py`.

Internals are not part of the public API. Import from
`workgraph_api.services` for `MembraneService` only.
"""
from __future__ import annotations

from .base import (
    MembraneCandidate,
    MembraneContext,
    MembranePolicy,
    MembraneReview,
    CandidateKind,
    ReviewAction,
)
from .decision_policy import review_decision_crystallize
from .kb_policy import audit_canonical_kb, review_kb_item_group
from .manual_create_policy import (
    review_manual_invite,
    review_manual_room,
    review_manual_skill_change,
)
from .task_policy import review_task_promote

__all__ = [
    "MembraneCandidate",
    "MembraneContext",
    "MembranePolicy",
    "MembraneReview",
    "CandidateKind",
    "ReviewAction",
    "audit_canonical_kb",
    "review_decision_crystallize",
    "review_kb_item_group",
    "review_manual_invite",
    "review_manual_room",
    "review_manual_skill_change",
    "review_task_promote",
]
