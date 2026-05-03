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
render as a 🤖 Edge card on the frontend.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    LicenseAuditRepository,
    ProjectMemberRepository,
    RoutedSignalRepository,
    RoutedSignalRow,
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)

from .license_context import LicenseContextService
from .license_lint import lint_reply
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
        license_context_service: LicenseContextService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._stream_service = stream_service
        self._signal_tally = signal_tally
        self._license_ctx = license_context_service

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
            f"🤖 {source_display} routed a decision to you: {framing}"
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
        # We post the framing as a `routed-prompt` message authored by
        # the SOURCE human so the DM reads like a real conversation A
        # initiated. Previously we ALSO posted a `routed-dm-log` audit
        # line ("🤖 X → Y via edge: {framing}") — but that contained
        # the same framing text and showed as a visual duplicate next
        # to routed-prompt. The routing fact (it went through edge) is
        # already on the RoutedSignalRow itself, so the audit is not
        # lost; we just stop double-printing it to the user.
        dm_result = await self._stream_service.create_or_get_dm(
            user_id=source_user_id, other_user_id=target_user_id
        )
        if dm_result.get("ok"):
            dm_stream_id = dm_result["stream"]["id"]
            await self._stream_service.post_system_message(
                stream_id=dm_stream_id,
                author_id=source_user_id,
                body=framing,
                kind="routed-prompt",
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
        lint_decision: str | None = None,
        skip_source_post: bool = False,
    ) -> dict[str, Any]:
        """Record target's reply, post into source's personal stream, mirror DM.

        Error codes:
          * 'signal_not_found'
          * 'not_the_target' — replier must be signal.target_user_id
          * 'already_replied' — status is not 'pending' (idempotency boundary)
          * 'empty_reply' — neither option_id nor custom_text provided

        If `lint_decision` is None (default), a license-lint runs on the
        outbound reply body. When the lint pauses, this method returns
        `{"ok": False, "error": "lint_paused", "lint": {...}}` without
        persisting the reply — the caller surfaces the options to the
        source and then calls reply() again with the chosen
        `lint_decision`. `lint_decision='deny'` writes the audit row
        and short-circuits without shipping; other decisions proceed
        to persistence + fan-out.
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

            # License lint on outbound reply body — the source is the
            # recipient of this reply. We scan the custom_text (if any)
            # or the option-label body the source will see.
            scan_body = custom_text or ""
            if not scan_body and option_id:
                for opt in signal.options_json or []:
                    if isinstance(opt, dict) and opt.get("id") == option_id:
                        # Join label + background so any cited refs
                        # in the option payload get scanned too.
                        scan_body = " ".join(
                            str(opt.get(k) or "")
                            for k in ("label", "background", "reason")
                        )
                        break
            lint_result: dict[str, Any] | None = None
            if (
                lint_decision is None
                and self._license_ctx is not None
                and signal.project_id
            ):
                lint_result = await self.lint_outbound_reply(
                    project_id=signal.project_id,
                    source_user_id=signal.target_user_id,
                    recipient_user_id=signal.source_user_id,
                    reply_body=scan_body,
                    signal_id=signal.id,
                )
                if lint_result.get("status") == "paused":
                    return {
                        "ok": False,
                        "error": "lint_paused",
                        "lint": lint_result,
                    }

            # Handle source decision. 'deny' halts before persistence.
            if lint_decision == "deny" and signal.project_id:
                await self.resolve_lint_decision(
                    project_id=signal.project_id,
                    source_user_id=signal.target_user_id,
                    recipient_user_id=signal.source_user_id,
                    reply_body=scan_body,
                    decision="deny",
                    referenced_node_ids=[],
                    out_of_view_node_ids=[],
                    effective_tier="full",
                    signal_id=signal.id,
                )
                return {"ok": False, "error": "denied"}

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
        # Callers wrapping a follow-up frame (PersonalStreamService.handle_reply
        # writes a richer `edge-reply-frame` immediately after) pass
        # skip_source_post=True so the source stream gets one card per
        # reply, not two. The frontend has a dedupe band-aid, but the
        # right fix is to not double-write. Direct callers (tests,
        # programmatic dispatch without a frame layer) keep the summary.
        if option_label:
            reply_summary = f"picked '{option_label}'"
        elif option_id:
            reply_summary = f"picked option {option_id}"
        else:
            reply_summary = f'replied: "{(custom_text or "").strip()[:160]}"'
        if not skip_source_post:
            reply_body = f"🤖 {target_display} {reply_summary}"
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
            dm_body = f"🤖 {target_display} → {source_display}: {reply_summary}"
            await self._stream_service.post_system_message(
                stream_id=dm_stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=dm_body,
                kind="routed-dm-log",
                linked_id=signal.id,
            )

        # Tally before emit — see decisions.py for the concurrency
        # hazard when subscribers run in parallel sessions.
        if self._signal_tally is not None:
            await self._signal_tally.increment(replier_user_id, "routings_answered")
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

        # Audit trail for the reply. Covers the three non-denied
        # outcomes: clean lint, edited ship (lint_decision='edit' or
        # 'ship' with lint flags), and manual answer.
        if signal.project_id and self._license_ctx is not None:
            audit_outcome = "clean"
            ref_ids: list[str] = []
            out_ids: list[str] = []
            eff_tier = "full"
            if lint_decision == "edit":
                audit_outcome = "edited"
            elif lint_decision == "ship":
                audit_outcome = "edited"  # source shipped past a flag
            elif lint_decision == "answer_manually":
                audit_outcome = "manual"
            if lint_result is not None:
                ref_ids = list(lint_result.get("referenced") or [])
                out_ids = list(lint_result.get("out_of_view") or [])
                eff_tier = str(lint_result.get("effective_tier") or "full")
            async with session_scope(self._sessionmaker) as session:
                await LicenseAuditRepository(session).record(
                    project_id=signal.project_id,
                    source_user_id=signal.target_user_id,
                    target_user_id=signal.source_user_id,
                    signal_id=signal.id,
                    referenced_node_ids=ref_ids,
                    out_of_view_node_ids=out_ids,
                    outcome=audit_outcome,
                    effective_tier=eff_tier,
                )
        return {"ok": True, "signal": signal_payload}

    # ---- license lint ---------------------------------------------------

    async def lint_outbound_reply(
        self,
        *,
        project_id: str,
        source_user_id: str,
        recipient_user_id: str,
        reply_body: str,
        signal_id: str | None = None,
        explicit_citations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Scan an outbound reply against the recipient's license view.

        If the lint is clean, returns `{"status": "clean", ...}` and the
        caller may ship the reply. If any cited node falls outside the
        recipient's view, returns `{"status": "paused", "options": [...]}`
        — the caller surfaces this as a pause card with
        ship / edit / deny / answer_manually.

        No persistence happens here; the caller records the decision
        through `resolve_lint_decision` once the source picks an option.
        """
        if self._license_ctx is None:
            # Fall-open only when the service hasn't been wired. Tests
            # that exercise lint always wire it; production wiring in
            # main.py wires it too. This branch exists for minimal
            # integration-test paths that don't touch lint.
            return {
                "status": "clean",
                "referenced": [],
                "out_of_view": [],
                "effective_tier": "full",
            }
        result = await lint_reply(
            license_context_service=self._license_ctx,
            project_id=project_id,
            source_user_id=source_user_id,
            recipient_user_id=recipient_user_id,
            reply_body=reply_body,
            explicit_citations=explicit_citations,
        )
        if result["clean"]:
            return {
                "status": "clean",
                "referenced": result["referenced"],
                "out_of_view": [],
                "effective_tier": result["effective_tier"],
            }
        return {
            "status": "paused",
            "referenced": result["referenced"],
            "out_of_view": result["out_of_view"],
            "effective_tier": result["effective_tier"],
            "signal_id": signal_id,
            "options": [
                {"id": "ship", "label": "Ship anyway"},
                {"id": "edit", "label": "Edit then ship"},
                {"id": "deny", "label": "Deny — don't send"},
                {
                    "id": "answer_manually",
                    "label": "Answer manually (bypass routing)",
                },
            ],
        }

    async def resolve_lint_decision(
        self,
        *,
        project_id: str,
        source_user_id: str,
        recipient_user_id: str,
        reply_body: str,
        decision: str,
        referenced_node_ids: list[str],
        out_of_view_node_ids: list[str],
        effective_tier: str,
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist a LicenseAuditRow for the source's decision on a
        paused reply. `decision` ∈ {'ship', 'edit', 'deny',
        'answer_manually'}. Maps 1:1 to audit outcomes 'clean' (when
        lint was already clean), 'edited', 'denied', 'manual'.

        Returns the persisted outcome so the caller can tell the UI
        what to render.
        """
        outcome_map = {
            "ship": "clean" if not out_of_view_node_ids else "edited",
            "edit": "edited",
            "deny": "denied",
            "answer_manually": "manual",
        }
        outcome = outcome_map.get(decision, "edited")
        async with session_scope(self._sessionmaker) as session:
            await LicenseAuditRepository(session).record(
                project_id=project_id,
                source_user_id=source_user_id,
                target_user_id=recipient_user_id,
                signal_id=signal_id,
                referenced_node_ids=referenced_node_ids,
                out_of_view_node_ids=out_of_view_node_ids,
                outcome=outcome,
                effective_tier=effective_tier,
            )
        return {"ok": True, "outcome": outcome}

    async def record_clean_audit(
        self,
        *,
        project_id: str,
        source_user_id: str,
        recipient_user_id: str,
        referenced_node_ids: list[str],
        effective_tier: str,
        signal_id: str | None = None,
    ) -> None:
        """Write a clean-outcome audit row (no out-of-view ids). Used
        when the lint pass found nothing to flag but we still want an
        audit trail of the reply."""
        async with session_scope(self._sessionmaker) as session:
            await LicenseAuditRepository(session).record(
                project_id=project_id,
                source_user_id=source_user_id,
                target_user_id=recipient_user_id,
                signal_id=signal_id,
                referenced_node_ids=referenced_node_ids,
                out_of_view_node_ids=[],
                outcome="clean",
                effective_tier=effective_tier,
            )

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

    async def accept(
        self, *, signal_id: str, accepter_user_id: str
    ) -> dict[str, Any]:
        """Source closes the loop on a replied signal. Persists the
        transition so a refresh after the click never reopens the
        accept button. Idempotent: re-accepting a signal already in
        'accepted' returns ok without writing.
        """
        async with session_scope(self._sessionmaker) as session:
            repo = RoutedSignalRepository(session)
            row = await repo.get(signal_id)
            if row is None:
                return {"ok": False, "error": "signal_not_found"}
            if row.source_user_id != accepter_user_id:
                return {"ok": False, "error": "not_the_source"}
            if row.status not in ("replied", "accepted"):
                return {"ok": False, "error": "not_accepted_state"}
            updated = await repo.mark_accepted(signal_id)
            return {"ok": True, "signal": _shape(updated)}


__all__ = ["RoutingService"]
