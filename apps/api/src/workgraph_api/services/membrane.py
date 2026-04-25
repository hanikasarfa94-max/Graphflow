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
    EDGE_AGENT_SYSTEM_USER_ID,
    MembraneSignalRepository,
    MembraneSignalRow,
    MessageRepository,
    ProjectMemberRepository,
    ProjectRow,
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
# to run. Stage 2 only wires `kb_item_group` (group-scope KB write);
# other kinds reserved for Stage 3+.
CandidateKind = Literal[
    "kb_item_group",         # group-scope KbItemRow about to be created
    "decision_crystallize",  # DecisionRow about to crystallize
    "graph_edge",             # graph node/edge promotion
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
    """

    action: ReviewAction
    reason: str
    diff_summary: str | None = None
    clarify_question: str | None = None
    conflict_with: tuple[str, ...] = ()


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

            repo = MembraneSignalRepository(session)
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
                fresh = await MembraneSignalRepository(session).get(signal_id)
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
            await MembraneSignalRepository(session).set_classification(
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
            fresh = await MembraneSignalRepository(session).get(signal_id)
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

        Stage 2 shell — always returns auto_merge with a stub reason.
        Stage 3+ will fill in conflict detection (cell snapshot diff,
        owner-review queueing, the clarify Q&A back-channel) without
        the call sites needing to change.

        Callers should treat this as authoritative — if the action is
        not auto_merge, do NOT proceed with the write. The non-auto
        action handlers are the membrane's job, not the caller's.
        """
        # Stage 3 will branch on candidate.kind here. For now, log the
        # candidate so we have observability for what's flowing through
        # the boundary even before any rules fire.
        _log.info(
            "membrane.review (stage 2 passthrough)",
            extra={
                "kind": candidate.kind,
                "project_id": candidate.project_id,
                "proposer_user_id": candidate.proposer_user_id,
                "title_chars": len(candidate.title or ""),
                "content_chars": len(candidate.content or ""),
            },
        )
        return MembraneReview(
            action="auto_merge",
            reason="stage2_passthrough",
        )

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
            repo = MembraneSignalRepository(session)
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
                updated = await MembraneSignalRepository(session).mark_status(
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
            updated = await MembraneSignalRepository(session).mark_status(
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
            rows = await MembraneSignalRepository(session).list_for_project(
                project_id, status=status, limit=limit
            )
            return [self._signal_payload(r) for r in rows]

    def _signal_payload(self, row: MembraneSignalRow) -> dict[str, Any]:
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
