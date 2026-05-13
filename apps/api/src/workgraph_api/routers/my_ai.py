"""Phase B.1 — v0.6.2 My AI surface (API_CONTRACT §"My AI APIs").

Thin wrapper over PersonalStreamService that re-shapes the existing
per-user agent surface as the cross-project My AI inbox + composer.

Endpoints:

  * GET  /api/my-ai/landing?scope_id=...
      Grounded re-entry items + Ready to Share drafts. `scope_id=null`
      means "no scope filter" — return cross-project items.

  * POST /api/my-ai/messages
      Assistant message + proposals (routing_suggestion, task_candidate,
      ...). Wraps PersonalStreamService.post.

`scope_id` is the v0.6.2 API alias for the underlying `project_id`
column (see CLAUDE.md §Architectural invariants — no DB column renames).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, PersonalStreamService

router = APIRouter(prefix="/api/my-ai", tags=["my-ai"])


# ---- response shapes ------------------------------------------------------


class GroundedItem(BaseModel):
    """One re-entry card on the My AI landing surface.

    Always a reference to a real object (decision / task / kb-item /
    message). Never a freeform LLM summary — per API_CONTRACT.md:
    "Grounded items must be real objects, not freeform LLM summaries."
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str  # decision | task | kb_item | message | flow_request
    title: str
    scope_id: str | None = None
    object_url: str | None = None


class ShareableDraft(BaseModel):
    """A reply / handoff / framing the user prepared but hasn't sent."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    target_scope_id: str | None = None
    target_user_id: str | None = None


class MyAILandingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grounded_items: list[GroundedItem]
    ready_to_share: list[ShareableDraft]
    scope_id: str | None


# ---- request shapes -------------------------------------------------------


class MyAIMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
    # Required for now — Phase B.1 ships the contract shape but the
    # "no scope" cross-project send case (scope_id=None) lands in B.2
    # once PersonalStreamService grows a cross-project post path. Today
    # the underlying service requires a project_id.
    scope_id: str = Field(min_length=1, max_length=64)
    # Mirrors PersonalStreamService.post — per-stream context-source
    # toggles + per-tier license intersection. Optional; absent means
    # server defaults.
    scope: dict[str, bool] | None = None
    scope_tiers: dict[str, bool] | None = None


def _get_personal_service(request: Request) -> PersonalStreamService:
    return request.app.state.personal_service


# ---- endpoints ------------------------------------------------------------


@router.get("/landing", response_model=MyAILandingResponse)
async def get_landing(
    request: Request,
    scope_id: str | None = Query(default=None, max_length=64),
    user: AuthenticatedUser = Depends(require_user),
) -> MyAILandingResponse:
    """Landing view for the My AI surface.

    Phase B.1 wires the contract shape with empty lists. Phase B.2
    populates from PersonalStreamService when the surface lands real
    grounded re-entry items (recent decisions / waiting flow requests /
    open Ready-to-Share drafts).
    """
    # Phase B.2 populates grounded_items from PersonalStreamService
    # when the surface lands real content.
    return MyAILandingResponse(
        grounded_items=[],
        ready_to_share=[],
        scope_id=scope_id,
    )


@router.post("/messages")
async def post_message(
    body: MyAIMessageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Assistant message + proposals.

    Thin wrapper over PersonalStreamService.post: pydantic validation
    here, membership gate + LLM orchestration inside the service. Any
    proposals (routing_suggestion / task_candidate / ...) ride out in
    the underlying service's response envelope unchanged for now;
    Phase B.2 normalizes the wire shape to the v0.6.2 ProposalType
    enum.
    """
    service = _get_personal_service(request)
    result = await service.post(
        user_id=user.id,
        project_id=body.scope_id,
        body=body.body,
        scope=body.scope,
        scope_tiers=body.scope_tiers,
    )
    if not result.get("ok"):
        err = result.get("error", "post_failed")
        status_map = {
            "project_not_found": 404,
            "not_a_project_member": 403,
            "stream_post_failed": 502,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result
