"""Phase B.1 — v0.6.2 Documents / KB surface (API_CONTRACT §"Documents / KB").

Wraps `KbItemService` and `RenderService` in the v0.6.2 contract. The
KB browser becomes /docs in v0.6.2; every existing `KbItemRow` is a
Document on the wire.

Endpoints:

  * GET  /api/documents?scope_id=...&type=all
  * GET  /api/scopes/{scope_id}/project-brief
  * POST /api/documents/{id}/publish

The project-brief endpoint **must** always return a `document_id`
field. INVARIANT_TESTS.md §"Project not routable as page" asserts
`brief.document_id` is defined — even when the scope has no proper
brief yet. We fall back to the most-recently-edited "brief"-titled
item, then to any document, then to null only as last resort with a
TODO marker.

The publish endpoint returns `memory_candidates` (proposed memory
atoms born from the published doc). It **never** returns accepted
memory — doctrine (DESIGN_LOCK.md): memory crystallization is a
separate authority decision via `/api/memory-candidates/{id}/accept`.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from workgraph_persistence import (
    ProjectMemberRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    KbItemError,
    KbItemService,
)

router = APIRouter(prefix="/api", tags=["documents"])


# ---- enums ----------------------------------------------------------------

DocumentTypeFilter = Literal["all", "brief", "note", "attachment"]


# ---- request shapes -------------------------------------------------------


class PublishDocumentRequest(BaseModel):
    """Optional publish flags. v0.6.2 publish is idempotent (status flips
    to 'published' and proposed memory candidates are generated).
    """

    model_config = ConfigDict(extra="forbid")


# ---- response shapes (C1-C) -----------------------------------------------
# These mirror the runtime payload built by `_doc_from_kb` below — NOT a
# frontend assumption. Required fields map to non-null KbItemRow columns
# (id PK, title, scope, status) + the always-bool is_project_brief; the rest
# are `.get()`-sourced and may be null. The FE features/documents/types.ts
# Document/DocumentListResponse already match this shape field-for-field.


class Document(BaseModel):
    document_id: str
    scope_id: str | None = None
    title: str
    scope: str  # 'personal' | 'group'
    status: str  # 'draft' | 'published' | 'archived' | 'pending-review'
    is_project_brief: bool
    updated_at: str | None = None
    created_at: str | None = None
    source: str | None = None
    owner_user_id: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[Document]
    scope_id: str
    type: DocumentTypeFilter


# ---- helpers --------------------------------------------------------------


def _kb_service(request: Request) -> KbItemService:
    return request.app.state.kb_item_service


def _looks_like_brief(item: dict[str, Any]) -> bool:
    """Match heuristic for the project brief.

    Convention: a KbItemRow with `is_project_brief=True` flag (Phase
    B.6 feature) wins. Fallback: title containing "brief" / "概要" /
    "项目简介" (case-insensitive).
    """
    if item.get("is_project_brief") is True:
        return True
    title = (item.get("title") or "").lower()
    return any(kw in title for kw in ("brief", "概要", "项目简介", "项目brief"))


def _doc_from_kb(item: dict[str, Any]) -> dict[str, Any]:
    """Re-shape a KbItemRow dict as a v0.6.2 Document (list shape).

    Keeps the list payload light — body content + attachment metadata
    live on the singleton wire (`_doc_full_from_kb`) only.
    """
    return {
        "document_id": item.get("id"),
        "scope_id": item.get("project_id"),
        "title": item.get("title"),
        "scope": item.get("scope"),  # personal | group
        "status": item.get("status"),
        "is_project_brief": bool(item.get("is_project_brief")) or _looks_like_brief(item),
        "updated_at": item.get("updated_at"),
        "created_at": item.get("created_at"),
        "source": item.get("source"),
        "owner_user_id": item.get("owner_user_id"),
    }


def _doc_full_from_kb(item: dict[str, Any]) -> dict[str, Any]:
    """Singleton shape — list shape + body + attachment metadata.

    Used by GET /api/documents/:id so the detail page renders without
    a follow-up fetch.
    """
    base = _doc_from_kb(item)
    base["content_md"] = item.get("content_md")
    base["attachment"] = item.get("attachment")
    base["folder_id"] = item.get("folder_id")
    return base


# ---- endpoints ------------------------------------------------------------


@router.get("/documents", response_model=DocumentListResponse)
async def get_documents(
    request: Request,
    scope_id: str = Query(min_length=1, max_length=64),
    type: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """List documents in a scope.

    Wraps KbItemService.list_visible. The `type` filter is a wire-shape
    placeholder for B.1: 'all' returns every visible KB item; other
    values pass through but the service doesn't yet branch on them.

    TODO(Phase B.2): real type filter (brief / note / attachment) once
    KbItemRow grows a `document_kind` column. For B.1 the filter is
    advisory.
    """
    service = _kb_service(request)
    try:
        items = await service.list_visible(
            project_id=scope_id, viewer_user_id=user.id, limit=limit
        )
    except KbItemError as err:
        status = err.status or 400
        raise HTTPException(status_code=status, detail=err.code) from err

    docs = [_doc_from_kb(it) for it in items]

    # Best-effort type filter — purely client-shaping until B.2.
    if type == "brief":
        docs = [d for d in docs if d["is_project_brief"]]
    elif type in {"note", "attachment"}:
        # TODO(Phase B.2): branch on KbItemRow.document_kind column.
        pass

    return {"documents": docs, "scope_id": scope_id, "type": type}


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Phase RW-8 — read-only single-document detail.

    Wraps KbItemService.get (membership-checked). Returns the same
    Document envelope as each row in the list endpoint plus the body
    (`content_md`) and attachment block so the /docs/:id page renders
    without a follow-up fetch. No mutation, no publish.
    """
    service = _kb_service(request)
    try:
        item = await service.get(item_id=document_id, viewer_user_id=user.id)
    except KbItemError as err:
        status = err.status or 400
        raise HTTPException(status_code=status, detail=err.code) from err
    return {"document": _doc_full_from_kb(item)}


@router.get("/scopes/{scope_id}/project-brief")
async def get_project_brief(
    scope_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Return the pinned project brief for a scope.

    INVARIANT_TESTS.md §"Project not routable as page":

        const brief = await get("/api/scopes/scope_tikhub/project-brief");
        expect(brief.document_id).toBeDefined();

    Resolution order (defensive — the response must always carry a
    `document_id` field, even if no proper brief exists):
      1. KbItemRow with `is_project_brief=True` (Phase B.6 feature
         flag — not wired yet, but cheap to honor)
      2. Most-recently-edited KbItemRow whose title looks like a
         brief (`brief` / `概要` / `项目简介`)
      3. Most-recently-edited group-scope KbItemRow in the scope
      4. `document_id: null` with a TODO marker — last resort
    """
    # Membership gate.
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        if not await ProjectMemberRepository(session).is_member(
            scope_id, user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_scope_member")

    service = _kb_service(request)
    try:
        items = await service.list_visible(
            project_id=scope_id, viewer_user_id=user.id, limit=200
        )
    except KbItemError as err:
        status = err.status or 400
        raise HTTPException(status_code=status, detail=err.code) from err

    docs = [_doc_from_kb(it) for it in items]

    # 1) explicit flag
    flagged = [d for d in docs if d.get("is_project_brief")]
    if flagged:
        flagged.sort(
            key=lambda d: d.get("updated_at") or d.get("created_at") or "",
            reverse=True,
        )
        return {
            "document_id": flagged[0]["document_id"],
            "scope_id": scope_id,
            "brief": flagged[0],
            "fallback_used": False,
        }

    # 2) title heuristic
    titled = [d for d in docs if _looks_like_brief(d)]
    if titled:
        titled.sort(
            key=lambda d: d.get("updated_at") or d.get("created_at") or "",
            reverse=True,
        )
        return {
            "document_id": titled[0]["document_id"],
            "scope_id": scope_id,
            "brief": titled[0],
            "fallback_used": True,
            "fallback_reason": "title_heuristic",
        }

    # 3) most recent group-scope doc
    group_docs = [d for d in docs if d.get("scope") == "group"]
    if group_docs:
        group_docs.sort(
            key=lambda d: d.get("updated_at") or d.get("created_at") or "",
            reverse=True,
        )
        return {
            "document_id": group_docs[0]["document_id"],
            "scope_id": scope_id,
            "brief": group_docs[0],
            "fallback_used": True,
            "fallback_reason": "most_recent_group_doc",
        }

    # 4) any doc
    if docs:
        docs.sort(
            key=lambda d: d.get("updated_at") or d.get("created_at") or "",
            reverse=True,
        )
        return {
            "document_id": docs[0]["document_id"],
            "scope_id": scope_id,
            "brief": docs[0],
            "fallback_used": True,
            "fallback_reason": "most_recent_doc",
        }

    # 5) last resort — document_id is still defined (=null) per the
    # invariant. TODO(Phase B.6): wire the `is_project_brief` flag at
    # scope-create time so this branch is never hit.
    return {
        "document_id": None,
        "scope_id": scope_id,
        "brief": None,
        "fallback_used": True,
        "fallback_reason": "no_documents_in_scope",
        "_todo": "Phase B.6 wires is_project_brief flag on scope-create",
    }


@router.post("/documents/{document_id}/publish")
async def post_publish_document(
    document_id: str,
    request: Request,
    _body: PublishDocumentRequest | None = None,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Publish a document. Returns proposed memory candidates only.

    Doctrine (DESIGN_LOCK.md): publish proposes memory; it never
    accepts memory. The returned `memory_candidates` is a list of
    proposal envelopes; each one must be authority-accepted via
    `POST /api/memory-candidates/{id}/accept` to crystallize.

    Implementation: flip the underlying KbItemRow's status to
    'published' via KbItemService.update, then return any
    candidate memory atoms the publish flow surfaced. For Phase B.1
    the memory_candidates list is empty — Phase C wires the actual
    distillation pipeline that emits candidates on publish.
    """
    service = _kb_service(request)
    try:
        updated = await service.update(
            item_id=document_id,
            actor_user_id=user.id,
            title=None,
            content_md=None,
            status="published",
            folder_id=None,
        )
    except KbItemError as err:
        status = err.status or 400
        raise HTTPException(status_code=status, detail=err.code) from err

    item = updated.get("item") if isinstance(updated, dict) else updated
    return {
        "document": _doc_from_kb(item or {}),
        # TODO(Phase C): wire MembraneService.propose_memory_from_document
        # to populate this. Each entry is a MemoryCandidate proposal
        # envelope (never accepted memory — doctrine).
        "memory_candidates": [],
        "mutates_state": True,  # publish itself mutates; memory does not
    }
