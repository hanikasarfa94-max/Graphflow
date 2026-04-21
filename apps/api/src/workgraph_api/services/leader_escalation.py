"""LeaderEscalationService — Phase 1.A leader-handoff path.

When a scoped sub-agent can't answer an in-license question because the
necessary context lives outside the asker's view, escalate the question
to the project leader. The leader's full-license sub-agent drafts a
reply (via PreAnswerService), surfaces it in the leader's stream, and
the leader picks accept / edit / deny before the reply ships back to
the original asker.

Reuses `RoutedSignalRow` as the transport primitive — a leader-
escalation is just a routed signal whose `target_user_id` is the
project leader and whose `framing` names the original asker + their
question. Discriminator is carried in the options set
(`kind='leader-escalation'`) so the leader's UI can render the drafted
preview instead of the normal option picker.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    ProjectMemberRepository,
    session_scope,
)

from .pre_answer import PreAnswerService
from .routing import RoutingService

_log = logging.getLogger("workgraph.api.leader_escalation")

# Option id used on the routed signal carrying the leader-draft preview.
LEADER_DRAFT_OPTION_ID = "leader-escalation-draft"


class LeaderEscalationService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        routing_service: RoutingService,
        pre_answer_service: PreAnswerService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._routing = routing_service
        self._pre_answer = pre_answer_service

    async def _find_leader(self, project_id: str) -> str | None:
        """Pick the project leader. The 'owner' role wins; if multiple
        owners exist, the earliest-joined one does."""
        async with session_scope(self._sessionmaker) as session:
            rows = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            owners = [
                r for r in rows if (r.role or "").lower() == "owner"
            ]
            if owners:
                return owners[0].user_id
            # Fall back to any full-tier member — a project with no
            # explicit owner can still have escalation resolved by a
            # full-license teammate.
            fulls = [
                r
                for r in rows
                if str(r.license_tier or "full") == "full"
            ]
            if fulls:
                return fulls[0].user_id
        return None

    async def escalate(
        self,
        *,
        project_id: str,
        asker_user_id: str,
        question: str,
        reason: str,
    ) -> dict[str, Any]:
        """Create a routed signal to the project leader carrying a
        pre-drafted reply. Returns `{"ok": True, "signal": {...},
        "leader_user_id": ...}` or an `{"ok": False, "error": ...}`.

        If no leader is found, returns `no_leader_found` — the caller
        can fall back to a manual-reply path.
        """
        leader_id = await self._find_leader(project_id)
        if leader_id is None:
            return {"ok": False, "error": "no_leader_found"}
        if leader_id == asker_user_id:
            return {"ok": False, "error": "asker_is_leader"}

        # Leader drafts via pre-answer pipeline with FULL license (leader
        # is full-tier by construction). `draft_pre_answer` internally
        # resolves roles + produces an LLM draft; we treat the asker as
        # the "sender" so the draft mirrors the question's framing.
        preview = await self._pre_answer.draft_pre_answer(
            project_id=project_id,
            sender_user_id=asker_user_id,
            target_user_id=leader_id,
            question=question,
        )
        draft_body = ""
        if preview.get("ok"):
            draft_body = (preview.get("draft") or {}).get("body") or ""

        framing = (
            f"[escalation] {asker_user_id}'s sub-agent needed leader input: "
            f"{reason}. Their question: {question[:600]}"
        )
        # Single option carrying the drafted reply preview. The leader's
        # UI renders accept/edit/deny against this payload; on accept
        # the reply text ships back to the asker's stream via the
        # normal routing reply path.
        options = [
            {
                "id": LEADER_DRAFT_OPTION_ID,
                "label": "Accept drafted reply",
                "kind": "leader-escalation",
                "background": draft_body,
                "reason": reason,
                "tradeoff": "",
                "weight": 1.0,
            }
        ]

        dispatch = await self._routing.dispatch(
            source_user_id=asker_user_id,
            target_user_id=leader_id,
            framing=framing,
            background=[
                {
                    "source": "escalation",
                    "snippet": question[:4000],
                    "reference_id": None,
                }
            ],
            options=options,
            project_id=project_id,
        )
        if not dispatch.get("ok"):
            return {
                "ok": False,
                "error": dispatch.get("error") or "dispatch_failed",
            }
        return {
            "ok": True,
            "signal": dispatch["signal"],
            "leader_user_id": leader_id,
            "draft_body": draft_body,
        }

    def should_escalate(self, agent_output: dict[str, Any]) -> tuple[bool, str]:
        """Decision heuristic. Returns (escalate, reason).

        Explicit `escalate_to_leader=True` wins. Falls back to
        confidence < 0.35 when the output still marks out-of-view
        context as the missing piece.
        """
        if not isinstance(agent_output, dict):
            return (False, "")
        if agent_output.get("escalate_to_leader") is True:
            reason = (
                agent_output.get("reason")
                or agent_output.get("rationale")
                or "agent requested escalation"
            )
            return (True, str(reason))
        confidence = agent_output.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < 0.35:
            if agent_output.get("out_of_view_context_needed") is True:
                return (True, "confidence below threshold; out-of-view context needed")
        return (False, "")


__all__ = ["LeaderEscalationService", "LEADER_DRAFT_OPTION_ID"]
