"""Phase N — personal-stream endpoints.

North-star §"The canonical interaction". The per-user personal stream is
the v2 primary surface. These endpoints are thin wrappers around
PersonalStreamService:

  * POST /api/personal/{project_id}/post          — user posts; edge
                                                   metabolizes
  * POST /api/personal/route/{proposal_id}/confirm — "Ask X" click → dispatch
  * GET  /api/personal/{project_id}/messages      — list with parsed
                                                   route-proposal metadata

All routes require a signed-in user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, PersonalStreamService

router = APIRouter(prefix="/api/personal", tags=["personal"])


class PostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
    # Per-stream context-source toggles from StreamContextPanel.
    # Keys: graph / kb / dms / audit. Absent → server defaults.
    scope: dict[str, bool] | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Draft body. Short drafts (<10 chars) short-circuit server-side with
    # {"kind": "silent_preview"} so the min_length guard here is just to
    # reject totally empty payloads — the value gate lives in the service.
    body: str = Field(min_length=0, max_length=4000)


class ConfirmRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1, max_length=64)
    # Optional refined B-facing framing the user edited in the route-
    # proposal card. When present, this overrides the original
    # proposal.framing so the routed signal carries an A→B-voice ask
    # (e.g. "do you have bandwidth for the auth rewrite?") instead of
    # A's sub-agent's prose written for A. Empty / null = use original.
    refined_framing: str | None = Field(default=None, max_length=4000)


def _get_service(request: Request) -> PersonalStreamService:
    return request.app.state.personal_service


@router.post("/{project_id}/post")
async def post_personal_turn(
    project_id: str,
    body: PostRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.post(
        user_id=user.id,
        project_id=project_id,
        body=body.body,
        scope=body.scope,
    )
    if not result.get("ok"):
        err = result.get("error", "post_failed")
        status_map = {
            "project_not_found": 404,
            "not_a_project_member": 403,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.post("/{project_id}/preview")
async def post_personal_preview(
    project_id: str,
    body: PreviewRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Pre-commit rehearsal (vision.md §5.3).

    Debounced keystroke endpoint: returns the EdgeAgent classification
    the draft *would* produce, without persisting anything. 429 on
    rate-limit so the caller can back off.
    """
    service = _get_service(request)
    result = await service.preview(
        user_id=user.id, project_id=project_id, body=body.body
    )
    if not result.get("ok"):
        err = result.get("error", "preview_failed")
        if err == "rate_limited":
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "rate_limited",
                    "retry_after_ms": result.get("retry_after_ms", 0),
                },
            )
        status_map = {
            "project_not_found": 404,
            "not_a_project_member": 403,
            "preview_failed": 502,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.post("/route/{proposal_id}/confirm")
async def post_confirm_route(
    proposal_id: str,
    body: ConfirmRouteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.confirm_route(
        proposal_id=proposal_id,
        source_user_id=user.id,
        target_user_id=body.target_user_id,
        refined_framing=body.refined_framing,
    )
    if not result.get("ok"):
        err = result.get("error", "confirm_failed")
        status_map = {
            "proposal_not_found": 404,
            "proposal_not_ours": 403,
            "target_not_in_proposal": 400,
            "cannot_route_to_self": 400,
            "target_not_found": 404,
            "source_not_project_member": 403,
            "target_not_project_member": 400,
            "option_generation_failed": 502,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.get("/{project_id}/messages")
async def get_personal_messages(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.list_messages(
        user_id=user.id, project_id=project_id, limit=limit
    )
    if not result.get("ok"):
        err = result.get("error", "list_failed")
        raise HTTPException(status_code=400, detail=err)
    return result
