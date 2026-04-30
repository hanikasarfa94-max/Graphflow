"""Room-stream timeline service + WS event helpers.

The room-stream slice ships a single canonical wire shape — the
`RoomTimelineEvent` discriminated union — for both the GET timeline
snapshot and the WS live-update channel. The frontend's
`useRoomTimeline` hook consumes them via one switch over `event.type`,
applying upsert / update / delete uniformly to whichever entity kind
the event references.

Three event types:
  * `timeline.upsert` — full TimelineItem (insert or replace).
  * `timeline.update` — partial patch by (kind, id).
  * `timeline.delete` — drop by (kind, id).

TimelineItem kinds rendered today:
  * `message` — chat turn (text or system).
  * `im_suggestion` — pending / accepted / rejected membrane candidate
    with `status` + `source_message_id`.
  * `decision` — crystallized DecisionRow with `scope_stream_id` so the
    DecisionCard explainer can render the smallest-relevant-vote scope.

Reserved kinds (not rendered this slice; schema-only): `task`, `kb_item`.
The dispatcher accepts them so adding their renderers later is a
frontend-only change.

Service layer wraps a single async DB join across messages /
im_suggestions / decisions for the GET-snapshot path. WS callers use
the per-event helpers (`make_message_event`, etc.) to keep payload
shape consistent across publish sites without coupling those sites to
the timeline service.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRepository,
    MessageRepository,
    MessageRow,
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)


# ---------------------------------------------------------------------------
# Event helpers — used by every publish site (MessageService.post,
# IMService._classify_and_persist, IMService.accept/dismiss/etc.) to
# construct the canonical wire shape.
# ---------------------------------------------------------------------------


def make_message_event(message_row: MessageRow, *, author_username: str | None = None) -> dict[str, Any]:
    """Build a `timeline.upsert` event for a freshly-posted message."""
    return {
        "type": "timeline.upsert",
        "item": {
            "kind": "message",
            "id": message_row.id,
            "stream_id": message_row.stream_id,
            "project_id": message_row.project_id,
            "author_id": message_row.author_id,
            "author_username": author_username,
            "body": message_row.body,
            "kind_message": message_row.kind,
            "linked_id": message_row.linked_id,
            "created_at": (
                message_row.created_at.isoformat()
                if message_row.created_at
                else None
            ),
        },
    }


def make_suggestion_event(suggestion_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a `timeline.upsert` event for an IM suggestion.

    `suggestion_payload` is the dict already returned by
    `IMService._suggestion_payload(row)` — re-using it keeps the wire
    shape consistent with the REST list endpoints.
    """
    return {
        "type": "timeline.upsert",
        "item": {
            "kind": "im_suggestion",
            "id": suggestion_payload["id"],
            **suggestion_payload,
        },
    }


def make_decision_event(decision_payload: dict[str, Any]) -> dict[str, Any]:
    """Build a `timeline.upsert` event for a crystallized decision.

    `decision_payload` is the dict returned by `_decision_payload`
    (which now includes `scope_stream_id` so the room view can render
    the vote-scope explainer).
    """
    return {
        "type": "timeline.upsert",
        "item": {
            "kind": "decision",
            "id": decision_payload["id"],
            **decision_payload,
        },
    }


def make_suggestion_status_update(
    suggestion_id: str, status: str
) -> dict[str, Any]:
    """Partial patch when a suggestion transitions
    pending → accepted / dismissed / countered / escalated.

    Frontend reducer applies the patch via shallow-merge so the
    workbench `Requests` panel filters out the row (status != pending)
    while the inline timeline card flips its visual state.
    """
    return {
        "type": "timeline.update",
        "kind": "im_suggestion",
        "id": suggestion_id,
        "patch": {"status": status},
    }


def is_room_stream(stream) -> bool:
    """True iff `stream` is a 'room' stream — the slice's broadcast gate.

    Project / personal / DM streams keep their existing publish paths
    untouched. Only room streams get the new RoomTimelineEvent fan-out.
    Returns False when the stream is None (e.g. unresolved at call site).
    """
    return stream is not None and stream.type == "room"


# ---------------------------------------------------------------------------
# Service — GET snapshot for the room route page.
# ---------------------------------------------------------------------------


class RoomTimelineService:
    """Joins messages + suggestions + decisions for one room into a
    chronological TimelineItem[] snapshot.

    Backs `GET /api/projects/{pid}/rooms/{rid}/timeline`. Membership-
    gated: caller must be both a project member and a stream member
    of the room. Returns the same wire shape WS upserts publish.
    """

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def get_timeline(
        self,
        *,
        project_id: str,
        stream_id: str,
        viewer_user_id: str,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return ordered TimelineItem[] for the room.

        Error envelope mirrors StreamService.list_messages:
          * 'stream_not_found' — no row with this id
          * 'wrong_project' — stream belongs to a different project
          * 'not_a_member' — caller isn't in the room

        Items returned newest-last (chronological), capped at `limit`
        per kind. The frontend reducer is order-agnostic but newest-
        last is the natural display order.
        """
        async with session_scope(self._sessionmaker) as session:
            stream = await StreamRepository(session).get(stream_id)
            if stream is None:
                return {"ok": False, "error": "stream_not_found"}
            if stream.project_id != project_id:
                return {"ok": False, "error": "wrong_project"}
            if not await StreamMemberRepository(session).is_member(
                stream_id=stream_id, user_id=viewer_user_id
            ):
                return {"ok": False, "error": "not_a_member"}

            # Messages in the room.
            messages = await MessageRepository(session).list_for_stream(
                stream_id, limit=limit
            )
            user_repo = UserRepository(session)
            authors: dict[str, str] = {}
            for r in messages:
                if r.author_id not in authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        authors[r.author_id] = u.username

            # IM suggestions whose source message landed in this room.
            suggestions = await IMSuggestionRepository(session).list_for_project(
                project_id=project_id, stream_id=stream_id, limit=limit
            )

            # Decisions whose scope_stream_id == this room. Picks up
            # the B3 + pickup-#6 chain — a decision crystallized from
            # a room conversation appears here.
            decision_rows = list(
                (
                    await session.execute(
                        select(DecisionRow)
                        .where(
                            DecisionRow.project_id == project_id,
                            DecisionRow.scope_stream_id == stream_id,
                        )
                        .order_by(DecisionRow.created_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )

        # Build the TimelineItem[] chronologically. Each item carries
        # the canonical entity id under `id` so the frontend dedupes
        # by (kind, id) on every event.
        items: list[dict[str, Any]] = []
        for r in messages:
            items.append(
                {
                    "kind": "message",
                    "id": r.id,
                    "stream_id": r.stream_id,
                    "project_id": r.project_id,
                    "author_id": r.author_id,
                    "author_username": authors.get(r.author_id),
                    "body": r.body,
                    "kind_message": r.kind,
                    "linked_id": r.linked_id,
                    "created_at": r.created_at.isoformat()
                    if r.created_at
                    else None,
                }
            )
        for s in suggestions:
            items.append(
                {
                    "kind": "im_suggestion",
                    "id": s.id,
                    "project_id": s.project_id,
                    "message_id": s.message_id,
                    "status": s.status,
                    "kind_suggestion": s.kind,
                    "confidence": s.confidence,
                    "targets": s.targets or [],
                    "proposal": s.proposal or {},
                    "reasoning": s.reasoning or "",
                    "decision_id": s.decision_id,
                    "counter_of_id": s.counter_of_id,
                    "created_at": s.created_at.isoformat()
                    if s.created_at
                    else None,
                    "resolved_at": s.resolved_at.isoformat()
                    if s.resolved_at
                    else None,
                }
            )
        # Lazy import — keeps the room_timeline → decision_votes
        # dependency one-way (decision_votes does not import this).
        from .decision_votes import enrich_decision_with_tally
        for d in decision_rows:
            payload = {
                "kind": "decision",
                "id": d.id,
                "project_id": d.project_id,
                "conflict_id": d.conflict_id,
                "source_suggestion_id": d.source_suggestion_id,
                "resolver_id": d.resolver_id,
                "rationale": d.rationale,
                "custom_text": d.custom_text,
                "scope_stream_id": d.scope_stream_id,
                "apply_outcome": d.apply_outcome,
                "created_at": d.created_at.isoformat()
                if d.created_at
                else None,
                "applied_at": d.applied_at.isoformat()
                if d.applied_at
                else None,
            }
            # Per-decision tally enrichment so the room view doesn't
            # need a follow-up GET per card.
            await enrich_decision_with_tally(payload, self._sessionmaker)
            items.append(payload)
        # Single chronological merge — all kinds share a created_at.
        # Ties (same instant): messages first so a derived suggestion
        # renders below its source.
        kind_order = {"message": 0, "im_suggestion": 1, "decision": 2}
        items.sort(
            key=lambda it: (
                it.get("created_at") or "",
                kind_order.get(it["kind"], 9),
            )
        )

        return {
            "ok": True,
            "stream_id": stream_id,
            "project_id": project_id,
            "items": items,
        }


__all__ = [
    "RoomTimelineService",
    "is_room_stream",
    "make_decision_event",
    "make_message_event",
    "make_suggestion_event",
    "make_suggestion_status_update",
]
