"""kb_item_group policy + the M2 audit walker.

Two responsibilities here:

  * `review_kb_item_group(candidate, context)` — pre-write checks
    for a group-scope KB candidate. Title near-duplicate detection
    (Stage 3), numeric-claim conflict guard, then the optional
    Slice M1 semantic reviewer as the last gate before auto_merge.
    Fail-CLOSED to `request_review` on agent-pretext / agent-call
    failures: the agent gate is the safety boundary, a bug in
    OUR code shouldn't open it.
  * `audit_canonical_kb(...)` — read-only existing-pollution audit
    (spec §M2). Replays the live agent path against rows that
    landed before M1 shipped. Returns a list of findings.

Action vocabulary:
  auto_merge | request_review | request_clarification | reject
"""
from __future__ import annotations

import logging
from typing import Any

from workgraph_persistence import (
    KbItemRepository,
    KbItemRow,
    session_scope,
)

from .._kb_visibility import is_canonical_kb_row
from .base import MembraneCandidate, MembraneContext, MembraneReview
from .deterministic import _first_numeric_fact_conflict, _normalize_title
from .pretext import build_kb_review_packet

_log = logging.getLogger("workgraph.api.membrane.kb_policy")


async def review_kb_item_group(
    candidate: MembraneCandidate,
    context: MembraneContext,
) -> MembraneReview:
    """Pre-write checks for a group-scope KB candidate.

    Stage 3 v0 — title near-duplicate detection. The most common
    failure mode for crowd-sourced wikis is "everyone writes
    their own slightly different page on the same topic." We catch
    the obvious case (same normalized title) and downgrade to
    request_review so the owner can decide: merge into the
    existing entry, supersede it, or accept as a related sibling.

    Not yet covered (stage 4+):
    - Full semantic contradiction with existing entries (needs LLM)
    - Conflict with crystallized DecisionRow rationales
    - Conflict with active CommitmentRow content
    - Stale-on-arrival (older than the most recent edit on the
      related node by N days)
    """
    normalized_new = _normalize_title(candidate.title)
    if not normalized_new:
        return MembraneReview(
            action="auto_merge",
            reason="empty_title_lets_caller_validate",
        )

    async with session_scope(context.sessionmaker) as session:
        existing = await KbItemRepository(session).list_group_for_project(
            project_id=candidate.project_id, limit=500
        )

    # First non-trivial title-match wins. Excluding archived rows
    # since they're explicitly retired by the owner — overwriting
    # the title on a new entry is fine and shouldn't trigger
    # review.
    for row in existing:
        if row.status == "archived":
            continue
        if _normalize_title(row.title) != normalized_new:
            continue

        # Stage 5: when the new entry differs in body size from the
        # existing one by a clear margin (>= 2x or <= 0.5x), the
        # proposer's intent is genuinely ambiguous — supersede,
        # elaborate as a section, or propose a separate entry under
        # a sharper title? Asking is more useful than blocking the
        # owner with a request_review the proposer needs to re-run
        # anyway. Otherwise (similar size) the existing
        # request_review path applies — owner decides.
        existing_len = len(row.content_md or "")
        new_len = len(candidate.content or "")
        size_ambiguous = (
            existing_len > 0
            and new_len > 0
            and (
                new_len >= existing_len * 2
                or new_len <= existing_len * 0.5
            )
        )
        # Skip clarification if the proposer already answered (the
        # caller re-ran review() with metadata['clarification_answer']
        # populated). Falls through to request_review then.
        already_answered = bool(
            candidate.metadata.get("clarification_answer")
        )

        if size_ambiguous and not already_answered:
            return MembraneReview(
                action="request_clarification",
                reason="duplicate_title_size_diverges",
                diff_summary=(
                    f"Same title as '{row.title}' (id={row.id}), "
                    f"but content size differs notably "
                    f"({new_len} vs {existing_len} chars)."
                ),
                clarify_question=(
                    f"An existing group KB entry titled '{row.title}' "
                    "already exists. Are you (a) SUPERSEDING it with "
                    "this new version, (b) ELABORATING — your entry "
                    "should become a section under the existing one, "
                    "or (c) PROPOSING a separate entry under a "
                    "sharper title? Reply 'supersede', 'elaborate', "
                    "or 'separate' (with the new title)."
                ),
                conflict_with=(row.id,),
            )

        return MembraneReview(
            action="request_review",
            reason="duplicate_title",
            diff_summary=(
                f"An existing group KB entry has the same title: "
                f"'{row.title}' (id={row.id}, status={row.status}). "
                "Owner should decide whether to merge, supersede, "
                "or accept as a sibling."
            ),
            conflict_with=(row.id,),
        )

    numeric_conflict = _first_numeric_fact_conflict(
        title=candidate.title,
        content=candidate.content,
        existing=existing,
    )
    if numeric_conflict is not None:
        row, new_numbers, existing_numbers = numeric_conflict
        return MembraneReview(
            action="request_review",
            reason="numeric_claim_conflict",
            diff_summary=(
                "Candidate appears to cover the same KB topic as "
                f"'{row.title}' (id={row.id}) but carries different "
                f"numeric claims: candidate={sorted(new_numbers)}, "
                f"existing={sorted(existing_numbers)}. Owner should "
                "decide whether this supersedes the older entry, is a "
                "separate scenario, or should be rejected."
            ),
            conflict_with=(row.id,),
        )

    # Slice M1 — semantic reviewer as the *last* gate before
    # auto_merge. Spec §7: only call the LLM when the candidate is
    # otherwise headed for auto_merge AND we have something for it
    # to review. If retrieval / decisions are empty there's nothing
    # the agent can reason against; skip the round-trip.
    if context.agent_reviewer is not None:
        agent_action = await _agent_review_kb_candidate(
            candidate=candidate, existing=existing, context=context
        )
        if agent_action is not None:
            return agent_action

    return MembraneReview(
        action="auto_merge",
        reason="no_conflicts",
    )


async def _agent_review_kb_candidate(
    *,
    candidate: MembraneCandidate,
    existing: list[KbItemRow],
    context: MembraneContext,
) -> MembraneReview | None:
    """Build a KB review packet (spec §5.2) and run the Membrane
    Agent. Returns a MembraneReview that overrides auto_merge when
    the agent flags a conflict, or `None` when the agent permits
    auto_merge so the caller's existing flow continues.

    Failure modes return MembraneReview directly with
    `request_review` (fail-closed) — never raise into the caller.
    """
    assert context.agent_reviewer is not None
    builder = context.kb_pretext_builder or build_kb_review_packet
    try:
        packet = await builder(
            candidate=candidate, existing=existing, context=context
        )
    except Exception:
        # M1.1 — fail closed. Pre-M1.1 this returned None (let
        # auto_merge through), which meant a pretext-builder bug
        # would let unreviewed candidates into shared memory
        # silently. The whole point of the agent gate is to be
        # the safety boundary; a bug in OUR code shouldn't open
        # that boundary.
        _log.exception(
            "membrane.agent_review.pretext_failed",
            extra={"project_id": candidate.project_id},
        )
        return MembraneReview(
            action="request_review",
            reason="agent_review_pretext_failed",
            diff_summary=(
                "Membrane semantic-review pretext failed to build. "
                "Holding candidate for owner review as a safety default."
            ),
        )

    # Skip when nothing to review against — spec §7 explicitly
    # avoids burning LLM calls for low-risk candidates.
    if not packet["retrieved_context"] and not packet["recent_decisions"]:
        return None

    try:
        outcome = await context.agent_reviewer.review_candidate(packet)
    except Exception:
        # Network / unexpected agent failure: fail-closed to
        # request_review with a generic reason.
        _log.exception(
            "membrane.agent_review.call_failed",
            extra={"project_id": candidate.project_id},
        )
        return MembraneReview(
            action="request_review",
            reason="agent_review_call_failed",
            diff_summary=(
                "Membrane semantic reviewer failed to run. "
                "Holding candidate for owner review as a safety default."
            ),
        )

    review = outcome.review
    if review.action == "auto_merge":
        return None  # let the caller's auto_merge path proceed

    # Map agent's ref strings (e.g. "kb:abc") back to bare ids for
    # the public MembraneReview shape. Agent already filtered to
    # pretext-only refs.
    conflict_ids = tuple(
        ref.partition(":")[2]
        for ref in review.conflict_with
        if ref.partition(":")[2]
    )
    return MembraneReview(
        action=review.action,
        reason=review.reason,
        diff_summary=review.diff_summary,
        clarify_question=review.clarify_question,
        conflict_with=conflict_ids,
        warnings=tuple(review.warnings),
    )


async def audit_canonical_kb(
    project_id: str,
    *,
    context: MembraneContext,
    max_rows: int = 50,
) -> list[dict[str, Any]]:
    """Scan canonical group KB rows in `project_id` for pairwise
    semantic conflicts. Read-only; returns a list of findings, each
    a dict shaped:

        {
          "row_id": "<kb id treated as candidate>",
          "row_title": "...",
          "agent_action": "request_review" | "request_clarification" | "reject",
          "reason": "...",
          "diff_summary": "...",
          "conflict_with": ["<kb id>", ...],
          "warnings": [...],
        }

    Per spec §M2: produces a report; never auto-demotes. The owner
    decides what to do with each finding (typically: archive the
    stale row via the existing M1.2 archive flow). The agent path
    is the same one M1 uses for new writes — the audit is just
    running it against rows that landed before M1 shipped.

    Skip rules:
      * agent reviewer not configured → empty list (caller decides
        whether to surface "audit unavailable")
      * row count < 2 → empty list (nothing to compare against)
      * per-row pretext empty after topic-overlap filtering → skip
        that row (no signal to review against)

    `max_rows` caps the iteration to keep the LLM cost bounded. The
    rows are taken in created_at-desc order so a partial audit
    prefers the most-recent rows.
    """
    if context.agent_reviewer is None:
        return []

    async with session_scope(context.sessionmaker) as session:
        rows = await KbItemRepository(session).list_group_for_project(
            project_id=project_id, limit=max_rows * 2
        )

    canonical = [r for r in rows if is_canonical_kb_row(r)]
    if len(canonical) < 2:
        return []
    canonical = canonical[:max_rows]

    findings: list[dict[str, Any]] = []
    for row in canonical:
        # Treat this row AS the candidate; the others are the
        # "existing" pretext. The agent's logic for new writes
        # carries over unchanged.
        synthetic_candidate = MembraneCandidate(
            kind="kb_item_group",
            project_id=project_id,
            proposer_user_id=row.owner_user_id or "",
            title=row.title or "",
            content=row.content_md or "",
            metadata={
                "source": "kb_audit",
                "audit_row_id": row.id,
            },
        )
        others = [r for r in canonical if r.id != row.id]
        builder = context.kb_pretext_builder or build_kb_review_packet
        try:
            packet = await builder(
                candidate=synthetic_candidate,
                existing=others,
                context=context,
            )
        except Exception:
            _log.exception(
                "membrane.audit.pretext_failed",
                extra={"project_id": project_id, "row_id": row.id},
            )
            continue

        # Same §7 gate as the live path: skip the LLM when nothing
        # to review against.
        if not packet["retrieved_context"] and not packet[
            "recent_decisions"
        ]:
            continue

        try:
            outcome = await context.agent_reviewer.review_candidate(packet)
        except Exception:
            _log.exception(
                "membrane.audit.agent_call_failed",
                extra={"project_id": project_id, "row_id": row.id},
            )
            continue

        review = outcome.review
        if review.action == "auto_merge":
            continue  # no conflict; nothing to surface

        conflict_ids = [
            ref.partition(":")[2]
            for ref in review.conflict_with
            if ref.partition(":")[2]
        ]
        findings.append(
            {
                "row_id": row.id,
                "row_title": row.title or "",
                "agent_action": review.action,
                "reason": review.reason,
                "diff_summary": review.diff_summary,
                "conflict_with": conflict_ids,
                "warnings": list(review.warnings),
            }
        )
    return findings


__all__ = [
    "audit_canonical_kb",
    "review_kb_item_group",
]
