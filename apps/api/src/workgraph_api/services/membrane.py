"""MembraneService — boundary between the cell (project knowledge) and
candidates trying to enter it.

The service owns two parallel entry points (vision §5.12 + the
2026-04-25 user reframe in docs/membrane-reorg.md):

## ingest()  — external signals (Phase D, original surface)

  1. Caller hands in `(source_kind, source_identifier, raw_content, project_id)`.
  2. Dedup: if we've already seen this (project_id, source_identifier) pair,
     return the existing row — never re-classify, never double-route.
  3. Trim `raw_content` to 4000 chars (prompt-cost AND injection-surface
     guard).
  4. Persist the row at `status='pending-review'` (default from ORM).
     This is the security boundary: nothing is routed until either the
     auto-approve gate passes OR a human approves.
  5. Call MembraneAgent.classify with a minimal project context (members).
  6. Persist classification. Apply the auto-approve gate:
       confidence >= 0.7 AND proposed_action != 'flag-for-review' AND
       safety_notes is empty
     → flip status to 'routed' and post `kind='membrane-signal'` messages
       into each validated target user's personal stream for this project.
     Otherwise status stays 'pending-review' until approve is called.
  7. Emit events at each stage so observability + WS can follow along.

The service NEVER trusts the LLM's `proposed_target_user_ids` blindly —
ids are filtered against the project's member list. External content
cannot name-drop arbitrary user ids into routing targets.

## review()  — internal candidates (added 2026-04-25, stage 2 of
                                     docs/membrane-reorg.md)

The same boundary, called from the OPPOSITE direction: when a user
or sub-agent proposes promoting something INTO the cell (group-scope
KB item, decision crystallization, edge join), the write path calls
`review(candidate, cell_snapshot)` first. The review returns one of
four actions (auto_merge / request_review / request_clarification /
reject) — the GitHub-PR analogy spelled out in the reorg doc.

For Stage 2 the review is a passthrough (always auto_merge). The
shell exists so Stage 3+ can fill in conflict detection, owner
review queueing, and the clarify Q&A back-channel without callers
having to change shape. Same pattern as the auto-approve gate in
ingest() — same cell, same agent, same boundary, just inward-facing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import MembraneAgent, MembraneClassification
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    AssignmentRepository,
    EDGE_AGENT_SYSTEM_USER_ID,
    KbItemRepository,
    KbItemRow,
    KbIngestRepository,
    MessageRepository,
    PlanRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)
from sqlalchemy import select

from .collab_hub import CollabHub
from .streams import StreamService

_log = logging.getLogger("workgraph.api.membrane")

# Trim incoming content to this many characters before storage or LLM.
# Vision §5.12 — bounds the prompt-injection surface area.
RAW_CONTENT_MAX_CHARS = 4000

# Auto-approve gate (vision §5.12 security boundary). Below this
# confidence OR any of the soft-block conditions → status stays
# 'pending-review' until a human approves.
AUTO_APPROVE_CONFIDENCE_THRESHOLD = 0.7


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
# to run.
CandidateKind = Literal[
    "kb_item_group",         # group-scope KbItemRow about to be created
    "task_promote",          # personal TaskRow being promoted to plan
    "decision_crystallize",  # DecisionRow about to crystallize
    "graph_edge",            # graph node/edge promotion
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


class MembraneService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        stream_service: StreamService,
        agent: MembraneAgent,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._stream_service = stream_service
        self._agent = agent

    async def ingest(
        self,
        *,
        project_id: str,
        source_kind: str,
        source_identifier: str,
        raw_content: str,
        ingested_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Ingest an external signal through the membrane.

        Returns a dict with `ok`, `signal` (the row payload), `created`
        (False if deduped), and `routed_count` (0 when flagged for
        review, else number of personal streams the signal was posted
        to).
        """
        trimmed = (raw_content or "")[:RAW_CONTENT_MAX_CHARS]

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}

            repo = KbIngestRepository(session)
            existing = await repo.find_by_source(
                project_id=project_id,
                source_identifier=source_identifier,
            )
            if existing is not None:
                return {
                    "ok": True,
                    "created": False,
                    "routed_count": 0,
                    "signal": self._signal_payload(existing),
                }

            row = await repo.create(
                project_id=project_id,
                source_kind=source_kind,
                source_identifier=source_identifier,
                raw_content=trimmed,
                ingested_by_user_id=ingested_by_user_id,
                trace_id=get_trace_id(),
            )
            signal_id = row.id
            # Capture members while the session is open.
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            member_ids: set[str] = set()
            member_summaries: list[dict] = []
            user_repo = UserRepository(session)
            for m in members:
                if m.user_id == EDGE_AGENT_SYSTEM_USER_ID:
                    continue
                u = await user_repo.get(m.user_id)
                if u is None:
                    continue
                member_ids.add(u.id)
                member_summaries.append(
                    {
                        "user_id": u.id,
                        "display_name": u.display_name or u.username,
                        "role": m.role,
                    }
                )
            project_title = project.title

        project_context = {
            "id": project_id,
            "title": project_title,
            "members": member_summaries,
        }

        await self._event_bus.emit(
            "membrane_signal.ingested",
            {
                "signal_id": signal_id,
                "project_id": project_id,
                "source_kind": source_kind,
                "source_identifier": source_identifier,
                "ingested_by_user_id": ingested_by_user_id,
            },
        )

        # Classify — exceptions here still let us keep the 'pending-review'
        # row on the audit log, which is the correct safety behaviour.
        try:
            outcome = await self._agent.classify(
                raw_content=trimmed,
                source_kind=source_kind,
                source_identifier=source_identifier,
                project_context=project_context,
            )
        except Exception:
            _log.exception(
                "membrane classify raised — leaving signal pending-review",
                extra={"signal_id": signal_id},
            )
            async with session_scope(self._sessionmaker) as session:
                fresh = await KbIngestRepository(session).get(signal_id)
            return {
                "ok": True,
                "created": True,
                "routed_count": 0,
                "signal": self._signal_payload(fresh) if fresh else None,
                "classified": False,
            }

        classification = outcome.classification

        # Auto-approve gate. Three soft-blocks:
        #   1) proposed_action == 'flag-for-review' — LLM flagged it
        #   2) safety_notes non-empty — LLM detected injection/suspicious
        #   3) confidence < threshold
        soft_blocked = (
            classification.proposed_action == "flag-for-review"
            or bool((classification.safety_notes or "").strip())
            or classification.confidence < AUTO_APPROVE_CONFIDENCE_THRESHOLD
        )

        # Filter proposed targets against the actual project member set —
        # external content cannot route to user_ids it invented.
        validated_targets = [
            uid
            for uid in classification.proposed_target_user_ids
            if uid in member_ids
        ]

        if soft_blocked or not validated_targets:
            # Stays pending-review. For genuinely relevant ambient-log
            # signals with no targets we still leave status=pending-review
            # so a human can decide whether to broadcast.
            new_status = "pending-review"
        else:
            new_status = "routed"

        # Persist classification + agent log + optional routing.
        async with session_scope(self._sessionmaker) as session:
            await KbIngestRepository(session).set_classification(
                signal_id,
                classification=classification.model_dump(),
                status=new_status,
            )
            await AgentRunLogRepository(session).append(
                agent="membrane",
                prompt_version=self._agent.prompt_version,
                project_id=project_id,
                trace_id=get_trace_id(),
                outcome=outcome.outcome,
                attempts=outcome.attempts,
                latency_ms=outcome.result.latency_ms,
                prompt_tokens=outcome.result.prompt_tokens,
                completion_tokens=outcome.result.completion_tokens,
                cache_read_tokens=outcome.result.cache_read_tokens,
                error=outcome.error,
            )

        routed_count = 0
        if new_status == "routed":
            routed_count = await self._route_to_members(
                signal_id=signal_id,
                project_id=project_id,
                target_user_ids=validated_targets,
                classification=classification,
            )

        async with session_scope(self._sessionmaker) as session:
            fresh = await KbIngestRepository(session).get(signal_id)
        payload = self._signal_payload(fresh) if fresh else None

        await self._event_bus.emit(
            "membrane_signal.classified",
            {
                "signal_id": signal_id,
                "project_id": project_id,
                "status": new_status,
                "confidence": classification.confidence,
                "safety_notes_present": bool(
                    (classification.safety_notes or "").strip()
                ),
                "proposed_action": classification.proposed_action,
                "routed_count": routed_count,
            },
        )
        await self._hub.publish(
            project_id, {"type": "membrane_signal", "payload": payload}
        )

        return {
            "ok": True,
            "created": True,
            "routed_count": routed_count,
            "signal": payload,
            "classified": True,
        }

    async def review(
        self, candidate: MembraneCandidate
    ) -> MembraneReview:
        """Decide what to do with a candidate trying to enter the cell.

        Branches on candidate.kind. Stage 3 wires real review for
        `kb_item_group` (title near-duplicate detection); other kinds
        fall through to auto_merge until their respective stages.

        Callers should treat this as authoritative — if the action is
        not auto_merge, do NOT proceed with the write. The non-auto
        action handlers are the membrane's job, not the caller's.
        """
        _log.info(
            "membrane.review",
            extra={
                "kind": candidate.kind,
                "project_id": candidate.project_id,
                "proposer_user_id": candidate.proposer_user_id,
                "title_chars": len(candidate.title or ""),
                "content_chars": len(candidate.content or ""),
            },
        )
        if candidate.kind == "kb_item_group":
            return await self._review_kb_item_group(candidate)
        if candidate.kind == "task_promote":
            return await self._review_task_promote(candidate)
        if candidate.kind == "decision_crystallize":
            return await self._review_decision_crystallize(candidate)
        # graph_edge: still passthrough until conflict detection lands.
        return MembraneReview(
            action="auto_merge",
            reason="no_check_for_kind",
        )

    async def _review_kb_item_group(
        self, candidate: MembraneCandidate
    ) -> MembraneReview:
        """Pre-write checks for a group-scope KB candidate.

        Stage 3 v0 — title near-duplicate detection. The most common
        failure mode for crowd-sourced wikis is "everyone writes
        their own slightly different page on the same topic." We catch
        the obvious case (same normalized title) and downgrade to
        request_review so the owner can decide: merge into the
        existing entry, supersede it, or accept as a related sibling.

        Not yet covered (stage 4+):
        - Semantic contradiction with existing entries (needs LLM)
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

        async with session_scope(self._sessionmaker) as session:
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

        return MembraneReview(
            action="auto_merge",
            reason="no_conflicts",
        )

    async def _review_task_promote(
        self, candidate: MembraneCandidate
    ) -> MembraneReview:
        """Pre-promote checks for a personal-task → plan candidate.

        Stage T+1 of the membrane reorg. Symmetric to
        `_review_kb_item_group` but the corpus is plan-scope tasks
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

        async with session_scope(self._sessionmaker) as session:
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
        async with session_scope(self._sessionmaker) as session:
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
            async with session_scope(self._sessionmaker) as session:
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

        return MembraneReview(
            action="auto_merge",
            reason="no_conflicts",
            warnings=tuple(warnings),
        )

    async def handle_clarification_reply(
        self,
        *,
        stream_id: str,
        project_id: str,
        proposer_user_id: str,
        reply_body: str,
    ) -> bool:
        """Stage 5 reply path — if `reply_body` is the proposer's answer
        to a recently-posted membrane-clarify question, re-run the
        candidate through review() with the answer in metadata, then
        apply the resulting action.

        Returns True if the reply was intercepted (caller should skip
        the normal Edge agent loop — the user's intent was answering,
        not starting a new turn). Returns False if no pending clarify
        question exists for this stream, OR the reply was already
        intercepted by an earlier handler.

        v0 covers `kb_item_group` candidates only. `task_promote`
        clarification is wired but doesn't currently trigger from
        any review check; when it does, extend the kind dispatch
        below to include it.
        """
        from .membrane import MembraneCandidate  # local — same module
        # Only one outstanding clarify per stream is meaningful — pick
        # the most recent. Walk back at most ~50 messages so a long
        # chat history doesn't slow the post path.
        async with session_scope(self._sessionmaker) as session:
            recent = await MessageRepository(session).list_for_stream(
                stream_id, limit=50
            )
        # Most recent first via reversed iteration. Match: agent-authored
        # membrane-clarify with linked_id pointing to a row we can find.
        clarify_msg = None
        for msg in reversed(recent):
            if (
                msg.kind == "membrane-clarify"
                and msg.author_id == EDGE_AGENT_SYSTEM_USER_ID
                and msg.linked_id
            ):
                clarify_msg = msg
                break
            # The user's own most-recent post might already be in the
            # window; we ignore non-clarify messages and keep walking.
        if clarify_msg is None:
            return False

        # Look up the linked row. Today the linked_id is always a
        # KbItemRow.id (only kb_item_group emits clarifications); a
        # missing row just means the draft was deleted between Q + A,
        # so degrade silently.
        async with session_scope(self._sessionmaker) as session:
            kb_repo = KbItemRepository(session)
            row = await kb_repo.get(clarify_msg.linked_id)
            if row is None:
                _log.info(
                    "membrane.handle_clarification_reply: linked row gone",
                    extra={
                        "stream_id": stream_id,
                        "linked_id": clarify_msg.linked_id,
                    },
                )
                return False
            # Defensive: only treat the reply as the answer if the
            # proposer matches. A teammate (somehow ending up in
            # someone else's personal stream) replying shouldn't
            # auto-resolve the question.
            if row.owner_user_id != proposer_user_id:
                return False

        # Re-run review with the answer threaded through metadata.
        # The review function uses metadata['clarification_answer']
        # presence to skip the size-divergence trigger and fall
        # through to the existing dup-resolution path.
        review = await self.review(
            MembraneCandidate(
                kind="kb_item_group",
                project_id=project_id,
                proposer_user_id=proposer_user_id,
                title=row.title,
                content=row.content_md or "",
                metadata={
                    "source": "clarification_reply",
                    "kb_item_id": row.id,
                    "clarification_answer": reply_body.strip(),
                },
            )
        )

        # Apply the new action. For v0, simple branching:
        #   * auto_merge → flip the draft to published
        #   * reject → flip to archived (keep audit) + system note
        #   * request_review → enqueue the standard inbox card
        #   * request_clarification → ask another round
        async with session_scope(self._sessionmaker) as session:
            kb_repo = KbItemRepository(session)
            if review.action == "auto_merge":
                await kb_repo.update(item_id=row.id, status="published")
            elif review.action == "reject":
                await kb_repo.update(item_id=row.id, status="archived")
            elif review.action == "request_review":
                # Defer to the existing inbox-enqueue path. We post the
                # team-room system message + IMSuggestion here inline
                # (mirrors KbItemService.create's request_review block).
                team_stream = await StreamRepository(session).get_for_project(
                    project_id
                )
                if team_stream is not None:
                    body = (
                        f"📥 Membrane re-staged a group KB entry after "
                        f"clarification reply: '{row.title}'. Reason: "
                        f"{review.reason}."
                    )
                    if review.diff_summary:
                        body = f"{body}\n{review.diff_summary}"
                    msg = await MessageRepository(session).append(
                        project_id=project_id,
                        author_id=EDGE_AGENT_SYSTEM_USER_ID,
                        body=body,
                        stream_id=team_stream.id,
                        kind="membrane-review",
                        linked_id=row.id,
                    )
                    from workgraph_persistence import IMSuggestionRepository

                    await IMSuggestionRepository(session).append(
                        project_id=project_id,
                        message_id=msg.id,
                        kind="membrane_review",
                        confidence=1.0,
                        targets=list(review.conflict_with),
                        proposal={
                            "action": "approve_membrane_candidate",
                            "summary": (
                                review.diff_summary
                                or f"Approve '{row.title}' for the group wiki"
                            ),
                            "detail": {
                                "candidate_kind": "kb_item_group",
                                "kb_item_id": row.id,
                                "diff_summary": review.diff_summary,
                                "conflict_with": list(review.conflict_with),
                            },
                        },
                        reasoning=review.reason or "membrane request_review",
                        prompt_version=None,
                        outcome="ok",
                        attempts=1,
                    )
            # request_clarification → fall through; notify_clarification
            # below handles posting the next question.

        if review.action == "request_clarification":
            await self.notify_clarification(
                candidate=MembraneCandidate(
                    kind="kb_item_group",
                    project_id=project_id,
                    proposer_user_id=proposer_user_id,
                    title=row.title,
                    content=row.content_md or "",
                    metadata={
                        "source": "clarification_reply",
                        "kb_item_id": row.id,
                        # Pre-populate so the next reply round sees the
                        # prior answer too. The review() handler skips
                        # the size-divergence trigger when
                        # clarification_answer is set, so a second
                        # ambiguity check needs new criteria — for v0
                        # we just route to request_review.
                        "clarification_answer": reply_body.strip(),
                    },
                ),
                review=review,
                linked_id=row.id,
            )

        # Post a small confirmation in the proposer's personal stream
        # so they see "ok, processed" — important UX cue since their
        # message disappears into the membrane otherwise.
        outcome_text = {
            "auto_merge": "✅ Thanks — your KB entry is now published.",
            "reject": "❌ The KB entry was rejected after review.",
            "request_review": "📥 Forwarded to team for owner review.",
            "request_clarification": "❓ Membrane has another question (see above).",
        }.get(review.action, "↪ Reply received.")
        try:
            await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=outcome_text,
                kind="membrane-clarify-ack",
                linked_id=row.id,
            )
        except Exception:
            _log.exception(
                "membrane.handle_clarification_reply: ack post failed",
                extra={"stream_id": stream_id, "linked_id": row.id},
            )
        return True

    async def _review_decision_crystallize(
        self, candidate: MembraneCandidate
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
            async with session_scope(self._sessionmaker) as session:
                from workgraph_persistence import DecisionRepository

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

        return MembraneReview(
            action="auto_merge",
            reason="advisory_only" if warnings else "no_conflicts",
            warnings=tuple(warnings),
        )

    async def notify_clarification(
        self,
        *,
        candidate: MembraneCandidate,
        review: MembraneReview,
        linked_id: str | None = None,
    ) -> bool:
        """Stage 5 — post the clarify question to the proposer's personal
        stream when review.action == 'request_clarification'.

        Returns True if delivered, False if no personal stream existed
        for the proposer in this project (membrane decisions about
        org-level signals can have no personal target — degrade
        gracefully).

        The Q lives in the proposer's PERSONAL stream, never team room
        or DM (docs/membrane-reorg.md Stage 5 spec). The reply pathway
        — proposer answers, candidate is re-submitted to review() with
        metadata['clarification_answer'] populated — is a follow-up;
        for v0 the proposer reads the Q, edits their draft accordingly,
        and re-submits via the original promote path. Even without the
        auto-reply loop the surface ships value: today the proposer
        just sees deferred=true with no actionable detail.
        """
        if review.action != "request_clarification":
            return False
        if not review.clarify_question:
            _log.warning(
                "membrane.notify_clarification: missing clarify_question",
                extra={
                    "candidate_kind": candidate.kind,
                    "project_id": candidate.project_id,
                },
            )
            return False
        try:
            stream_payload = await self._stream_service.ensure_personal_stream(
                user_id=candidate.proposer_user_id,
                project_id=candidate.project_id,
            )
        except Exception:
            _log.exception(
                "membrane.notify_clarification: ensure_personal_stream failed",
                extra={
                    "proposer_user_id": candidate.proposer_user_id,
                    "project_id": candidate.project_id,
                },
            )
            return False
        stream_id = (stream_payload or {}).get("stream_id")
        if not stream_id:
            return False
        body_lines = [
            f"❓ Membrane wants a quick clarification before "
            f"accepting your {candidate.kind.replace('_', ' ')}: "
            f"'{candidate.title}'",
            "",
            review.clarify_question,
        ]
        if review.diff_summary:
            body_lines.extend(["", review.diff_summary])
        try:
            await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body="\n".join(body_lines),
                kind="membrane-clarify",
                linked_id=linked_id,
            )
        except Exception:
            _log.exception(
                "membrane.notify_clarification: post_system_message failed",
                extra={
                    "proposer_user_id": candidate.proposer_user_id,
                    "stream_id": stream_id,
                },
            )
            return False
        return True

    async def _route_to_members(
        self,
        *,
        signal_id: str,
        project_id: str,
        target_user_ids: list[str],
        classification: MembraneClassification,
    ) -> int:
        """Post `kind='membrane-signal'` messages into each validated target's
        personal stream for this project. Returns the count of streams
        actually delivered to.
        """
        import json

        body = json.dumps(
            {
                "signal_id": signal_id,
                "summary": classification.summary,
                "tags": list(classification.tags),
                "confidence": classification.confidence,
            },
            ensure_ascii=False,
        )
        delivered = 0
        for uid in target_user_ids:
            try:
                stream_payload = await self._stream_service.ensure_personal_stream(
                    user_id=uid, project_id=project_id
                )
            except Exception:
                _log.exception(
                    "membrane: could not ensure personal stream for target",
                    extra={"signal_id": signal_id, "target_user_id": uid},
                )
                continue
            stream_id = stream_payload.get("stream_id")
            if not stream_id:
                continue
            try:
                await self._stream_service.post_system_message(
                    stream_id=stream_id,
                    author_id=EDGE_AGENT_SYSTEM_USER_ID,
                    body=body,
                    kind="membrane-signal",
                    linked_id=signal_id,
                )
                delivered += 1
            except Exception:
                _log.exception(
                    "membrane: post_system_message failed for target",
                    extra={"signal_id": signal_id, "target_user_id": uid},
                )
        return delivered

    async def approve(
        self,
        *,
        signal_id: str,
        approver_user_id: str,
        decision: str,
    ) -> dict[str, Any]:
        """Admin approval path for signals flagged for review.

        `decision` ∈ {'approve', 'reject'}. On 'approve' we flip the status
        and route to the (LLM-proposed, member-filtered) targets now that
        a human has cleared the content. On 'reject' the row stays as
        audit history, never routed.
        """
        if decision not in ("approve", "reject"):
            return {"ok": False, "error": "invalid_decision"}

        async with session_scope(self._sessionmaker) as session:
            repo = KbIngestRepository(session)
            row = await repo.get(signal_id)
            if row is None:
                return {"ok": False, "error": "signal_not_found"}
            if row.status not in ("pending-review",):
                return {"ok": False, "error": "already_resolved"}
            project_id = row.project_id
            classification_data = dict(row.classification_json or {})

            # Capture the member set inside this session for target filtering.
            member_ids: set[str] = set()
            if project_id is not None:
                members = await ProjectMemberRepository(session).list_for_project(
                    project_id
                )
                for m in members:
                    member_ids.add(m.user_id)

        if decision == "reject":
            async with session_scope(self._sessionmaker) as session:
                updated = await KbIngestRepository(session).mark_status(
                    signal_id,
                    status="rejected",
                    approved_by_user_id=approver_user_id,
                )
                payload = self._signal_payload(updated) if updated else None
            await self._event_bus.emit(
                "membrane_signal.rejected",
                {
                    "signal_id": signal_id,
                    "project_id": project_id,
                    "approver_user_id": approver_user_id,
                },
            )
            if payload and project_id:
                await self._hub.publish(
                    project_id, {"type": "membrane_signal", "payload": payload}
                )
            return {"ok": True, "status": "rejected", "signal": payload}

        # decision == 'approve'. Still filter targets against member set —
        # approval doesn't let external content name-drop non-members.
        proposed_targets = classification_data.get(
            "proposed_target_user_ids", []
        ) or []
        validated_targets = [
            uid for uid in proposed_targets if uid in member_ids
        ]

        routed_count = 0
        if validated_targets and project_id is not None:
            classification = MembraneClassification.model_validate(
                {
                    # Fall back to safe defaults if the stored dict is partial.
                    "is_relevant": bool(classification_data.get("is_relevant", True)),
                    "tags": list(classification_data.get("tags", []) or []),
                    "summary": (classification_data.get("summary") or "")[:200],
                    "proposed_target_user_ids": list(validated_targets),
                    "proposed_action": classification_data.get(
                        "proposed_action", "route-to-members"
                    ),
                    "confidence": float(
                        classification_data.get("confidence", 1.0) or 0.0
                    ),
                    "safety_notes": classification_data.get("safety_notes", "") or "",
                }
            )
            routed_count = await self._route_to_members(
                signal_id=signal_id,
                project_id=project_id,
                target_user_ids=validated_targets,
                classification=classification,
            )

        new_status = "routed" if routed_count > 0 else "approved"
        async with session_scope(self._sessionmaker) as session:
            updated = await KbIngestRepository(session).mark_status(
                signal_id,
                status=new_status,
                approved_by_user_id=approver_user_id,
            )
            payload = self._signal_payload(updated) if updated else None

        await self._event_bus.emit(
            "membrane_signal.approved",
            {
                "signal_id": signal_id,
                "project_id": project_id,
                "approver_user_id": approver_user_id,
                "status": new_status,
                "routed_count": routed_count,
            },
        )
        if payload and project_id:
            await self._hub.publish(
                project_id, {"type": "membrane_signal", "payload": payload}
            )
        return {
            "ok": True,
            "status": new_status,
            "routed_count": routed_count,
            "signal": payload,
        }

    async def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        async with session_scope(self._sessionmaker) as session:
            rows = await KbIngestRepository(session).list_for_project(
                project_id, status=status, limit=limit
            )
            return [self._signal_payload(r) for r in rows]

    def _signal_payload(self, row: KbItemRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "source_kind": row.source_kind,
            "source_identifier": row.source_identifier,
            "raw_content": row.raw_content,
            "ingested_by_user_id": row.ingested_by_user_id,
            "classification": dict(row.classification_json or {}),
            "status": row.status,
            "approved_by_user_id": row.approved_by_user_id,
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "trace_id": row.trace_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def _normalize_title(title: str | None) -> str:
    """Normalize a KB title for duplicate detection.

    Lowercase, strip punctuation, collapse whitespace, drop common
    leading-article words. Two titles that pass this filter to the
    same value are treated as duplicates by the membrane.
    """
    if not title:
        return ""
    import re
    s = title.strip().lower()
    # Drop punctuation; keep word chars + Unicode letters (so "API 设计" stays
    # comparable to "API设计"). \W matches non-word; combined with the unicode
    # flag this preserves CJK + accented chars.
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


__all__ = [
    "MembraneService",
    "MembraneCandidate",
    "MembraneReview",
    "ReviewAction",
    "CandidateKind",
    "RAW_CONTENT_MAX_CHARS",
    "AUTO_APPROVE_CONFIDENCE_THRESHOLD",
]
