"""Silent consensus router — Phase 1.A.

Endpoints:
  * GET  /api/projects/{project_id}/silent-consensus
      List pending silent-consensus proposals for the project.
      Project member gate.
  * POST /api/projects/{project_id}/silent-consensus/{sc_id}/ratify
      Crystallize as a DecisionRow. Owner + full-tier only.
  * POST /api/projects/{project_id}/silent-consensus/{sc_id}/reject
      Flip status to 'rejected' without creating a decision. Owner +
      full-tier only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ProjectService,
    SilentConsensusService,
)

router = APIRouter(tags=["silent-consensus"])


# ---- response shapes (C1-C) -----------------------------------------------
# Mirror SilentConsensusService._serialize. NOTE: supporting_action_ids is
# genuinely list[dict] {kind,id} at runtime (the sole writer builds dicts), and
# the FE SilentConsensusProposal already declares it as objects — so this is NOT
# a mismatch; modeling it truthfully aligns both. *_at + ratified_decision_id
# nullable; the {ok:false} variant is raised as HTTP by _handle.


class SilentConsensusSupportingAction(BaseModel):
    kind: str
    id: str


class SilentConsensusMember(BaseModel):
    user_id: str
    display_name: str


class SilentConsensusProposal(BaseModel):
    id: str
    project_id: str
    topic_text: str
    supporting_action_ids: list[SilentConsensusSupportingAction] = Field(
        default_factory=list
    )
    inferred_decision_summary: str
    members: list[SilentConsensusMember] = Field(default_factory=list)
    member_user_ids: list[str] = Field(default_factory=list)
    confidence: float
    status: str
    created_at: str | None = None
    ratified_decision_id: str | None = None
    ratified_at: str | None = None


class SilentConsensusListResponse(BaseModel):
    ok: bool
    proposals: list[SilentConsensusProposal]


_ERROR_STATUS: dict[str, int] = {
    "not_a_member": 403,
    "forbidden": 403,
    "not_found": 404,
    "not_pending": 409,
}


def _handle(result: dict) -> dict:
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_ERROR_STATUS.get(err, 400), detail=err
        )
    return result


@router.get(
    "/api/projects/{project_id}/silent-consensus",
    response_model=SilentConsensusListResponse,
)
async def list_silent_consensus(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: SilentConsensusService = (
        request.app.state.silent_consensus_service
    )
    return _handle(
        await service.list_pending(
            project_id=project_id, viewer_user_id=user.id
        )
    )


@router.post(
    "/api/projects/{project_id}/silent-consensus/{sc_id}/ratify"
)
async def ratify_silent_consensus(
    project_id: str,
    sc_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: SilentConsensusService = (
        request.app.state.silent_consensus_service
    )
    return _handle(
        await service.ratify(
            project_id=project_id,
            sc_id=sc_id,
            ratifier_user_id=user.id,
        )
    )


@router.post(
    "/api/projects/{project_id}/silent-consensus/{sc_id}/reject"
)
async def reject_silent_consensus(
    project_id: str,
    sc_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: SilentConsensusService = (
        request.app.state.silent_consensus_service
    )
    return _handle(
        await service.reject(
            project_id=project_id,
            sc_id=sc_id,
            rejecter_user_id=user.id,
        )
    )
