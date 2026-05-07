"""KB candidate handlers.

Two kinds share the KB lifecycle:
  * kb_item_group        → flip a draft KbItemRow to status='published'
  * kb_archive_request   → flip a published KbItemRow to status='archived'

Both run after the owner clicked accept on a membrane_review
suggestion. The membrane already validated the candidate at queue
time; this is the cell-side write.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import IMSuggestionRow, KbItemRepository

from .base import HandlerServices


class KbItemGroupHandler:
    candidate_kind = "kb_item_group"

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: HandlerServices,
    ) -> dict[str, Any]:
        kb_item_id = (
            detail.get("kb_item_id") if isinstance(detail, dict) else None
        )
        if not kb_item_id:
            return {"ok": False, "error": "missing_kb_item_id"}
        updated = await KbItemRepository(session).update(
            item_id=kb_item_id, status="published"
        )
        if updated is None:
            return {"ok": False, "error": "kb_item_not_found"}
        return {
            "ok": True,
            "graph_touched": True,
            "kb_item_id": kb_item_id,
            "action": "approve_membrane_candidate",
        }


class KbArchiveRequestHandler:
    """M1.2 — owner accepts a member's request to archive a group-scope
    KB item. Soft-archive in place; the row stays in the DB for audit.
    is_canonical_kb_row excludes status='archived' so retrieval /
    kb_search stop using it immediately."""

    candidate_kind = "kb_archive_request"

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: HandlerServices,
    ) -> dict[str, Any]:
        kb_item_id = (
            detail.get("kb_item_id") if isinstance(detail, dict) else None
        )
        if not kb_item_id:
            return {"ok": False, "error": "missing_kb_item_id"}
        updated = await KbItemRepository(session).update(
            item_id=kb_item_id, status="archived"
        )
        if updated is None:
            return {"ok": False, "error": "kb_item_not_found"}
        return {
            "ok": True,
            "graph_touched": True,
            "kb_item_id": kb_item_id,
            "action": "archive_kb_item",
        }


__all__ = ["KbArchiveRequestHandler", "KbItemGroupHandler"]
