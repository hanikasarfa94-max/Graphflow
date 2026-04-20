from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from workgraph_persistence import (
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    StatusTransitionRepository,
    session_scope,
)
from sqlalchemy import select

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService
from workgraph_api.services.graph_replay import GraphReplayService

router = APIRouter(prefix="/api/projects", tags=["graph"])


@router.get("/{project_id}/graph")
async def get_graph(project_id: str, request: Request) -> dict[str, Any]:
    """Return the graph entities bound to the latest requirement version.

    Phase 5 output shape — downstream phases (planning, QA) will extend it
    with enriched fields on existing kinds rather than adding new top-level
    collections.
    """
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        project = (
            await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(
                status_code=404, detail=f"project not found: {project_id}"
            )

        latest_req = await RequirementRepository(session).latest_for_project(project_id)
        if latest_req is None:
            return {
                "project_id": project_id,
                "requirement_id": None,
                "requirement_version": 0,
                "goals": [],
                "deliverables": [],
                "constraints": [],
                "risks": [],
            }

        rows = await ProjectGraphRepository(session).list_all(latest_req.id)

    return {
        "project_id": project_id,
        "requirement_id": latest_req.id,
        "requirement_version": latest_req.version,
        "goals": [
            {
                "id": g.id,
                "title": g.title,
                "description": g.description,
                "success_criteria": g.success_criteria,
                "status": g.status,
                "sort_order": g.sort_order,
            }
            for g in rows["goals"]
        ],
        "deliverables": [
            {
                "id": d.id,
                "title": d.title,
                "kind": d.kind,
                "status": d.status,
                "sort_order": d.sort_order,
            }
            for d in rows["deliverables"]
        ],
        "constraints": [
            {
                "id": c.id,
                "kind": c.kind,
                "content": c.content,
                "severity": c.severity,
                "status": c.status,
                "sort_order": c.sort_order,
            }
            for c in rows["constraints"]
        ],
        "risks": [
            {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "severity": r.severity,
                "status": r.status,
                "sort_order": r.sort_order,
            }
            for r in rows["risks"]
        ],
    }


# ---- Sprint 1b — time-cursor endpoints ----------------------------------


def _parse_iso_ts(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp. Accepts 'Z' suffix and naive inputs.

    Naive inputs are assumed to be UTC — the frontend always serializes
    via Date.toISOString() which is UTC-Z, but server-side callers (e.g.
    curl with no zone) shouldn't silently produce wrong answers against
    the project timezone. Default-to-UTC matches the rest of the stack.
    """
    # fromisoformat doesn't accept trailing 'Z' until py3.11; strip it
    # defensively so the endpoint stays portable.
    cleaned = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail=f"invalid ts (expected iso8601): {raw}"
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/{project_id}/graph-at")
async def graph_at(
    project_id: str,
    request: Request,
    ts: str = Query(..., description="ISO-8601 timestamp"),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Return the project graph as it existed at `ts`.

    Shape mirrors `/state` closely enough that GraphCanvas can swap the
    payload in place. Membership-gated. Delegates to GraphReplayService.
    """
    when = _parse_iso_ts(ts)
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    replay = GraphReplayService(request.app.state.sessionmaker)
    result = await replay.graph_at(project_id, when)
    if result is None:
        raise HTTPException(status_code=404, detail="project not found")
    return result


@router.get("/{project_id}/timeline")
async def get_timeline(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Return timeline bounds + event markers for the scrubber strip.

    Shape:
      * created_at: earliest point on the timeline (project birth)
      * now: current server wall-clock, so the client anchors "Live"
        to the server's clock rather than the user's (clock skew would
        make the scrubber misrender otherwise)
      * transitions: recent status-mutation markers
      * decisions: decision created_at markers
      * conflicts: conflict created_at markers (unresolved or resolved
        within the window — both are useful as "something happened here"
        ticks)
    """
    sessionmaker = request.app.state.sessionmaker
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    async with session_scope(sessionmaker) as session:
        project = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        # Epoch = project creation. The web client anchors the slider at
        # this lower bound so even very old projects fit in one strip.
        epoch = project.created_at
        # Pull transitions from the project start (no cap) — the timeline
        # is a fixed-height strip so rendering all marks is fine for v1.
        # If a project ever accumulates thousands of transitions we'll
        # bucketize server-side.
        transitions = await StatusTransitionRepository(
            session
        ).list_for_project_since(
            project_id, since=epoch, limit=500
        )
        # Conflicts + decisions as coarser markers (labeled differently
        # on the strip so the user can tell them apart).
        from workgraph_persistence import ConflictRow, DecisionRow

        decisions = (
            await session.execute(
                select(DecisionRow)
                .where(DecisionRow.project_id == project_id)
                .order_by(DecisionRow.created_at)
            )
        ).scalars().all()
        conflicts = (
            await session.execute(
                select(ConflictRow)
                .where(ConflictRow.project_id == project_id)
                .order_by(ConflictRow.created_at)
            )
        ).scalars().all()

    now = datetime.now(timezone.utc)
    return {
        "project_id": project_id,
        "created_at": epoch.isoformat(),
        "now": now.isoformat(),
        "transitions": [
            {
                "id": tr.id,
                "entity_kind": tr.entity_kind,
                "entity_id": tr.entity_id,
                "old_status": tr.old_status,
                "new_status": tr.new_status,
                "changed_at": tr.changed_at.isoformat(),
            }
            for tr in transitions
        ],
        "decisions": [
            {
                "id": d.id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "rationale": (d.rationale or "")[:120],
            }
            for d in decisions
        ],
        "conflicts": [
            {
                "id": c.id,
                "rule": c.rule,
                "severity": c.severity,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            }
            for c in conflicts
        ],
    }
