"""Phase B.1 — v0.6.2 Scope APIs (API_CONTRACT §"Scope APIs").

A "scope" in v0.6.2 is the API-side alias for what the DB still calls a
project. `id` = `project_id`; no DB column renames (CLAUDE.md §
Architectural invariants).

Endpoints:

  * GET  /api/scopes              — list of scopes the current user is in
  * GET  /api/user/active-scope   — current selection
  * POST /api/user/active-scope   — mutate

Active-scope state piggybacks on `UserRow.profile.active_scope` so we
inherit the no-migration approach the v-next prefs blob already uses
(see `routers/vnext_prefs.py`). Shape inside the blob:

    {"scope_id": str | None, "scope_mode": RetrievalScopeMode,
     "updated_at": iso8601}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import UserRepository, session_scope

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

router = APIRouter(tags=["scopes"])


# RetrievalScopeMode mirror — must stay in sync with schemas.graphflow.json.
# Limited set so the FE select can't drift the wire contract.
ScopeMode = Literal["current_focus", "all_accessible", "no_focus"]
_ALLOWED_SCOPE_MODES: set[str] = {"current_focus", "all_accessible", "no_focus"}

# v0.6.2 surfaces only project-as-cell scopes today. The `tier` field
# stays in the response so the FE can branch on it once enterprise /
# department / personal tiers ship as first-class scope kinds.
_DEFAULT_SCOPE_TIER = "cell"


# ---- response shapes ------------------------------------------------------


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str  # = project_id (v0.6.2 API alias; no DB rename)
    title: str
    role: str  # owner | member | contractor | observer
    tier: Literal["personal", "cell", "department", "enterprise"]


class ActiveScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str | None
    scope_mode: ScopeMode
    updated_at: str | None


# ---- request shapes -------------------------------------------------------


class ActiveScopeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str | None = Field(default=None, max_length=64)
    scope_mode: ScopeMode


# ---- helpers --------------------------------------------------------------


def _default_active_scope() -> dict:
    """Default active-scope blob — what GET returns when nothing is
    persisted yet. `current_focus` matches the v0.6.2 FE default
    landing mode (focus on the user's last-touched scope).
    """
    return {
        "scope_id": None,
        "scope_mode": "current_focus",
        "updated_at": None,
    }


def _shape_active_scope(blob: dict | None) -> dict:
    """Overlay persisted blob on defaults; reject unknown scope_mode
    values so a stale write never poisons the response."""
    out = _default_active_scope()
    if not isinstance(blob, dict):
        return out
    sid = blob.get("scope_id")
    if sid is None or isinstance(sid, str):
        out["scope_id"] = sid
    mode = blob.get("scope_mode")
    if isinstance(mode, str) and mode in _ALLOWED_SCOPE_MODES:
        out["scope_mode"] = mode
    updated = blob.get("updated_at")
    if isinstance(updated, str):
        out["updated_at"] = updated
    return out


def _get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


# ---- endpoints ------------------------------------------------------------


@router.get("/api/scopes", response_model=list[Scope])
async def list_scopes(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[Scope]:
    """List the scopes the current user has membership in.

    Wraps ProjectService.list_for_user — same membership semantics as
    `GET /api/projects`, re-shaped to the v0.6.2 Scope contract. Today
    every scope is a project-as-cell, so `tier` is always "cell".
    """
    service = _get_project_service(request)
    projects = await service.list_for_user(user.id)
    return [
        Scope(
            id=p["id"],
            title=p["title"],
            role=str(p.get("role") or "member"),
            tier=_DEFAULT_SCOPE_TIER,
        )
        for p in projects
    ]


@router.get("/api/user/active-scope", response_model=ActiveScopeResponse)
async def get_active_scope(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> ActiveScopeResponse:
    """Return the user's active-scope selection.

    Stored on `UserRow.profile.active_scope` (JSON blob, same pattern
    as vnext_prefs — no migration needed).
    """
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        row = await UserRepository(session).get(user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        blob = (row.profile or {}).get("active_scope")
        return ActiveScopeResponse(**_shape_active_scope(blob))


@router.post("/api/user/active-scope", response_model=ActiveScopeResponse)
async def set_active_scope(
    body: ActiveScopeUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> ActiveScopeResponse:
    """Mutate the user's active-scope selection.

    Membership check: when `scope_id` is set, the caller must be a
    member of that scope (= project). `scope_id=None` is legal — it
    represents "no focus" / cross-scope mode.
    """
    # Membership gate when a concrete scope is requested. `no_focus`
    # with scope_id=None skips the check — there's no scope to gate on.
    if body.scope_id is not None:
        proj_service = _get_project_service(request)
        is_member = await proj_service.is_member(
            project_id=body.scope_id, user_id=user.id
        )
        if not is_member:
            raise HTTPException(
                status_code=403, detail="not_a_scope_member"
            )

    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        repo = UserRepository(session)
        row = await repo.get(user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")

        profile = dict(row.profile or {})
        now = datetime.now(timezone.utc).isoformat()
        new_blob = {
            "scope_id": body.scope_id,
            "scope_mode": body.scope_mode,
            "updated_at": now,
        }
        profile["active_scope"] = new_blob
        row.profile = profile
        await session.flush()

        return ActiveScopeResponse(**_shape_active_scope(new_blob))
