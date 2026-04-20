"""Phase B (v2) — user profile endpoints.

North-star §"Profile as first-class primitive":
  GET  /api/users/me  returns id, username, display_name, display_language,
                      and the full profile JSON (declared_abilities,
                      role_hints, signal_tally)
  PATCH /api/users/me partial update of declared_abilities / role_hints /
                      display_language.

Signal-tally is computed from activity in v2 and is not directly editable
by the user. We return it on GET so the UI can surface observed emissions
alongside self-declared abilities (the "gap is itself information" per
north-star).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import UserRepository, session_scope

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser
from workgraph_api.services.profile_tallies import compute_profile

router = APIRouter(prefix="/api", tags=["users"])


# Allowed languages kept narrow in v1 — north-star §"display_language" lists
# en + zh. Expand as we localize more chrome.
_ALLOWED_LANGUAGES = {"en", "zh"}


class PatchProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_abilities: list[str] | None = Field(default=None, max_length=64)
    role_hints: list[str] | None = Field(default=None, max_length=16)
    display_language: str | None = Field(default=None, min_length=2, max_length=8)


def _shape_user(row) -> dict:
    return {
        "id": row.id,
        "username": row.username,
        "display_name": row.display_name,
        "display_language": row.display_language,
        "profile": row.profile or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/users/me")
async def get_me(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        row = await UserRepository(session).get(user.id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        return _shape_user(row)


# Observed-profile tallies. Compute-on-read, no schema mutation. Pairs
# with GET /api/users/me (self-declared) so the client can render both
# halves of the response profile — the gap is itself information per
# docs/north-star.md §"Profile as first-class primitive".
@router.get("/users/me/profile")
async def get_my_profile(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        tallies = await compute_profile(session, user.id)
    return tallies.to_dict()


@router.patch("/users/me")
async def patch_me(
    body: PatchProfileRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    if (
        body.display_language is not None
        and body.display_language not in _ALLOWED_LANGUAGES
    ):
        # 422 — matches FastAPI validation convention for rejected enum values.
        raise HTTPException(
            status_code=422,
            detail=f"display_language must be one of {sorted(_ALLOWED_LANGUAGES)}",
        )

    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        row = await UserRepository(session).update_profile(
            user.id,
            declared_abilities=body.declared_abilities,
            role_hints=body.role_hints,
            display_language=body.display_language,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        return _shape_user(row)
