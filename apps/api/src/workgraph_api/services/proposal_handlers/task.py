"""task_promote — owner accepts a personal-scope task being promoted
into the project plan. Bumps it to plan-scope under the latest
requirement, with a sort_order placed at the tail so existing plan
order stays stable.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import (
    IMSuggestionRow,
    PlanRepository,
    RequirementRepository,
)

from .base import HandlerServices


class TaskPromoteHandler:
    candidate_kind = "task_promote"

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: HandlerServices,
    ) -> dict[str, Any]:
        task_id = (
            detail.get("task_id") if isinstance(detail, dict) else None
        )
        if not task_id:
            return {"ok": False, "error": "missing_task_id"}
        req = await RequirementRepository(session).latest_for_project(
            row.project_id
        )
        if req is None:
            return {"ok": False, "error": "no_requirement_to_attach_to"}
        existing = await PlanRepository(session).list_tasks(req.id)
        next_sort = (
            max((t.sort_order or 0) for t in existing) + 1 if existing else 0
        )
        promoted = await PlanRepository(session).promote_personal_to_plan(
            task_id=task_id,
            requirement_id=req.id,
            sort_order=next_sort,
        )
        if promoted is None:
            return {"ok": False, "error": "promote_failed"}
        return {
            "ok": True,
            "graph_touched": True,
            "task_id": task_id,
            "action": "approve_membrane_candidate",
        }


__all__ = ["TaskPromoteHandler"]
