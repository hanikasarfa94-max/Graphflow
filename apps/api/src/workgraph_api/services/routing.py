"""Parent-agent routing service — Phase L.

North-star §"Sub-agent and routing architecture": the parent agent is the
cross-user routing hub. A source's edge-agent dispatches a framed signal
(context + rich options) to a target's edge-agent; the target replies with
one-click option pick or custom text; the reply flows back and can
crystallize into a decision.

This service is the backend primitive for that flow. It does NOT itself
call any LLM — the framing / background / options are produced upstream
(in v1 by the web frontend passing prefilled data; in Phase M by a
prompt-driven sub-agent). Here we persist, fan out, and mirror.

Dispatch side-effects
---------------------
1. Persist a RoutedSignalRow with status='pending'
2. Post a `kind='routed-inbound'` message into the target's personal
   stream (linked_id → signal.id). Author = edge-agent system user.
3. Ensure a source↔target DM stream exists (reuse StreamService
   create_or_get_dm). Post a `kind='routed-dm-log'` summary message
   there so the pair has a shared audit trail of LLM-routed flows.

Reply side-effects
------------------
1. Flip RoutedSignalRow.status → 'replied', record reply_json
2. Post a `kind='routed-reply'` message into the source's personal
   stream (edge-agent author, linked_id → signal.id)
3. Mirror a `kind='routed-dm-log'` summary message into the DM

The edge-agent system user is the one from
`workgraph_persistence.ensure_edge_agent_system_user`. Messages it posts
render as a 🧠 Edge card on the frontend.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    ProjectMemberRepository,
    RoutedSignalRepository,
    RoutedSignalRow,
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)

from .signal_tally import SignalTallyService
from .streams import StreamService

_log = logging.getLogger("workgraph.api.routing")


def _shape(row: RoutedSignalRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "trace_id": row.trace_id,
        "source_user_id": row.source_user_id,
        "target_user_id": row.target_user_id,
        "source_stream_id": row.source_stream_id,
        "target_stream_id": row.target_stream_id,
        "project_id": row.project_id,
        "framing": row.framing,
        "background": list(row.background_json or []),
        "options": list(row.options_json or []),
        "status": row.status,
        "reply": row.reply_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "responded_at": (
            row.responded_at.isoformat() if row.responded_at else None
        ),
    }


class RoutingService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        stream_service: StreamService,
        signal_tally: SignalTallyService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._stream_service = stream_service
        self._signal_tally = signal_tally

    # ---- dispatch --------------------------------------------------------

    async def dispatch(
        self,
        *,
        source_user_id: str,
        target_user_id: str,
        framing: str,
        background: list,
        options: list,
        project_id: str,
    ) -> dict[str, Any]:
        """Create a routed signal and post the inbound card + DM mirror.

        Returns `{"ok": True, "signal": {...}}` on success, or
        `{"ok": False, "error": "<code>"}` with codes:
          * 'cannot_route_to_self'
          * 'target_not_found'
          * 'source_not_project_member'
          * 'target_not_project_member'
          * 'project_not_found'  (raised via membership lookup)
        """
        if source_user_id == target_user_id:
            return {"ok": False, "error": "cannot_route_to_self"}

        trace_id = get_trace_id()

        async with session_scope(self._sessionmaker) as session:
            user_repo = UserRepository(session)
            target_user = await user_repo.get(target_user_id)
            if target_user is None:
                return {"ok": False, "error": "target_not_found"}

            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, source_user_id):
                return {"ok": False, "error": "source_not_project_member"}
            if not await pm_repo.is_member(project_id, target_user_id):
                return {"ok": False, "error": "target_not_project_member"}

            source_user = await user_repo.get(source_user_id)
            source_display = (
                source_user.display_name or source_user.username
                if source_user
                else source_user_id
            )
            target_display = (
                target_user.display_name or target_user.username
            )

        # Ensure both personal streams exist (backfill may not have covered
        # this pair if a member joined after boot).
        source_ps = await self._stream_service.ensure_personal_stream(
            user_id=source_user_id, project_id=project_id
        )
        target_ps = await self._stream_service.ensure_personal_stream(
            user_id=target_user_id, project_id=project_id
        )
        source_stream_id = source_ps["stream_id"]
        target_stream_id = target_ps["stream_id"]

        # Persist the signal row.
        async with session_scope(self._sessionmaker) as session:
            signal = await RoutedSignalRepository(session).create(
                source_user_id=source_user_id,
                target_user_id=target_user_id,
                source_stream_id=source_stream_id,
                target_stream_id=target_stream_id,
                project_id=project_id,
                framing=framing,
                background=background,
                options=options,
                trace_id=trace_id,
            )
            signal_payload = _shape(signal)

        # Post the routed-inbound card into the target's personal stream
        # (edge-agent is the author). Body is a short human-readable
        # fallback; frontend uses `kind` + `linked_id` to render the rich
        # card by fetching the signal.
        inbound_body = (
            f"🧠 {source_display} routed a decision to you: {framing}"
        )
        await self._stream_service.post_system_message(
            stream_id=target_stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=inbound_body,
            kind="routed-inbound",
            linked_id=signal.id,
        )

        # DM mirror — the dual-purpose DM is the shared log of routed
        # flows between the pair. Create if needed.
        dm_result = await self._stream_service.create_or_get_dm(
            user_id=source_user_id, other_user_id=target_user_id
        )
        if dm_result.get("ok"):
            dm_stream_id = dm_result["stream"]["id"]
            dm_body = f"🧠 {source_display} → {target_display} via edge: {framing}"
            await self._stream_service.post_system_message(
                stream_id=dm_stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=dm_body,
                kind="routed-dm-log",
                linked_id=signal.id,
            )

        await self._event_bus.emit(
            "routing.dispatched",
            {
                "signal_id": signal.id,
                "source_user_id": source_user_id,
                "target_user_id": target_user_id,
                "project_id": project_id,
                "option_count": len(options or []),
            },
        )
        return {"ok": True, "signal": signal_payload}

    # ---- reply -----------------------------------------------------------

    async def reply(
        self,
        *,
        signal_id: str,
        replier_user_id: str,
        option_id: str | None = None,
        custom_text: str | None = None,
    ) -> dict[str, Any]:
        """Record target's reply, post into source's personal stream, mirror DM.

        Error codes:
          * 'signal_not_found'
          * 'not_the_target' — replier must be signal.target_user_id
          * 'already_replied' — status is not 'pending' (idempotency boundary)
          * 'empty_reply' — neither option_id nor custom_text provided
        """
        if not option_id and not (custom_text and custom_text.strip()):
            return {"ok": False, "error": "empty_reply"}

        async with session_scope(self._sessionmaker) as session:
            repo = RoutedSignalRepository(session)
            signal = await repo.get(signal_id)
            if signal is None:
                return {"ok": False, "error": "signal_not_found"}
            if signal.target_user_id != replier_user_id:
                return {"ok": False, "error": "not_the_target"}
            if signal.status != "pending":
                return {"ok": False, "error": "already_replied"}

            updated = await repo.mark_replied(
                signal_id,
                option_id=option_id,
                custom_text=custom_text,
            )
            signal_payload = _shape(updated)

            user_repo = UserRepository(session)
            source_user = await user_repo.get(signal.source_user_id)
            target_user = await user_repo.get(signal.target_user_id)
            target_display = (
                target_user.display_name or target_user.username
                if target_user
                else signal.target_user_id
            )
            source_display = (
                source_user.display_name or source_user.username
                if source_user
                else signal.source_user_id
            )

            # Find the option label for friendlier DM-mirror text.
            option_label = None
            if option_id:
                for opt in signal.options_json or []:
                    if isinstance(opt, dict) and opt.get("id") == option_id:
                        option_label = opt.get("label")
                        break

        # Post routed-reply into source's personal stream.
        if option_label:
            reply_summary = f"picked '{option_label}'"
        elif option_id:
            reply_summary = f"picked option {option_id}"
        else:
            reply_summary = f'replied: "{(custom_text or "").strip()[:160]}"'
        reply_body = f"🧠 {target_display} {reply_summary}"
        await self._stream_service.post_system_message(
            stream_id=signal.source_stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=reply_body,
            kind="routed-reply",
            linked_id=signal.id,
        )

        # Mirror into the DM log.
        dm_result = await self._stream_service.create_or_get_dm(
            user_id=signal.source_user_id, other_user_id=signal.target_user_id
        )
        if dm_result.get("ok"):
            dm_stream_id = dm_result["stream"]["id"]
            dm_body = f"🧠 {target_display} → {source_display}: {reply_summary}"
            await self._stream_service.post_system_message(
                stream_id=dm_stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=dm_body,
                kind="routed-dm-log",
                linked_id=signal.id,
            )

        await self._event_bus.emit(
            "routing.replied",
            {
                "signal_id": signal.id,
                "source_user_id": signal.source_user_id,
                "target_user_id": signal.target_user_id,
                "option_id": option_id,
                "has_custom_text": bool(custom_text),
            },
        )
        if self._signal_tally is not None:
            await self._signal_tally.increment(replier_user_id, "routings_answered")
        return {"ok": True, "signal": signal_payload}

    # ---- reads -----------------------------------------------------------

    async def get_for_user(
        self,
        user_id: str,
        *,
        kind: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await RoutedSignalRepository(session).list_for_user(
                user_id, kind=kind, status=status, limit=limit
            )
            return [_shape(r) for r in rows]

    async def get(self, signal_id: str, *, viewer_id: str) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await RoutedSignalRepository(session).get(signal_id)
            if row is None:
                return {"ok": False, "error": "signal_not_found"}
            if viewer_id not in (row.source_user_id, row.target_user_id):
                return {"ok": False, "error": "not_a_participant"}
            return {"ok": True, "signal": _shape(row)}


__all__ = ["RoutingService"]
