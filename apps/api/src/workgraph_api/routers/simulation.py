"""Simulation router — counterfactual "what if?" endpoint.

POST /api/projects/{project_id}/simulate
  body: {kind: "drop_task", entity_kind: "task", entity_id: str}
  returns: SimulationResult.to_dict()

Read-only. Requires project membership. Does not persist the
scenario — the graph stays live and the caller layers the overlay
on top of the current /state render.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ProjectService,
    SimulationError,
    SimulationService,
)

router = APIRouter(tags=["simulation"])


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["drop_task"]
    entity_kind: Literal["task"]
    entity_id: str = Field(min_length=1, max_length=64)


@router.post("/api/projects/{project_id}/simulate")
async def simulate(
    project_id: str,
    body: SimulateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")

    service: SimulationService = request.app.state.simulation_service
    try:
        result = await service.simulate(
            project_id=project_id,
            kind=body.kind,
            entity_kind=body.entity_kind,
            entity_id=body.entity_id,
        )
    except SimulationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result.to_dict()
