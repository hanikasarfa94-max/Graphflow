"""decision_crystallize policy.

Stage A v0 — ADVISORY ONLY by default. Always returns `auto_merge`
unless the M4 semantic reviewer finds a clear contradiction AND the
candidate carries no `supersedes` ref in its metadata. Otherwise
warnings are surfaced through the response so the membrane-notes UI
can show "FYI: this overlaps with an earlier crystallized decision"
without disrupting the decision-making cadence.

Action vocabulary:
  auto_merge | request_review | request_clarification | reject

Failure mode: unlike KB / task, decision agent failures fall back to
ADVISORY (return `None` from the agent path). Decision crystallization
is more sensitive to false-block than KB / task — fail-closed here
would surprise established gates (vote resolve, gated proposal
approve) that already had human review.
"""
from __future__ import annotations

import logging

from workgraph_persistence import (
    DecisionRepository,
    session_scope,
)

from .base import MembraneCandidate, MembraneContext, MembraneReview
from .deterministic import _normalize_title
from .pretext import build_decision_review_packet

_log = logging.getLogger("workgraph.api.membrane.decision_policy")


async def review_decision_crystallize(
    candidate: MembraneCandidate,
    context: MembraneContext,
) -> MembraneReview:
    """Pre-crystallize checks for a Decision about to enter the cell.

    QA-confusion fix: decisions today land in the graph through 7
    different code paths (conflict resolve, IM apply, gated proposal
    approve/vote, silent consensus ratify, scrimmage convergence,
    meeting signal accept). Each path has its own upstream gate
    (a conflict opened, a vote threshold reached, an owner ratifying
    consensus, etc.), which is why "how does a decision get into the
    graph?" is hard to answer. Routing them all through
    MembraneService.review() gives one mental model: every decision
    crosses the same boundary before becoming a load-bearing fact
    in the cell.

    Stage A v0 — ADVISORY ONLY. Always returns `auto_merge` so the
    path completes as before, but `warnings` carries the membrane's
    observations. The caller surfaces them in the response (and
    eventually the membrane-notes UI). This keeps the existing
    flows working while still:
      - Audit-logging that the membrane was consulted on every
        decision
      - Giving us a single place to add real blocking rules later
        (LLM contradiction check, scope re-litigation, gated
        reversal — all deferred to Stage A+1)
      - Letting the proposer / owner notice "FYI: this overlaps with
        an earlier crystallized decision" without disrupting the
        decision-making cadence

    Why advisory-not-blocking: every upstream path that calls us
    (conflict resolve, gated proposal approve, ratify, etc.) has
    ALREADY been reviewed by humans. Blocking again would feel like
    the system second-guessing the human's own gate. Surfacing
    warnings, on the other hand, is the membrane being a good
    nervous system: noticing patterns the humans might have missed
    because each gate sees only its own slice. The 5 load-bearing
    rules for decisions get their day when we have the eval data
    to trust them.

    Rules v0:
      1. Title near-duplicate against an existing crystallized
         decision in this project → warning. Symmetric to
         kb_item_group's dup-check; same _normalize_title rules.
         Surfaces "you might be silently overwriting prior intent."
      2. Missing rationale → warning. Decisions without a recorded
         "why" are weaker audit material. Skipped for gated proposal
         and scrimmage sources whose rationale lives elsewhere.
    """
    warnings: list[str] = []

    rationale = (
        (candidate.metadata.get("rationale") or "").strip()
        if isinstance(candidate.metadata, dict)
        else ""
    )
    source = (
        candidate.metadata.get("source")
        if isinstance(candidate.metadata, dict)
        else None
    )

    # Rule 2: missing rationale → advisory warning.
    if not rationale and source not in ("gated_proposal", "scrimmage"):
        warnings.append(
            "This decision was crystallized without a recorded "
            "rationale. Future readers will see the action but not "
            "the why — consider adding one before the next gate."
        )

    # Rule 1: title near-duplicate scan against recent crystallized
    # decisions in this project.
    normalized_new = _normalize_title(candidate.title)
    if normalized_new:
        async with session_scope(context.sessionmaker) as session:
            recent = await DecisionRepository(session).list_for_project(
                candidate.project_id, limit=100
            )
        for row in recent:
            if row.apply_outcome in ("rejected", "pending_scrimmage"):
                continue
            row_title = (row.custom_text or row.rationale or "")[:500]
            if _normalize_title(row_title) == normalized_new:
                warnings.append(
                    f"A prior decision in this project has the same "
                    f"title-equivalent: '{row_title[:120]}' "
                    f"(id={row.id}). Confirm this is a deliberate "
                    f"supersede, not an accidental re-litigation."
                )
                break  # one collision warning is enough

    # Slice M4 — semantic reviewer as the *last* gate. Same pattern
    # as M1 (KB) and M3 (task), but the verdict mapping is softer:
    #
    # Per spec §M4 / §9: keep human-reviewed decision paths mostly
    # advisory. The agent's `request_review` becomes a real block
    # ONLY when the candidate carries no `supersedes` ref in its
    # metadata. Reasoning: the upstream paths (vote resolve, gated
    # proposal approve, conflict resolve, scrimmage convergence)
    # have already been reviewed by humans; blocking again would
    # second-guess that gate. But if the agent sees a clear
    # contradiction with prior decisions and the proposer didn't
    # mark it as a deliberate supersede, that's exactly the
    # "accidental re-litigation" rule 1 already warns about — and
    # an explicit block helps the proposer notice before the
    # decision lands as a load-bearing fact.
    if context.agent_reviewer is not None:
        agent_action = await _agent_review_decision_candidate(
            candidate=candidate,
            deterministic_warnings=warnings,
            context=context,
        )
        if agent_action is not None:
            return agent_action

    return MembraneReview(
        action="auto_merge",
        reason="advisory_only" if warnings else "no_conflicts",
        warnings=tuple(warnings),
    )


async def _agent_review_decision_candidate(
    *,
    candidate: MembraneCandidate,
    deterministic_warnings: list[str],
    context: MembraneContext,
) -> MembraneReview | None:
    """Build a decision review packet (spec §5.4) and run the
    Membrane Agent. Returns:

      * `None` — let the deterministic auto_merge path proceed.
        Used when the agent permits the candidate, AND when the
        agent's review verdict is treated as advisory-only because
        the candidate carries a supersede marker.
      * a `MembraneReview` with action != auto_merge — overrides
        the existing advisory flow with a real block.

    Failure modes return `None` (preserve the advisory pre-M4
    behavior) since decision crystallization is more sensitive to
    false-block than KB / task — fail-closed here would surprise
    established gates (vote resolve, gated proposal approve)
    that already had human review.
    """
    assert context.agent_reviewer is not None
    builder = context.decision_pretext_builder or build_decision_review_packet
    try:
        packet = await builder(
            candidate=candidate,
            deterministic_warnings=deterministic_warnings,
            context=context,
        )
    except Exception:
        _log.exception(
            "membrane.agent_review.decision_pretext_failed",
            extra={"project_id": candidate.project_id},
        )
        return None

    # §7 gate — skip the LLM when nothing to review against.
    if (
        not packet["prior_decisions"]
        and not packet["related_kb"]
    ):
        return None

    try:
        outcome = await context.agent_reviewer.review_candidate(packet)
    except Exception:
        _log.exception(
            "membrane.agent_review.decision_call_failed",
            extra={"project_id": candidate.project_id},
        )
        return None

    review = outcome.review
    if review.action == "auto_merge":
        return None

    # M4 softer mapping: only block when there's no supersede
    # marker. With a supersede ref present, treat the agent's
    # concern as advisory and let the existing flow proceed
    # (warning carried through).
    metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
    has_supersede = bool(
        metadata.get("supersedes")
        or metadata.get("supersedes_decision_id")
        or metadata.get("supersedes_ref")
    )
    if has_supersede:
        return None  # advisory; warnings already carried by caller

    conflict_ids = tuple(
        ref.partition(":")[2]
        for ref in review.conflict_with
        if ref.partition(":")[2]
    )
    merged_warnings = list(deterministic_warnings) + list(review.warnings)
    return MembraneReview(
        action=review.action,
        reason=review.reason,
        diff_summary=review.diff_summary,
        clarify_question=review.clarify_question,
        conflict_with=conflict_ids,
        warnings=tuple(merged_warnings),
    )


__all__ = [
    "review_decision_crystallize",
]
