"""Phase 7'' collab endpoints: assignments, comments, notifications, IM.

All routes require a signed-in user. Assignments and comments require
project membership (the task/deliverable/risk row scopes the project).
IM post + suggestion accept also require membership.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from workgraph_persistence import (
    DeliverableRow,
    MessageRepository,
    ProjectRow,
    RiskRow,
    TaskRow,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AssignmentService,
    AuthenticatedUser,
    CommentService,
    ConflictService,
    IMService,
    MessageService,
    NotificationService,
    ProjectService,
)

router = APIRouter(prefix="/api", tags=["collab"])


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None


class CommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
    parent_comment_id: str | None = None


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
    # Per-stream context-source toggles set by the user via
    # StreamContextPanel on the web. Keys: graph / kb / dms / audit.
    # Absent → server-side defaults apply (graph + kb on, dms + audit
    # off). The field is explicitly typed instead of widening to
    # extra="ignore" so a client typo still gets a 422.
    scope: dict[str, bool] | None = None
    # Per-project scope-tier toggles from ScopeTierPills (N.2 →
    # consumed in pickup #7). Keys: personal / group / department /
    # enterprise (group = Cell). Absent → server treats as all-tiers-on.
    scope_tiers: dict[str, bool] | None = None
    # Pickup #6 — when supplied, the message lands in this specific
    # stream (typically a room) instead of the project's team-room.
    # Validated server-side: stream must belong to the project AND
    # the author must have membership for room/dm streams. Absent →
    # team-room (legacy behavior every existing client relies on).
    stream_id: str | None = None


class CounterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


async def _project_from_task(sessionmaker, task_id: str) -> str | None:
    async with session_scope(sessionmaker) as session:
        task = (
            await session.execute(select(TaskRow).where(TaskRow.id == task_id))
        ).scalar_one_or_none()
        return task.project_id if task else None


async def _project_from_target(
    sessionmaker, target_kind: str, target_id: str
) -> str | None:
    async with session_scope(sessionmaker) as session:
        if target_kind == "task":
            row = (
                await session.execute(select(TaskRow).where(TaskRow.id == target_id))
            ).scalar_one_or_none()
        elif target_kind == "deliverable":
            row = (
                await session.execute(
                    select(DeliverableRow).where(DeliverableRow.id == target_id)
                )
            ).scalar_one_or_none()
        elif target_kind == "risk":
            row = (
                await session.execute(select(RiskRow).where(RiskRow.id == target_id))
            ).scalar_one_or_none()
        else:
            return None
        return row.project_id if row else None


# ---- Assignments ---------------------------------------------------------


@router.post("/tasks/{task_id}/assignment")
async def set_assignment(
    task_id: str,
    body: AssignRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_id = await _project_from_task(request.app.state.sessionmaker, task_id)
    if project_id is None:
        raise HTTPException(status_code=404, detail="task not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    service: AssignmentService = request.app.state.assignment_service
    result = await service.set_assignment(
        task_id=task_id, user_id=body.user_id, actor_id=user.id
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "assignment_failed"))
    # Ownership change can clear missing_owner conflicts; recheck in
    # background so the banner count stays honest.
    from workgraph_observability import get_trace_id

    conflict_service: ConflictService = request.app.state.conflict_service
    conflict_service.kick_recheck(project_id, trace_id=get_trace_id())
    return result


@router.get("/projects/{project_id}/assignments")
async def list_assignments(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: AssignmentService = request.app.state.assignment_service
    return await service.list_for_project(project_id)


# ---- Comments ------------------------------------------------------------


@router.post("/{target_kind}/{target_id}/comments")
async def post_comment(
    target_kind: str,
    target_id: str,
    body: CommentRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    if target_kind not in {"tasks", "deliverables", "risks"}:
        raise HTTPException(status_code=404, detail="unsupported target kind")
    singular = {"tasks": "task", "deliverables": "deliverable", "risks": "risk"}[target_kind]
    project_id = await _project_from_target(
        request.app.state.sessionmaker, singular, target_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail=f"{singular} not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    service: CommentService = request.app.state.comment_service
    result = await service.post(
        author_id=user.id,
        target_kind=singular,
        target_id=target_id,
        body=body.body,
        project_id_hint=project_id,
        parent_comment_id=body.parent_comment_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "comment_failed"))
    return result


@router.get("/{target_kind}/{target_id}/comments")
async def list_comments(
    target_kind: str,
    target_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    if target_kind not in {"tasks", "deliverables", "risks"}:
        raise HTTPException(status_code=404, detail="unsupported target kind")
    singular = {"tasks": "task", "deliverables": "deliverable", "risks": "risk"}[target_kind]
    project_id = await _project_from_target(
        request.app.state.sessionmaker, singular, target_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail=f"{singular} not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: CommentService = request.app.state.comment_service
    return await service.list_for_target(singular, target_id)


# ---- Notifications -------------------------------------------------------


@router.get("/notifications")
async def list_notifications(
    request: Request,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthenticatedUser = Depends(require_user),
):
    service: NotificationService = request.app.state.notification_service
    items = await service.list_for_user(user.id, unread_only=unread_only, limit=limit)
    unread = await service.unread_count(user.id)
    return {"items": items, "unread_count": unread}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: NotificationService = request.app.state.notification_service
    ok = await service.mark_read(notification_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


@router.post("/notifications/read_all")
async def mark_all_notifications_read(
    request: Request, user: AuthenticatedUser = Depends(require_user)
):
    service: NotificationService = request.app.state.notification_service
    count = await service.mark_all_read(user.id)
    return {"ok": True, "marked": count}


# ---- Messages + IM -------------------------------------------------------


@router.post("/projects/{project_id}/messages")
async def post_message(
    project_id: str,
    body: MessageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: IMService = request.app.state.im_service
    result = await service.post_message(
        project_id=project_id,
        author_id=user.id,
        body=body.body,
        scope=body.scope,
        scope_tiers=body.scope_tiers,
        stream_id=body.stream_id,
    )
    if not result.get("ok"):
        err = result.get("error", "post_failed")
        if err == "rate_limited":
            raise HTTPException(status_code=429, detail="rate_limited")
        if err == "observer_cannot_post":
            raise HTTPException(status_code=403, detail="observer_cannot_post")
        if err in (
            "stream_not_found",
            "wrong_project",
            "not_a_stream_member",
        ):
            raise HTTPException(status_code=403, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.post("/projects/{project_id}/messages/{message_id}/save-as-kb")
async def post_save_message_as_kb(
    project_id: str,
    message_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Promote a stream message into a group-scope KB (wiki) draft.

    Manual trigger today; the same path will be reused by the future
    edge-agent auto-classifier so the path through the system is
    identical regardless of trigger origin. The created KbItemRow is
    `scope='group', source='llm', status='draft'` so the wiki view
    surfaces it pending owner approval / promotion. Title is derived
    from the first line of the message body (capped); content is the
    full body.
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    async with session_scope(request.app.state.sessionmaker) as session:
        msg = await MessageRepository(session).get(message_id)
        if msg is None or msg.project_id != project_id:
            raise HTTPException(status_code=404, detail="message_not_found")
        body = (msg.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="empty_message")
    first_line = body.splitlines()[0] if body else ""
    title = (first_line or body)[:160].strip() or "Untitled"
    kb_service = request.app.state.kb_item_service
    try:
        item = await kb_service.create(
            project_id=project_id,
            owner_user_id=user.id,
            title=title,
            content_md=body,
            scope="group",
            source="llm",
            status="draft",
        )
    except Exception as e:  # noqa: BLE001 — surface the validation code
        code = getattr(e, "code", None) or "create_failed"
        status = getattr(e, "status", None) or 400
        raise HTTPException(status_code=status, detail=code) from e
    return {"ok": True, "item": item, "source_message_id": message_id}


@router.get("/projects/{project_id}/messages")
async def list_messages(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    message_service: MessageService = request.app.state.message_service
    im_service: IMService = request.app.state.im_service
    messages = await message_service.list_recent(project_id, limit=limit)
    suggestions = await im_service.list_for_project(project_id, limit=limit)
    by_message: dict[str, dict] = {s["message_id"]: s for s in suggestions}
    for m in messages:
        m["suggestion"] = by_message.get(m["id"])
    return {"messages": messages}


@router.post("/im_suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: IMService = request.app.state.im_service
    payload = await service.get_suggestion(suggestion_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=payload["project_id"], user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.accept(suggestion_id=suggestion_id, actor_id=user.id)
    if not result.get("ok"):
        err = result.get("error", "accept_failed")
        # owner_only: caller is a member but not the project owner;
        # only owners can accept membrane_review suggestions (the
        # staged-write authority gate).
        status = 403 if err == "owner_only" else 409
        raise HTTPException(status_code=status, detail=err)
    return result


@router.post("/im_suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    suggestion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: IMService = request.app.state.im_service
    payload = await service.get_suggestion(suggestion_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=payload["project_id"], user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.dismiss(suggestion_id=suggestion_id, actor_id=user.id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "dismiss_failed"))
    return result


@router.post("/im_suggestions/{suggestion_id}/counter")
async def counter_suggestion(
    suggestion_id: str,
    body: CounterRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Signal-chain counter (vision §6). Flips original → countered, posts
    a new message authored by the counterer, runs IMAssist, returns the
    original + new message + new suggestion (if the new message was
    long enough to classify).
    """
    service: IMService = request.app.state.im_service
    payload = await service.get_suggestion(suggestion_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=payload["project_id"], user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.counter(
        suggestion_id=suggestion_id, text=body.text, user_id=user.id
    )
    if not result.get("ok"):
        err = result.get("error", "counter_failed")
        if err == "already_resolved":
            raise HTTPException(status_code=409, detail=err)
        if err == "rate_limited":
            raise HTTPException(status_code=429, detail=err)
        if err == "suggestion_not_found":
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.post("/im_suggestions/{suggestion_id}/escalate")
async def escalate_suggestion(
    suggestion_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Signal-chain escalate (vision §6 / §5.6). Flag-only in v0 — no
    meeting scheduled; the UI just renders an 'awaiting sync' badge.
    """
    service: IMService = request.app.state.im_service
    payload = await service.get_suggestion(suggestion_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=payload["project_id"], user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.escalate(suggestion_id=suggestion_id, user_id=user.id)
    if not result.get("ok"):
        err = result.get("error", "escalate_failed")
        if err == "already_resolved":
            raise HTTPException(status_code=409, detail=err)
        if err == "suggestion_not_found":
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result["suggestion"]
