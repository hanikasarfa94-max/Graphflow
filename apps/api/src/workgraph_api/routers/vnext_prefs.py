"""Shell v-Next user preferences (spec §11 E-6 / E-7 / E-9).

All v-next prefs live as a single JSON blob on `UserRow.profile.vnext_prefs`
to avoid an alembic migration. The blob carries:

  * auto_dispatch_streams: dict[stream_id, bool]
      Per-stream override for the composer's "auto-dispatch" toggle (E-6).
      Missing key → use default (true). Storing only overrides keeps the
      blob small.

  * thinking_mode: "deep" | "fast"
      User's last-selected thinking-mode hint (E-7). Default "deep" so
      the toggle starts in the same place every session.

  * workbench_layout: dict[stream_kind, list[panel_kind]]
      Per-stream-kind panel order + presence (E-9). Empty list = use
      default. stream_kind ∈ {"personal", "room", "dm"}.

Endpoints:
  * GET /api/vnext/prefs                 — full blob with defaults applied
  * PUT /api/vnext/prefs                 — partial update; merge into profile

Per-stream auto_dispatch + per-message thinking_mode hints can also be
sent as request fields by the composer; this endpoint is the persistence
layer the composer reads on mount and writes on toggle.

Note: the LLM-side wire-through for thinking_mode (model temperature /
tier selection) is explicitly defer-to-follow-up per spec §11 E-7
("v1 ships the select as client-side state only; backend uses fixed
model"). v1 persistence ensures the toggle survives reload.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import UserRepository, session_scope

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser

router = APIRouter(prefix="/api/vnext", tags=["vnext-prefs"])


# Allowed values — kept narrow because the FE only sends these.
_ALLOWED_THINKING_MODES = {"deep", "fast"}
_ALLOWED_STREAM_KINDS = {"personal", "room", "dm"}
_ALLOWED_PANEL_KINDS = {"tasks", "knowledge", "skills", "requests", "workflow"}


class WorkbenchLayoutUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_kind: Literal["personal", "room", "dm"]
    # Order matters — first item renders leftmost in the panel grid.
    # Empty list resets to "use default". Duplicate kinds are dropped
    # at write time so the layout dict never carries dupes.
    panels: list[Literal["tasks", "knowledge", "skills", "requests", "workflow"]] = (
        Field(default_factory=list, max_length=10)
    )


class AutoDispatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream_id: str = Field(min_length=1, max_length=64)
    enabled: bool


class PrefsUpdateRequest(BaseModel):
    """Partial update — every field is optional. Unset fields stay as-is."""

    model_config = ConfigDict(extra="forbid")

    thinking_mode: Literal["deep", "fast"] | None = None
    auto_dispatch: AutoDispatchUpdate | None = None
    workbench: WorkbenchLayoutUpdate | None = None


def _defaults() -> dict:
    """Default vnext_prefs blob — what GET returns when nothing is persisted.

    Workbench defaults match the prototype's toolShelf order so a fresh
    user sees the same layout the prototype showed.
    """
    return {
        "auto_dispatch_streams": {},
        "thinking_mode": "deep",
        "workbench_layout": {
            "personal": ["tasks", "knowledge", "skills", "workflow"],
            "room": [
                "tasks",
                "knowledge",
                "requests",
                "skills",
                "workflow",
            ],
            "dm": [],
        },
    }


def _shape(prefs_blob: dict) -> dict:
    """Overlay persisted blob on top of defaults so missing keys still
    return a sensible value to the FE."""
    out = _defaults()
    if isinstance(prefs_blob.get("auto_dispatch_streams"), dict):
        out["auto_dispatch_streams"] = {
            str(k): bool(v)
            for k, v in prefs_blob["auto_dispatch_streams"].items()
        }
    mode = prefs_blob.get("thinking_mode")
    if isinstance(mode, str) and mode in _ALLOWED_THINKING_MODES:
        out["thinking_mode"] = mode
    layout = prefs_blob.get("workbench_layout")
    if isinstance(layout, dict):
        for kind in _ALLOWED_STREAM_KINDS:
            v = layout.get(kind)
            if isinstance(v, list):
                # Filter to allowed panel kinds and de-dupe preserving order.
                seen: set[str] = set()
                filtered: list[str] = []
                for p in v:
                    if (
                        isinstance(p, str)
                        and p in _ALLOWED_PANEL_KINDS
                        and p not in seen
                    ):
                        filtered.append(p)
                        seen.add(p)
                out["workbench_layout"][kind] = filtered
    return out


@router.get("/prefs")
async def get_prefs(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        row = await UserRepository(session).get(user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        blob = (row.profile or {}).get("vnext_prefs") or {}
        return _shape(blob if isinstance(blob, dict) else {})


@router.put("/prefs")
async def put_prefs(
    body: PrefsUpdateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        repo = UserRepository(session)
        row = await repo.get(user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")

        profile = dict(row.profile or {})
        existing = profile.get("vnext_prefs")
        prefs = dict(existing) if isinstance(existing, dict) else {}

        # E-7: thinking_mode default.
        if body.thinking_mode is not None:
            prefs["thinking_mode"] = body.thinking_mode

        # E-6: per-stream auto-dispatch override. The default is "enabled"
        # so we only persist explicit overrides — and we strip the key
        # entirely when the user toggles back to default-on. This keeps
        # the blob from growing unboundedly as users churn through streams.
        if body.auto_dispatch is not None:
            adm_existing = prefs.get("auto_dispatch_streams")
            adm = (
                dict(adm_existing) if isinstance(adm_existing, dict) else {}
            )
            if body.auto_dispatch.enabled:
                adm.pop(body.auto_dispatch.stream_id, None)
            else:
                adm[body.auto_dispatch.stream_id] = False
            prefs["auto_dispatch_streams"] = adm

        # E-9: workbench layout per stream_kind. Empty list resets to
        # default (delete the key). De-dupe preserving order.
        if body.workbench is not None:
            layout_existing = prefs.get("workbench_layout")
            layout = (
                dict(layout_existing)
                if isinstance(layout_existing, dict)
                else {}
            )
            seen: set[str] = set()
            filtered: list[str] = []
            for p in body.workbench.panels:
                if p not in seen:
                    filtered.append(p)
                    seen.add(p)
            if filtered:
                layout[body.workbench.stream_kind] = filtered
            else:
                layout.pop(body.workbench.stream_kind, None)
            prefs["workbench_layout"] = layout

        profile["vnext_prefs"] = prefs
        row.profile = profile
        await session.flush()

        return _shape(prefs)
