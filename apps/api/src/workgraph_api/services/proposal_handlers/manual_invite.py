"""manual_invite — owner accepts a non-owner's member-invite proposal.

Replays add_member through the gated service path with
_skip_membrane=True.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import IMSuggestionRow

from .base import HandlerServices


class ManualInviteHandler:
    candidate_kind = "manual_invite"

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: HandlerServices,
    ) -> dict[str, Any]:
        if services.project_service is None:
            return {"ok": False, "error": "project_service_unavailable"}
        if not isinstance(detail, dict):
            return {"ok": False, "error": "missing_manual_invite_detail"}
        target_username = detail.get("target_username") or ""
        proposer_user_id = detail.get("proposer_user_id") or actor_id
        if not target_username:
            return {"ok": False, "error": "missing_target_username"}
        result = await services.project_service.add_member(
            project_id=row.project_id,
            username=target_username,
            invited_by=proposer_user_id,
            _skip_membrane=True,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "manual_invite_failed"),
            }
        return {
            "ok": True,
            "graph_touched": True,
            "user_id": result.get("user_id"),
            "username": target_username,
            "action": "approve_membrane_candidate",
        }


__all__ = ["ManualInviteHandler"]
