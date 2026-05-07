"""manual_room — owner accepts a non-owner's room-create candidate.

Replays the args via StreamService. `_skip_membrane=True` bypasses
the gate (we're past the owner approval — re-running review would
loop).
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import IMSuggestionRow

from .base import HandlerServices


class ManualRoomHandler:
    candidate_kind = "manual_room"

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: HandlerServices,
    ) -> dict[str, Any]:
        if services.stream_service is None:
            return {"ok": False, "error": "stream_service_unavailable"}
        if not isinstance(detail, dict):
            return {"ok": False, "error": "missing_manual_room_detail"}
        name = detail.get("name") or ""
        member_user_ids = detail.get("member_user_ids") or []
        proposer_user_id = detail.get("proposer_user_id") or actor_id
        result = await services.stream_service.create_room(
            project_id=row.project_id,
            creator_user_id=proposer_user_id,
            name=name,
            member_user_ids=list(member_user_ids),
            _skip_membrane=True,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "manual_room_create_failed"),
            }
        stream = result.get("stream") or {}
        return {
            "ok": True,
            "graph_touched": True,
            "stream_id": stream.get("id"),
            "action": "approve_membrane_candidate",
        }


__all__ = ["ManualRoomHandler"]
