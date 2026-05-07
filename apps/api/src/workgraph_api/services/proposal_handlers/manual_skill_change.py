"""manual_skill_change — owner accepts a non-owner's skill_tags edit.

Replays through ProjectService.set_member_skill_tags with
_skip_membrane=True so the gate doesn't double-fire.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import IMSuggestionRow

from .base import HandlerServices


class ManualSkillChangeHandler:
    candidate_kind = "manual_skill_change"

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
            return {
                "ok": False,
                "error": "missing_manual_skill_change_detail",
            }
        target_user_id = detail.get("target_user_id")
        proposer_user_id = detail.get("proposer_user_id") or actor_id
        new_skill_tags = detail.get("new_skill_tags") or []
        if not target_user_id:
            return {"ok": False, "error": "missing_target_user_id"}
        result = await services.project_service.set_member_skill_tags(
            project_id=row.project_id,
            actor_user_id=proposer_user_id,
            target_user_id=target_user_id,
            skill_tags=list(new_skill_tags),
            _skip_membrane=True,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error", "manual_skill_change_failed"),
            }
        return {
            "ok": True,
            "graph_touched": True,
            "user_id": target_user_id,
            "skill_tags": result.get("skill_tags"),
            "action": "approve_membrane_candidate",
        }


__all__ = ["ManualSkillChangeHandler"]
