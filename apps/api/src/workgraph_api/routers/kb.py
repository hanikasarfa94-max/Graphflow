"""Phase Q / 3.A — KB browseable + hierarchical endpoints.

Phase Q shipped flat listing (north-star Q.6). Phase 3.A layers a
folder tree + per-item license overrides on top:

  * GET    /api/projects/{pid}/kb                      — flat list (Q.6)
  * GET    /api/projects/{pid}/kb/{item_id}            — item detail (Q.6)
  * POST   /api/projects/{pid}/kb/folders              — create folder (full-tier)
  * GET    /api/projects/{pid}/kb/tree                 — tree payload
  * PATCH  /api/projects/{pid}/kb/items/{item_id}/folder       — move item (member)
  * PATCH  /api/projects/{pid}/kb/folders/{fid}/parent — reparent (owner; 409 on cycle)
  * DELETE /api/projects/{pid}/kb/folders/{fid}        — delete (owner; 409 if non-empty)
  * PUT    /api/projects/{pid}/kb/items/{item_id}/license      — license override (owner)

Auth: project member required (observer-tier can read). Owner/full-tier
gates live in KbHierarchyService; the router translates structured
service errors into status codes.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from workgraph_persistence import (
    KbIngestRepository,
    KbItemRepository,
    KbItemRow,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    KbHierarchyService,
    ProjectService,
)

router = APIRouter(prefix="/api", tags=["kb"])


# Mapping from service-layer error codes → HTTP status. Owner /
# full-tier gates surface as 403; name conflicts and non-empty-delete
# / cycle-reject surface as 409 so the frontend can distinguish
# permission failures from legitimate preconditions.
_KB_ERROR_STATUS: dict[str, int] = {
    "not_a_member": 403,
    "forbidden": 403,
    "folder_not_found": 404,
    "parent_not_found": 404,
    "item_not_found": 404,
    "cannot_delete_root": 409,
    "folder_not_empty": 409,
    "name_conflict": 409,
    "cycle": 409,
    "name_required": 400,
    "name_too_long": 400,
    "invalid_tier": 400,
}


def _handle_kb(result: dict) -> dict:
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_KB_ERROR_STATUS.get(err, 400), detail=err
        )
    return result


def _kb_list_payload(row: KbItemRow) -> dict:
    """Compact list-view payload for a KB item, polymorphic on `source`.

    Two row families share kb_items post-fold:
      * source='ingest' — externally-pulled signals; summary lives in
        classification_json, body in raw_content.
      * source in {'manual','upload','llm'} — user-authored notes;
        title is canonical, body in content_md. We synthesize a
        source_kind ('kb-note' / 'kb-personal') so list filters and
        the FE renderer treat them as first-class entries.
    """
    if row.source == "ingest":
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
    src_kind = "kb-personal" if row.scope == "personal" else "kb-note"
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_kind": src_kind,
        "source_identifier": None,
        "summary": (row.title or "") + (
            ": " + (row.content_md or "")[:160] if row.content_md else ""
        ),
        "tags": [],
        "status": row.status,
        "ingested_by_user_id": row.owner_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _kb_detail_payload(row: KbItemRow) -> dict:
    """Full-detail payload for a single KB item.

    The kb_items table is the unified store post-migration 0022 — both
    user-authored items (save-as-kb / paste / upload) and ingested
    membrane signals live here. Two field families:

      ingest-shape: source_kind, source_identifier, raw_content
      user-shape:   title, content_md, summary, scope, owner_user_id

    User-authored rows have source in {'manual','upload','llm'} and
    populate the user-shape fields; ingest-shape ones are NULL. The
    pre-fold detail handler only emitted the ingest-shape, which made
    every save-as-kb draft render as a blank page (the QA report
    "every KB is empty for approve"). We emit BOTH families now and
    let the FE pick based on what's populated.
    """
    classification = dict(row.classification_json or {})
    # Synthesize summary/tags so the FE meta panel renders consistently
    # whether the row is an LLM-classified ingest (carries summary+tags
    # in classification_json) or a user-authored note (has title+body).
    # Without this, KbItemDetail's "classification" panel renders empty
    # for ingest rows because the FE reads `summary` / `tags` / `classification_json`
    # at the top level — the previous payload only emitted `classification`.
    summary_val = classification.get("summary") if isinstance(classification.get("summary"), str) else ""
    if not summary_val and row.title:
        summary_val = row.title
        if row.content_md:
            summary_val = f"{row.title}: {row.content_md[:160]}"
    tags_val = classification.get("tags")
    if not isinstance(tags_val, list):
        tags_val = []
    return {
        "id": row.id,
        "project_id": row.project_id,
        # Ingest-shape (membrane signals). Null for user-authored items.
        "source_kind": row.source_kind,
        "source_identifier": row.source_identifier,
        "raw_content": row.raw_content,
        # User-authored shape (save-as-kb, paste, upload). Null for ingest.
        "title": row.title,
        "content_md": row.content_md,
        "scope": row.scope,
        "source": row.source,
        "owner_user_id": row.owner_user_id,
        # Common metadata. Field is `classification_json` to match the FE
        # KbItemDetail interface (renamed from `classification`).
        "classification_json": classification,
        "summary": summary_val,
        "tags": tags_val,
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
    """List KB items for a project (post-fold: returns both ingests and
    user-authored group notes).

    Excludes status='rejected' (signal audit history) and 'archived'
    (retired notes). Also excludes draft / pending-review by default
    so the list is the canonical view, not the staging queue. Use
    `/kb/tree` for the curation surface that shows drafts.

    `query` does case-insensitive substring match across summary,
    title, content, raw_content, tags, and source_identifier — works
    uniformly across both row families. `source_kind` filters on
    origin channel; the synthesized values 'kb-note' / 'kb-personal'
    let callers distinguish user-authored from ingested.
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    q = (query or "").strip().lower()

    async with session_scope(request.app.state.sessionmaker) as session:
        # Single-table read post-fold — KbItemRepository returns both
        # ingest rows and user-authored group notes.
        rows = await KbItemRepository(session).list_group_for_project(
            project_id=project_id, limit=500
        )

    # Hide non-canonical states from the list surface; the tree handles
    # the staging queue with chips.
    rows = [r for r in rows if r.status not in ("rejected", "archived", "draft", "pending-review")]

    # source_kind filter operates on either the raw column (ingests) or
    # the synthesized value ('kb-note'/'kb-personal') we expose in the
    # payload — match both so the FE filter chip works whether the user
    # picks 'rss' or 'kb-note'.
    if source_kind:
        def _matches(r: KbItemRow) -> bool:
            if r.source == "ingest":
                return r.source_kind == source_kind
            synth = "kb-personal" if r.scope == "personal" else "kb-note"
            return synth == source_kind

        rows = [r for r in rows if _matches(r)]

    if q:
        filtered: list[KbItemRow] = []
        for r in rows:
            if r.source == "ingest":
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
            else:
                haystack = " ".join(
                    [
                        (r.title or "").lower(),
                        (r.content_md or "").lower(),
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


# NOTE: the /kb/tree + /kb/folders + /kb/items/... routes below MUST
# be registered before the catch-all /kb/{item_id}, otherwise FastAPI
# treats 'tree' / 'folders' / 'items' as item_ids and hands back 404.
# The Phase 3.A additions at the end of this file stay paired with
# this comment — if another route lands between, check ordering first.


def _kb_service(request: Request) -> KbHierarchyService:
    return request.app.state.kb_hierarchy_service


@router.get("/projects/{project_id}/kb/tree")
async def get_kb_tree(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Return the folder tree + placed items for a project.

    Members only. Flat list with parent_id pointers — the client
    nests in-memory. See KbHierarchyService.get_tree for the payload
    shape.
    """
    service = _kb_service(request)
    return _handle_kb(
        await service.get_tree(
            project_id=project_id, user_id=user.id
        )
    )


@router.post("/projects/{project_id}/kb/folders")
async def create_kb_folder(
    project_id: str,
    request: Request,
    payload: dict = Body(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """Create a folder. Full-tier member required.

    Body: {name: str, parent_folder_id: str|null}
    """
    name = payload.get("name") or ""
    parent_folder_id = payload.get("parent_folder_id")
    service = _kb_service(request)
    return _handle_kb(
        await service.create_folder(
            project_id=project_id,
            user_id=user.id,
            name=str(name),
            parent_folder_id=(
                str(parent_folder_id)
                if parent_folder_id is not None
                else None
            ),
        )
    )


@router.patch("/projects/{project_id}/kb/folders/{folder_id}/parent")
async def reparent_kb_folder(
    project_id: str,
    folder_id: str,
    request: Request,
    payload: dict = Body(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """Move a folder under a new parent. Owner only.

    Cycle detection lives in the service; we forward 409 to the
    client without re-checking — the service is the single writer
    and a second check here would just be duplicated logic that
    could drift.

    Body: {new_parent_id: str|null}
    """
    new_parent_id = payload.get("new_parent_id")
    service = _kb_service(request)
    return _handle_kb(
        await service.reparent_folder(
            project_id=project_id,
            user_id=user.id,
            folder_id=folder_id,
            new_parent_id=(
                str(new_parent_id)
                if new_parent_id is not None
                else None
            ),
        )
    )


@router.delete("/projects/{project_id}/kb/folders/{folder_id}")
async def delete_kb_folder(
    project_id: str,
    folder_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Delete an empty folder. Owner only. 409 if non-empty or root."""
    service = _kb_service(request)
    return _handle_kb(
        await service.delete_folder(
            project_id=project_id,
            user_id=user.id,
            folder_id=folder_id,
        )
    )


@router.patch("/projects/{project_id}/kb/items/{item_id}/folder")
async def move_kb_item(
    project_id: str,
    item_id: str,
    request: Request,
    payload: dict = Body(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """Move a KB item to a different folder. Member required.

    Body: {folder_id: str}
    """
    folder_id = payload.get("folder_id")
    if not folder_id:
        raise HTTPException(status_code=400, detail="folder_id_required")
    service = _kb_service(request)
    return _handle_kb(
        await service.move_item(
            project_id=project_id,
            user_id=user.id,
            item_id=item_id,
            folder_id=str(folder_id),
        )
    )


@router.put("/projects/{project_id}/kb/items/{item_id}/license")
async def set_kb_item_license(
    project_id: str,
    item_id: str,
    request: Request,
    payload: dict = Body(...),
    user: AuthenticatedUser = Depends(require_user),
):
    """Set or clear a per-item license tier override. Owner only.

    Body: {license_tier: 'full'|'task_scoped'|'observer'|null}
    Passing null clears the override (item reverts to project tier).
    """
    license_tier = payload.get("license_tier")
    service = _kb_service(request)
    return _handle_kb(
        await service.set_item_license(
            project_id=project_id,
            user_id=user.id,
            item_id=item_id,
            license_tier=(
                str(license_tier) if license_tier is not None else None
            ),
        )
    )


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
        row = await KbIngestRepository(session).get(item_id)

    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="kb_item_not_found")
    if row.status == "rejected":
        # Rejected items are audit history; don't surface them in the
        # live KB even on direct GET.
        raise HTTPException(status_code=404, detail="kb_item_not_found")

    return {"ok": True, "item": _kb_detail_payload(row)}
