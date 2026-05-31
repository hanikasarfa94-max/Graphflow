"""Shared types for the membrane policy registry.

This module is the contract surface between `MembraneService` (facade
in `services/membrane.py`) and the per-candidate-kind policy modules.
It is deliberately side-effect free — no DB access, no LLM calls,
no notifications. Pure dataclasses + Protocol so the policy modules
can be imported and unit-tested in isolation.

Why a `MembraneContext`: each policy needs the same handful of
service-level dependencies (sessionmaker, optional semantic
reviewer agent). Bundling them keeps each policy a free function
with a tidy signature instead of leaking the whole `MembraneService`
into per-kind modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import MembraneAgentReviewer


# Stage 2 of the membrane reorg (docs/membrane-reorg.md). Candidates
# trying to enter the cell go through review() — same boundary as
# ingest() for external signals, opposite direction.
ReviewAction = Literal[
    "auto_merge",            # write to cell, no review needed
    "request_review",        # queue for owner approval
    "request_clarification", # back-channel Q&A with proposer first
    "reject",                # log + notify proposer with reason
]

# Candidate kinds the membrane review() understands. Each promote
# path picks one; the review function uses it to choose which checks
# to run. Unknown kinds fall through to auto_merge (review() default).
#
# N-Next additions (manual_*): per new_concepts.md §6.11 + north-star
# Correction R.4, manual-typed creates do not become canonical state
# directly — they enter as candidates and ascend through Membrane like
# any other promotion. The actual creation routes (POST /api/projects,
# POST /api/streams for rooms) wire to these kinds in N.4; the enum
# values are added now so call sites and tests can reference them.
CandidateKind = Literal[
    "kb_item_group",         # group-scope KbItemRow about to be created
    "task_promote",          # personal TaskRow being promoted to plan
    "decision_crystallize",  # DecisionRow about to crystallize
    "graph_edge",            # graph node/edge promotion
    "manual_project",        # N-Next: user-typed cell (project) candidate
    "manual_room",           # N-Next: user-typed team-room within a cell
]


@dataclass(frozen=True)
class MembraneCandidate:
    """A candidate trying to enter the cell.

    Shape is intentionally permissive — the review function pulls
    only the fields it needs per kind. Frozen so callers can't
    accidentally mutate state mid-review.
    """

    kind: CandidateKind
    project_id: str
    proposer_user_id: str
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MembraneReview:
    """Outcome of a review() call.

    `action` drives what the caller does next; `reason` is for logs +
    user-facing copy. `clarify_question` is populated only when
    action='request_clarification' (Stage 5). `conflict_with` lists
    cell node ids the candidate contradicts (Stage 3).

    `warnings` (Stage 6 — partial collapse of ConflictService): advisory
    notes about pre-existing issues in the cell that the proposer should
    know about. Does NOT block the action; the caller decides whether to
    surface them in UI. Used for graph-integrity signals that show up at
    promote time but originate elsewhere (e.g., "you're about to add a
    task to a requirement that already has 2 unstaffed tasks downstream
    of risks").
    """

    action: ReviewAction
    reason: str
    diff_summary: str | None = None
    clarify_question: str | None = None
    conflict_with: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    # M5 — id of the IMSuggestion the gate enqueued for owner review.
    # Populated only on `request_review` paths that DID create the
    # suggestion row (manual_room is one such; KB / task review create
    # their suggestions inline elsewhere). None otherwise.
    suggestion_id: str | None = None


@dataclass(frozen=True)
class MembraneContext:
    """Service-level dependencies a policy needs.

    Built once by `MembraneService.__init__` and threaded into each
    policy call. Side-effect free at construction; the sessionmaker
    and agent reviewer are the doors policies open inside their own
    `review_*` function bodies.

    The `*_pretext_builder` callables are seams the facade can swap
    in tests to simulate a pretext-builder bug (the M1.1 fail-closed
    contract). Default: bound methods on `MembraneService` that
    delegate to `pretext.build_*_review_packet`.
    """

    sessionmaker: async_sessionmaker
    agent_reviewer: MembraneAgentReviewer | None = None
    kb_pretext_builder: Callable[..., Awaitable[dict[str, Any]]] | None = None
    task_pretext_builder: Callable[..., Awaitable[dict[str, Any]]] | None = None
    decision_pretext_builder: (
        Callable[..., Awaitable[dict[str, Any]]] | None
    ) = None


class MembranePolicy(Protocol):
    """Per-candidate-kind review entry point.

    Each policy module exposes `review(candidate, context)` returning
    a `MembraneReview`. The facade routes by `candidate.kind`.
    Failure-mode is policy-specific: KB / task fail-closed to
    `request_review`; decision falls back to advisory `auto_merge`.
    """

    async def __call__(
        self,
        candidate: MembraneCandidate,
        context: MembraneContext,
    ) -> MembraneReview: ...


class MembraneReviewPort(Protocol):
    """The single method consumer services need from MembraneService.

    Lets DecisionService / IMService / KbItemService / SilentConsensusService
    (and PersonalStreamService / ProjectService / StreamService) type their
    late-bound membrane reference against a contract in this leaf module rather
    than against the heavy `services.membrane` facade — that's what keeps the
    services->membrane import cycle broken (audit M5) and makes the
    setter-injection seam (audit M3) honest. MembraneService satisfies this
    structurally; no nominal inheritance is required.
    """

    async def review(self, candidate: MembraneCandidate) -> MembraneReview: ...


__all__ = [
    "CandidateKind",
    "MembraneCandidate",
    "MembraneContext",
    "MembranePolicy",
    "MembraneReview",
    "MembraneReviewPort",
    "ReviewAction",
]
