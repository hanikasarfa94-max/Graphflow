"""Phase Q — KB browseable endpoints (north-star Q.6).

Earlier v1 decision deferred `/kb` browsing to v2. Phase Q corrects that:
KB is user-facing, not just an LLM corpus. v1 sources KB items from the
MembraneSignalRepository (ingested external signals + pasted artifacts);
future KB tables can plug into the same shape without breaking the API.

  * GET /api/projects/{project_id}/kb              — list KB items
  * GET /api/projects/{project_id}/kb/{item_id}    — item detail

Auth: project member required (observer-tier can read).
Filters on list: `query` (substring), `source_kind`, `limit`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from workgraph_persistence import (
    MembraneSignalRepository,
    MembraneSignalRow,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

router = APIRouter(prefix="/api", tags=["kb"])


def _kb_list_payload(row: MembraneSignalRow) -> dict:
    """Compact list-view payload for a KB item."""
    classification = dict(row.classification_json or {})
    summary = (classification.get("summary") or "") or (row.raw_content or "")
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_kind": row.source_kind,
        "source_identifier": row.source_identifier,
        "summary": summary[:300],
        "tags": list(classification.get("tags") or []),
        "status": row.status,
        "ingested_by_user_id": row.ingested_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _kb_detail_payload(row: MembraneSignalRow) -> dict:
    """Full-detail payload for a single KB item."""
    classification = dict(row.classification_json or {})
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_kind": row.source_kind,
        "source_identifier": row.source_identifier,
        "raw_content": row.raw_content,
        "classification": classification,
        "status": row.status,
        "ingested_by_user_id": row.ingested_by_user_id,
        "approved_by_user_id": row.approved_by_user_id,
        "approved_at": (
            row.approved_at.isoformat() if row.approved_at else None
        ),
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/projects/{project_id}/kb")
async def get_kb_list(
    project_id: str,
    request: Request,
    query: str | None = Query(default=None),
    source_kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    """List KB items for a project.

    KB items are MembraneSignalRows with `status != 'rejected'` plus any
    future KB sources (not yet in v1). `query` does case-insensitive
    substring match on raw_content, summary, and tags. `source_kind`
    filters on the origin channel (git-commit, rss, user-drop, …).
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    q = (query or "").strip().lower()

    async with session_scope(request.app.state.sessionmaker) as session:
        rows = await MembraneSignalRepository(session).list_for_project(
            project_id, limit=500
        )

    # Rejected items stay in the audit table but never surface in the
    # browseable KB (north-star §"Documents, knowledge, and edits"
    # treats KB as live reference; rejected rows are audit history).
    rows = [r for r in rows if r.status != "rejected"]

    if source_kind:
        rows = [r for r in rows if r.source_kind == source_kind]

    if q:
        filtered: list[MembraneSignalRow] = []
        for r in rows:
            classification = dict(r.classification_json or {})
            haystack = " ".join(
                [
                    (r.raw_content or "").lower(),
                    (classification.get("summary") or "").lower(),
                    " ".join(
                        str(t).lower()
                        for t in (classification.get("tags") or [])
                    ),
                    (r.source_identifier or "").lower(),
                ]
            )
            if q in haystack:
                filtered.append(r)
        rows = filtered

    rows = rows[:limit]
    return {
        "ok": True,
        "items": [_kb_list_payload(r) for r in rows],
        "count": len(rows),
    }


@router.get("/projects/{project_id}/kb/{item_id}")
async def get_kb_item(
    project_id: str,
    item_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Fetch a single KB item's full detail.

    404 if the item doesn't exist OR belongs to a different project
    (we don't leak existence across projects).
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    async with session_scope(request.app.state.sessionmaker) as session:
        row = await MembraneSignalRepository(session).get(item_id)

    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="kb_item_not_found")
    if row.status == "rejected":
        # Rejected items are audit history; don't surface them in the
        # live KB even on direct GET.
        raise HTTPException(status_code=404, detail="kb_item_not_found")

    return {"ok": True, "item": _kb_detail_payload(row)}
