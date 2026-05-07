"""task_promote policy.

Symmetric to kb_policy but the corpus is plan-scope tasks attached
to the project's latest requirement, not group KB items.

Action vocabulary:
  auto_merge | request_review | request_clarification | reject

Failure mode: same as KB — fail-CLOSED to `request_review`. Plan
mutations are load-bearing for downstream routing / SLA, so a
pretext or agent-call bug must not let unreviewed tasks through.
"""
from __future__ import annotations

import logging
from typing import Any

from workgraph_persistence import (
    AssignmentRepository,
    PlanRepository,
    ProjectMemberRepository,
    RequirementRepository,
    session_scope,
)

from .base import MembraneCandidate, MembraneContext, MembraneReview
from .deterministic import _normalize_title
from .pretext import build_task_review_packet

_log = logging.getLogger("workgraph.api.membrane.task_policy")


async def review_task_promote(
    candidate: MembraneCandidate,
    context: MembraneContext,
) -> MembraneReview:
    """Pre-promote checks for a personal-task → plan candidate.

    Stage T+1 of the membrane reorg. Symmetric to
    `review_kb_item_group` but the corpus is plan-scope tasks
    attached to the project's latest requirement, not group KB
    items. The crowd-wiki failure mode applies to plans too:
    two members each create their own "implement OAuth" task
    without realizing the other one already shipped.

    Checks v1:
      1. Title near-duplicate against ACTIVE plan tasks → blocking
         (request_review). Owner decides merge/supersede/sibling.
      2. Title match against done/cancelled siblings → advisory
         warning. Doesn't block — the proposer may legitimately be
         re-doing closed work — but surfaces it so they don't miss
         that prior work exists.
      3. Estimate-budget overflow vs requirement.budget_hours →
         advisory warning. Reads candidate.metadata['estimate_hours']
         as the proposed estimate; sums existing plan estimates;
         flags if the addition would push past budget.
      4. Stage 6 conflict-rule scan → advisory warnings about
         pre-existing graph-integrity issues (orphan tasks with
         downstream deps). Surfaces "the plan already has staffing
         gaps you're adding to" without blocking.

    Not covered (deferred):
      - Assignee coverage (needs project-member role-skill mapping;
        ProjectMemberRow.role is admin-scope, not functional).
    """
    normalized_new = _normalize_title(candidate.title)
    if not normalized_new:
        return MembraneReview(
            action="auto_merge",
            reason="empty_title_lets_caller_validate",
        )

    async with session_scope(context.sessionmaker) as session:
        req_repo = RequirementRepository(session)
        latest = await req_repo.latest_for_project(candidate.project_id)
        if latest is None:
            return MembraneReview(
                action="auto_merge",
                reason="no_requirement_yet",
            )
        existing = await PlanRepository(session).list_tasks(latest.id)
        req_budget = latest.budget_hours

    warnings: list[str] = []

    # Check 1 + 2: title scan against existing plan tasks.
    active_dup: Any = None
    sibling_done: list[Any] = []
    for row in existing:
        if _normalize_title(row.title) != normalized_new:
            continue
        if row.status in ("cancelled", "done"):
            sibling_done.append(row)
        else:
            active_dup = row
            break  # first active dup wins; no need to keep scanning
    if sibling_done:
        warnings.append(
            "A "
            + ("done" if any(s.status == "done" for s in sibling_done) else "cancelled")
            + f" plan task with this title exists: '{sibling_done[0].title}' "
            f"(id={sibling_done[0].id}). Confirm you intend to redo the work "
            f"rather than reopen the existing row."
        )

    if active_dup is not None:
        return MembraneReview(
            action="request_review",
            reason="duplicate_title",
            diff_summary=(
                f"An active plan task already has this title: "
                f"'{active_dup.title}' (id={active_dup.id}, "
                f"status={active_dup.status}). Owner should decide "
                "whether to merge into it, supersede it, or accept "
                "as a sibling task."
            ),
            conflict_with=(active_dup.id,),
            warnings=tuple(warnings),
        )

    # Check 3: budget overflow. estimate_hours arrives in metadata
    # because MembraneCandidate doesn't carry typed task fields —
    # the caller (promote endpoint) reads task.estimate_hours and
    # passes it through. Both sides null-safe: skip the check if
    # no budget set OR no estimate provided.
    proposed_estimate = candidate.metadata.get("estimate_hours")
    if (
        req_budget is not None
        and isinstance(proposed_estimate, int)
        and proposed_estimate > 0
    ):
        current_total = sum(
            (t.estimate_hours or 0)
            for t in existing
            if t.status not in ("cancelled",)
        )
        if current_total + proposed_estimate > req_budget:
            warnings.append(
                f"Adding this task ({proposed_estimate}h) would push "
                f"the requirement total ({current_total}h) over the "
                f"declared budget ({req_budget}h)."
            )

    # Check 4: Stage 6 — surface pre-existing orphan-with-downstream
    # tasks. Mirrors the missing_owner conflict rule but read-only
    # (advisory, not a block). Cheap because we already have the
    # task list in memory.
    downstream_count: dict[str, int] = {}
    async with session_scope(context.sessionmaker) as session:
        deps = await PlanRepository(session).list_dependencies(latest.id)
        for d in deps:
            downstream_count[d.from_task_id] = (
                downstream_count.get(d.from_task_id, 0) + 1
            )
        assigned_task_ids: set[str] = set()
        for a in await AssignmentRepository(session).list_for_project(
            candidate.project_id
        ):
            if getattr(a, "active", True) and a.task_id:
                assigned_task_ids.add(a.task_id)
    orphans_with_downstream = [
        t
        for t in existing
        if (t.assignee_role or "unknown") != "unknown"
        and t.status not in ("done", "cancelled")
        and t.id not in assigned_task_ids
        and downstream_count.get(t.id, 0) > 0
    ]
    if orphans_with_downstream:
        warnings.append(
            f"The plan already has {len(orphans_with_downstream)} "
            "unstaffed task(s) blocking downstream work. Promoting "
            "this task adds to the queue without addressing the gap."
        )

    # Check 5: assignee-coverage. The candidate carries a proposed
    # role (threaded via metadata['assignee_role']); if no project
    # member has that role tag in their skill_tags list, surface a
    # warning. 'unknown' role skips the check (no commitment was
    # made about who'd own it). Schema added in migration 0026.
    proposed_role = candidate.metadata.get("assignee_role")
    if (
        isinstance(proposed_role, str)
        and proposed_role
        and proposed_role != "unknown"
    ):
        async with session_scope(context.sessionmaker) as session:
            members = await ProjectMemberRepository(session).list_for_project(
                candidate.project_id
            )
        covered = any(
            proposed_role in (m.skill_tags or []) for m in members
        )
        if not covered:
            warnings.append(
                f"No project member has declared the '{proposed_role}' "
                "skill tag. Promoting this task may leave it without "
                "an owner — consider tagging a member or routing to "
                "an external collaborator."
            )

    # Slice M3 — semantic reviewer as the *last* gate before
    # auto_merge. Same pattern as M1 for KB: the deterministic
    # checks above already caught duplicate-title / budget overflow
    # / orphan-with-downstream / role-coverage. The agent is here
    # to catch what those checks can't see — semantic duplicates
    # under a different title, contradictions with recent decisions,
    # reopening intentionally-closed work.
    #
    # Per spec §7: only call the LLM when the candidate is
    # otherwise headed for auto_merge AND the pretext has
    # something for the agent to reason against. If both
    # related_tasks and recent_decisions are empty there's
    # nothing for the agent to compare to; skip the round-trip.
    if context.agent_reviewer is not None:
        agent_action = await _agent_review_task_candidate(
            candidate=candidate,
            existing=existing,
            requirement=latest,
            deterministic_warnings=warnings,
            context=context,
        )
        if agent_action is not None:
            return agent_action

    return MembraneReview(
        action="auto_merge",
        reason="no_conflicts",
        warnings=tuple(warnings),
    )


async def _agent_review_task_candidate(
    *,
    candidate: MembraneCandidate,
    existing: list[Any],
    requirement: Any,
    deterministic_warnings: list[str],
    context: MembraneContext,
) -> MembraneReview | None:
    """Build a task review packet (spec §5.3) and run the Membrane
    Agent. Returns a MembraneReview that overrides auto_merge when
    the agent flags a conflict, or `None` when the agent permits
    auto_merge so the caller's existing flow (with its accumulated
    deterministic warnings) continues.

    Failure modes return MembraneReview directly with
    `request_review` (fail-closed) — never raise into the caller.
    """
    assert context.agent_reviewer is not None
    builder = context.task_pretext_builder or build_task_review_packet
    try:
        packet = await builder(
            candidate=candidate,
            existing=existing,
            requirement=requirement,
            deterministic_warnings=deterministic_warnings,
            context=context,
        )
    except Exception:
        _log.exception(
            "membrane.agent_review.task_pretext_failed",
            extra={"project_id": candidate.project_id},
        )
        return MembraneReview(
            action="request_review",
            reason="agent_review_pretext_failed",
            diff_summary=(
                "Membrane semantic-review pretext failed to build. "
                "Holding candidate for owner review as a safety default."
            ),
            warnings=tuple(deterministic_warnings),
        )

    # Skip when nothing to review against — same gate as KB.
    if not packet["related_tasks"] and not packet["recent_decisions"]:
        return None

    try:
        outcome = await context.agent_reviewer.review_candidate(packet)
    except Exception:
        _log.exception(
            "membrane.agent_review.task_call_failed",
            extra={"project_id": candidate.project_id},
        )
        return MembraneReview(
            action="request_review",
            reason="agent_review_call_failed",
            diff_summary=(
                "Membrane semantic reviewer failed to run. "
                "Holding candidate for owner review as a safety default."
            ),
            warnings=tuple(deterministic_warnings),
        )

    review = outcome.review
    if review.action == "auto_merge":
        return None  # let the caller's auto_merge path proceed

    # Map agent's ref strings back to bare ids for the public shape.
    # Mix in the deterministic warnings the agent didn't see so the
    # caller's eventual review row carries both signals.
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
    "review_task_promote",
]
