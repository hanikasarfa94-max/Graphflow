"""Decision-vote router — N.4 smallest-relevant-vote tally.

Endpoints:
  * POST /api/decisions/{decision_id}/votes
      body { verdict: "approve"|"deny"|"abstain", rationale?: str }
      Casts (or changes) the caller's vote. Returns {tally, my_vote}.
      Membership: room-scoped decisions require room membership;
      project-scoped require project membership.

  * GET  /api/decisions/{decision_id}/votes
      Read-only. Returns the current tally + the viewer's own vote.

WS broadcast: a successful POST publishes a RoomTimelineEvent
`timeline.update` on the room stream (if scope_stream_id is set).
The frontend useRoomTimeline reducer applies it via shallow-merge so
both projections (inline DecisionCard + workbench Decisions panel
when it ships) reconcile from one event.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser
from workgraph_api.services.decision_votes import (
    VALID_VERDICTS,
    DecisionVoteError,
    DecisionVoteService,
)


router = APIRouter(tags=["decision-votes"])


class CastVoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `approve` / `deny` / `abstain`. Validated server-side so a
    # forward-compat verdict added to the enum doesn't 422 here.
    verdict: str = Field(min_length=1, max_length=16)
    rationale: str | None = Field(default=None, max_length=2000)


def _service(request: Request) -> DecisionVoteService:
    return request.app.state.decision_vote_service


@router.post("/api/decisions/{decision_id}/votes")
async def cast_decision_vote(
    decision_id: str,
    body: CastVoteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(status_code=400, detail="invalid_verdict")
    svc = _service(request)
    try:
        result = await svc.cast_vote(
            decision_id=decision_id,
            voter_user_id=user.id,
            verdict=body.verdict,
            rationale=body.rationale,
        )
    except DecisionVoteError as e:
        raise HTTPException(status_code=e.status, detail=e.code)
    return result


@router.get("/api/decisions/{decision_id}/votes")
async def get_decision_tally(
    decision_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    svc = _service(request)
    try:
        return await svc.get_tally(
            decision_id=decision_id, viewer_user_id=user.id
        )
    except DecisionVoteError as e:
        raise HTTPException(status_code=e.status, detail=e.code)
