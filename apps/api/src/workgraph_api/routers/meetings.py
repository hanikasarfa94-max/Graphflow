"""Meetings router — Phase 2.B uploaded meeting transcripts.

Endpoints:
  * POST /api/projects/{project_id}/meetings
      Body: {title, transcript_text, participant_user_ids?}
      Upload a transcript. Returns the created row at
      `metabolism_status='pending'`; the edge-LLM metabolism pass runs
      in the background and flips status to 'done' or 'failed'.
  * GET  /api/projects/{project_id}/meetings
      List transcripts for the project (compact — no transcript text).
  * GET  /api/projects/{project_id}/meetings/{transcript_id}
      Full detail: transcript text + extracted_signals proposals.
  * POST /api/projects/{project_id}/meetings/{transcript_id}/remetabolize
      Owner-only. Clear extracted_signals + re-queue metabolism.
  * POST /api/projects/{project_id}/meetings/{transcript_id}/signals/{signal_kind}/{signal_idx}/accept
      Convert one proposed signal into a real DecisionRow / TaskRow /
      RiskRow. Member-level; same auth gate as the rest of the graph-
      mutation paths in this project.

Auth: project membership required for upload / list / get / accept.
Owner role required for remetabolize.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import (
    ProjectMemberRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    MeetingIngestError,
    MeetingIngestService,
    ProjectService,
)

router = APIRouter(prefix="/api", tags=["meetings"])


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=500)
    transcript_text: str = Field(min_length=1, max_length=60_000)
    participant_user_ids: list[str] = Field(default_factory=list, max_length=50)


def _get_service(request: Request) -> MeetingIngestService:
    return request.app.state.meeting_ingest_service


async def _require_member(
    request: Request, project_id: str, user_id: str
) -> None:
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user_id
    ):
        raise HTTPException(status_code=403, detail="not_a_project_member")


async def _require_owner(
    request: Request, project_id: str, user_id: str
) -> None:
    await _require_member(request, project_id, user_id)
    async with session_scope(request.app.state.sessionmaker) as session:
        members = await ProjectMemberRepository(session).list_for_project(
            project_id
        )
        for m in members:
            if m.user_id == user_id and m.role == "owner":
                return
    raise HTTPException(status_code=403, detail="owner_required")


def _handle_error(exc: MeetingIngestError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.code)


@router.post("/projects/{project_id}/meetings")
async def post_upload(
    project_id: str,
    body: UploadRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_service(request)
    try:
        return await service.upload(
            project_id=project_id,
            uploader_user_id=user.id,
            title=body.title,
            transcript_text=body.transcript_text,
            participant_user_ids=body.participant_user_ids,
        )
    except MeetingIngestError as e:
        raise _handle_error(e)


@router.get("/projects/{project_id}/meetings")
async def get_list(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_service(request)
    items = await service.list_for_project(project_id)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/projects/{project_id}/meetings/{transcript_id}")
async def get_detail(
    project_id: str,
    transcript_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_service(request)
    detail = await service.detail(
        transcript_id, project_id=project_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="transcript_not_found")
    return {"ok": True, "transcript": detail}


@router.post("/projects/{project_id}/meetings/{transcript_id}/remetabolize")
async def post_remetabolize(
    project_id: str,
    transcript_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_owner(request, project_id, user.id)
    service = _get_service(request)
    try:
        return await service.remetabolize(
            transcript_id=transcript_id, project_id=project_id
        )
    except MeetingIngestError as e:
        raise _handle_error(e)


@router.post(
    "/projects/{project_id}/meetings/{transcript_id}"
    "/signals/{signal_kind}/{signal_idx}/accept"
)
async def post_accept_signal(
    project_id: str,
    transcript_id: str,
    signal_kind: str,
    signal_idx: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_service(request)
    try:
        return await service.accept_signal(
            transcript_id=transcript_id,
            project_id=project_id,
            signal_kind=signal_kind,
            signal_idx=signal_idx,
            actor_id=user.id,
        )
    except MeetingIngestError as e:
        raise _handle_error(e)
