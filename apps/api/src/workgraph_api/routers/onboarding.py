"""Onboarding router — Phase 1.B ambient Day-1 walkthrough.

Endpoints:
  * GET  /api/projects/{project_id}/onboarding/walkthrough
      Returns { state, walkthrough }. First-visit side effect: creates
      an OnboardingStateRow if one doesn't exist for (user, project).
  * POST /api/projects/{project_id}/onboarding/checkpoint
      Body: { checkpoint: str }
      Advance the saved checkpoint. Valid values enumerated by
      services.onboarding.VALID_CHECKPOINTS.
  * POST /api/projects/{project_id}/onboarding/dismiss
      Mark the overlay dismissed; overlay stops opening on subsequent
      visits but the row is not marked completed.
  * POST /api/projects/{project_id}/onboarding/replay
      Clear dismissed + completed + cached walkthrough so the overlay
      reopens next visit. Used by /settings/profile "Replay" link.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    VALID_CHECKPOINTS,
    AuthenticatedUser,
    OnboardingService,
    ProjectService,
)

router = APIRouter(tags=["onboarding"])


class CheckpointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint: str = Field(min_length=1, max_length=24)


_ERROR_STATUS: dict[str, int] = {
    "invalid_checkpoint": 400,
}


def _handle(result: dict) -> dict:
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_ERROR_STATUS.get(err, 400), detail=err
        )
    return result


async def _require_member(
    request: Request, project_id: str, user_id: str
) -> None:
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user_id
    ):
        raise HTTPException(status_code=403, detail="not a project member")


@router.get("/api/projects/{project_id}/onboarding/walkthrough")
async def get_walkthrough(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service: OnboardingService = request.app.state.onboarding_service
    # First-visit side effect: ensures row exists + first_seen_at stamped.
    state, _created = await service.get_or_init_state(
        user_id=user.id, project_id=project_id
    )
    walkthrough = await service.build_walkthrough(
        user_id=user.id, project_id=project_id
    )
    return {
        "state": state,
        "walkthrough": walkthrough,
        "valid_checkpoints": sorted(VALID_CHECKPOINTS),
    }


@router.post("/api/projects/{project_id}/onboarding/checkpoint")
async def post_checkpoint(
    project_id: str,
    body: CheckpointRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service: OnboardingService = request.app.state.onboarding_service
    return _handle(
        await service.advance_checkpoint(
            user_id=user.id,
            project_id=project_id,
            checkpoint=body.checkpoint,
        )
    )


@router.post("/api/projects/{project_id}/onboarding/dismiss")
async def post_dismiss(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service: OnboardingService = request.app.state.onboarding_service
    return _handle(
        await service.dismiss(
            user_id=user.id, project_id=project_id
        )
    )


@router.post("/api/projects/{project_id}/onboarding/replay")
async def post_replay(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service: OnboardingService = request.app.state.onboarding_service
    return _handle(
        await service.replay(
            user_id=user.id, project_id=project_id
        )
    )
