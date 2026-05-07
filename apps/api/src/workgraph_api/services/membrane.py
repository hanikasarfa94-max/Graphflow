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

Phase B of the Architecture Organization Pass moved the per-kind
policy logic, deterministic helpers, and LLM pretext builders into
the `membrane_policies/` package. This module is now a thin
orchestration facade that keeps the existing public import path
stable:

    from workgraph_api.services import MembraneService
    from workgraph_api.services.membrane import MembraneCandidate

The facade dispatches `review()` through a `_policy_registry` dict
keyed on `candidate.kind`, and proxies the manual_* methods directly
to their corresponding policy. ingest() / approve() / list_for_project()
/ handle_clarification_reply() / notify_clarification() / _route_to_members()
stay here — they are service-shaped concerns (event emission, stream
posting, DB lifecycle) rather than per-candidate policy.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import (
    MembraneAgent,
    MembraneAgentReviewer,
    MembraneClassification,
)
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    EDGE_AGENT_SYSTEM_USER_ID,
    IMSuggestionRepository,
    KbIngestRepository,
    KbItemRepository,
    KbItemRow,
    MessageRepository,
    ProjectMemberRepository,
    ProjectRow,
    StreamRepository,
    UserRepository,
    session_scope,
)

from .collab_hub import CollabHub
from .membrane_policies import (
    CandidateKind,
    MembraneCandidate,
    MembraneContext,
    MembranePolicy,
    MembraneReview,
    ReviewAction,
    audit_canonical_kb,
    review_decision_crystallize,
    review_kb_item_group,
    review_manual_invite,
    review_manual_room,
    review_manual_skill_change,
    review_task_promote,
)
from .membrane_policies.pretext import (
    build_decision_review_packet,
    build_kb_review_packet,
    build_task_review_packet,
)
from .streams import StreamService

_log = logging.getLogger("workgraph.api.membrane")

# Trim incoming content to this many characters before storage or LLM.
# Vision §5.12 — bounds the prompt-injection surface area.
RAW_CONTENT_MAX_CHARS = 4000

# Auto-approve gate (vision §5.12 security boundary). Below this
# confidence OR any of the soft-block conditions → status stays
# 'pending-review' until a human approves.
AUTO_APPROVE_CONFIDENCE_THRESHOLD = 0.7


class MembraneService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        stream_service: StreamService,
        agent: MembraneAgent,
        agent_reviewer: MembraneAgentReviewer | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._stream_service = stream_service
        self._agent = agent
        # Slice M1 (docs/membrane-agent-review-spec.md) — optional
        # semantic reviewer that runs *after* deterministic checks
        # when the candidate is headed for auto_merge. Optional so
        # tests can pass None and skip the LLM round-trip; in prod
        # the constructor receives a wired reviewer.
        self._agent_reviewer = agent_reviewer
        # Phase B: per-kind policy dispatch table. Manual_* policies
        # live alongside in the package but use direct call shapes
        # (see review_manual_room / review_manual_skill_change /
        # review_manual_invite below).
        self._policy_registry: dict[CandidateKind, MembranePolicy] = {
            "kb_item_group": review_kb_item_group,
            "task_promote": review_task_promote,
            "decision_crystallize": review_decision_crystallize,
        }

    @property
    def _policy_context(self) -> MembraneContext:
        """Bundle service-level deps every policy needs.

        Constructed per-call so a future swap of `_agent_reviewer`
        (test stub injection) is reflected immediately. The
        `*_pretext_builder` seams point at bound methods on this
        service so tests can monkey-patch
        `service._build_kb_review_packet` and have the policy
        pick it up — preserves the M1.1 fail-closed contract test.
        """
        return MembraneContext(
            sessionmaker=self._sessionmaker,
            agent_reviewer=self._agent_reviewer,
            kb_pretext_builder=self._build_kb_review_packet,
            task_pretext_builder=self._build_task_review_packet,
            decision_pretext_builder=self._build_decision_review_packet,
        )

    # Bridge methods. Each delegates to the package-level builder; the
    # method exists so tests can swap it on a per-instance basis without
    # reaching into the membrane_policies module. Behavior unchanged
    # vs. pre-Phase-B: same args, same return shape.
    async def _build_kb_review_packet(
        self,
        *,
        candidate: MembraneCandidate,
        existing: list[KbItemRow],
        context: MembraneContext | None = None,
    ) -> dict[str, Any]:
        return await build_kb_review_packet(
            candidate=candidate,
            existing=existing,
            context=context or self._policy_context,
        )

    async def _build_task_review_packet(
        self,
        *,
        candidate: MembraneCandidate,
        existing: list[Any],
        requirement: Any,
        deterministic_warnings: list[str],
        context: MembraneContext | None = None,
    ) -> dict[str, Any]:
        return await build_task_review_packet(
            candidate=candidate,
            existing=existing,
            requirement=requirement,
            deterministic_warnings=deterministic_warnings,
            context=context or self._policy_context,
        )

    async def _build_decision_review_packet(
        self,
        *,
        candidate: MembraneCandidate,
        deterministic_warnings: list[str],
        context: MembraneContext | None = None,
    ) -> dict[str, Any]:
        return await build_decision_review_packet(
            candidate=candidate,
            deterministic_warnings=deterministic_warnings,
            context=context or self._policy_context,
        )

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

        Branches on candidate.kind via the policy registry. Unknown
        kinds (e.g. `graph_edge`) fall through to auto_merge —
        symmetric to the original passthrough behavior until a real
        policy lands for that kind.

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
        policy = self._policy_registry.get(candidate.kind)
        if policy is None:
            # graph_edge / manual_project / unhandled kinds: passthrough
            # until their respective stages wire a real policy.
            return MembraneReview(
                action="auto_merge",
                reason="no_check_for_kind",
            )
        return await policy(candidate, self._policy_context)

    async def review_manual_room(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        name: str,
        member_user_ids: list[str],
        owner_ids: list[str],
    ) -> MembraneReview:
        return await review_manual_room(
            project_id=project_id,
            proposer_user_id=proposer_user_id,
            name=name,
            member_user_ids=member_user_ids,
            owner_ids=owner_ids,
            context=self._policy_context,
        )

    async def review_manual_skill_change(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        target_user_id: str,
        new_skill_tags: list[str],
        owner_ids: list[str],
    ) -> MembraneReview:
        return await review_manual_skill_change(
            project_id=project_id,
            proposer_user_id=proposer_user_id,
            target_user_id=target_user_id,
            new_skill_tags=new_skill_tags,
            owner_ids=owner_ids,
            context=self._policy_context,
        )

    async def review_manual_invite(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        target_username: str,
        owner_ids: list[str],
    ) -> MembraneReview:
        return await review_manual_invite(
            project_id=project_id,
            proposer_user_id=proposer_user_id,
            target_username=target_username,
            owner_ids=owner_ids,
            context=self._policy_context,
        )

    async def audit_canonical_kb(
        self, project_id: str, *, max_rows: int = 50
    ) -> list[dict[str, Any]]:
        """Read-only existing-pollution audit (M2). Delegates to the
        kb_policy module; agent gating + skip rules live there."""
        return await audit_canonical_kb(
            project_id, context=self._policy_context, max_rows=max_rows
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


__all__ = [
    "MembraneService",
    "MembraneCandidate",
    "MembraneReview",
    "ReviewAction",
    "CandidateKind",
    "RAW_CONTENT_MAX_CHARS",
    "AUTO_APPROVE_CONFIDENCE_THRESHOLD",
]
