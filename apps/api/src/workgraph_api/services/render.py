"""Phase R — RenderService.

Builds a project- or user-scoped context dict from the persistence layer,
hands it to the RenderAgent, and caches the resulting doc in-memory (no
ORM). Regeneration endpoint clears the cache entry and recomputes.

Cache key format:
  f"{kind}:{project_id}:{user_id or '_'}"

Cache value is a small dataclass with a `generated_at` so the frontend
can show staleness ("Generated 12 minutes ago"). Cache survives process
lifetime only — on reboot everything regenerates on first request, which
is fine for v1.

Two public methods, both return a serializable dict payload the router
hands straight back:

  * `render_postmortem(project_id)` — fetches requirement + graph + plan +
    decisions + assignments + recent stream turns, walks decisions for a
    light lineage trace (counters + signals referencing the decision), and
    hands the bundle to the agent. Returns the cached doc on subsequent
    calls until regeneration is requested.

  * `render_handoff(user_id, project_id)` — fetches the target user's
    edges in the project: tasks they own, decisions they authored, routed
    signals they are source/target of, adjacent teammates, open items.
    Also computes a rough response_profile from their recent routed
    signals (counter_rate / accept_rate). Hands it to the agent.

Neither method hits DeepSeek if the doc is cached; the router's
regenerate endpoint explicitly calls `regenerate_*` which evicts first.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import HandoffDoc, PostmortemDoc, RenderAgent
from workgraph_persistence import (
    AssignmentRepository,
    DecisionRepository,
    MessageRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    RoutedSignalRepository,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.render")


class RenderError(Exception):
    """Raised for lookup/validation failures — mapped to 4xx by the router."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(slots=True)
class _CachedRender:
    """In-memory cache entry.

    Stores the doc payload as a dict (already JSON-serializable) plus the
    generation timestamp + agent metadata. The frontend uses
    `generated_at` to render "12 minutes ago" staleness.
    """

    kind: str  # "postmortem" | "handoff"
    project_id: str
    user_id: str | None
    doc: dict[str, Any]
    generated_at: datetime
    prompt_version: str
    outcome: str
    attempts: int
    error: str | None = None


class RenderService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        agent: RenderAgent,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._agent = agent
        # Cache is dict[key] -> _CachedRender. No eviction policy in v1;
        # entries live for process lifetime. If memory becomes a concern,
        # swap in cachetools.LRUCache — the call sites only need .get
        # and .__setitem__ so the swap is trivial.
        self._cache: dict[str, _CachedRender] = {}

    # ---- public API ------------------------------------------------------

    async def render_postmortem(
        self, *, project_id: str, force: bool = False
    ) -> dict[str, Any]:
        key = f"postmortem:{project_id}:_"
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return _serialize(cached)
        return _serialize(await self._compute_postmortem(project_id, key))

    async def regenerate_postmortem(
        self, *, project_id: str
    ) -> dict[str, Any]:
        return await self.render_postmortem(project_id=project_id, force=True)

    async def render_handoff(
        self, *, project_id: str, user_id: str, force: bool = False
    ) -> dict[str, Any]:
        key = f"handoff:{project_id}:{user_id}"
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return _serialize(cached)
        return _serialize(
            await self._compute_handoff(project_id, user_id, key)
        )

    async def regenerate_handoff(
        self, *, project_id: str, user_id: str
    ) -> dict[str, Any]:
        return await self.render_handoff(
            project_id=project_id, user_id=user_id, force=True
        )

    # ---- postmortem compute ---------------------------------------------

    async def _compute_postmortem(
        self, project_id: str, cache_key: str
    ) -> _CachedRender:
        context = await self._gather_postmortem_context(project_id)
        if context is None:
            raise RenderError("project_not_ready", status=409)

        outcome = await self._agent.render_postmortem(context)
        entry = _CachedRender(
            kind="postmortem",
            project_id=project_id,
            user_id=None,
            doc=outcome.doc.model_dump(mode="json"),
            generated_at=datetime.now(timezone.utc),
            prompt_version=self._agent.postmortem_prompt_version,
            outcome=outcome.outcome,
            attempts=outcome.attempts,
            error=outcome.error,
        )
        self._cache[cache_key] = entry
        return entry

    async def _gather_postmortem_context(
        self, project_id: str
    ) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None
            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            if req is None:
                return None

            graph_repo = ProjectGraphRepository(session)
            goals = await graph_repo.list_goals(req.id)
            deliverables = await graph_repo.list_deliverables(req.id)
            constraints = await graph_repo.list_constraints(req.id)
            risks = await graph_repo.list_risks(req.id)

            plan_repo = PlanRepository(session)
            tasks = await plan_repo.list_tasks(req.id)
            milestones = await plan_repo.list_milestones(req.id)

            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )
            decisions = await DecisionRepository(session).list_for_project(
                project_id, limit=200
            )
            messages = await MessageRepository(session).list_recent(
                project_id, limit=30
            )

            # Display-name lookup for lineage attribution.
            user_ids = {a.user_id for a in assignments}
            user_ids.update(d.resolver_id for d in decisions if d.resolver_id)
            user_ids.update(m.author_id for m in messages if m.author_id)
            user_map: dict[str, str] = {}
            if user_ids:
                user_repo = UserRepository(session)
                for uid in user_ids:
                    u = await user_repo.get(uid)
                    if u is not None:
                        user_map[uid] = u.display_name or u.username

        delivered = [t for t in tasks if t.status in ("done", "completed")]
        undelivered = [t for t in tasks if t.status not in ("done", "completed")]
        resolved_risks = [r for r in risks if r.status in ("resolved", "closed")]
        active_tasks_out = [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "owner_display_name": _owner_display(t.id, assignments, user_map),
            }
            for t in undelivered
        ]

        decisions_out: list[dict[str, Any]] = []
        for d in decisions:
            lineage = _build_lineage(d, user_map=user_map)
            decisions_out.append(
                {
                    "id": d.id,
                    "conflict_id": d.conflict_id,
                    "option_index": d.option_index,
                    "custom_text": d.custom_text,
                    "rationale": d.rationale or "",
                    "apply_outcome": d.apply_outcome,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "resolver_display_name": (
                        user_map.get(d.resolver_id) if d.resolver_id else None
                    ),
                    "lineage": lineage,
                }
            )

        return {
            "project": {"id": project.id, "title": project.title},
            "requirement": {
                "goal": (req.parsed_json or {}).get("goal", ""),
                "scope_items": (req.parsed_json or {}).get("scope_items", []),
                "deadline": (req.parsed_json or {}).get("deadline"),
                "open_questions": (req.parsed_json or {}).get(
                    "open_questions", []
                ),
            },
            "graph": {
                "goals": [
                    {"id": g.id, "title": g.title, "status": g.status}
                    for g in goals
                ],
                "deliverables": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "kind": d.kind,
                        "status": d.status,
                    }
                    for d in deliverables
                ],
                "constraints": [
                    {
                        "id": c.id,
                        "kind": c.kind,
                        "content": c.content,
                        "severity": c.severity,
                        "status": c.status,
                    }
                    for c in constraints
                ],
                "risks": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                        "status": r.status,
                    }
                    for r in risks
                ],
            },
            "plan": {
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "status": t.status,
                        "deliverable_id": t.deliverable_id,
                        "acceptance_criteria": t.acceptance_criteria or [],
                    }
                    for t in tasks
                ],
                "milestones": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "status": m.status,
                        "target_date": m.target_date,
                    }
                    for m in milestones
                ],
            },
            "decisions": decisions_out,
            "resolved_risks": [
                {"id": r.id, "title": r.title, "severity": r.severity}
                for r in resolved_risks
            ],
            "active_tasks": active_tasks_out,
            "delivered_tasks": [
                {"id": t.id, "title": t.title} for t in delivered
            ],
            "undelivered_tasks": [
                {"id": t.id, "title": t.title, "status": t.status}
                for t in undelivered
            ],
            "key_turns": [
                {
                    "author_display_name": user_map.get(m.author_id, m.author_id),
                    "body": _truncate(m.body or "", 400),
                    "kind": "message",
                }
                for m in messages[-10:]
            ],
        }

    # ---- handoff compute ------------------------------------------------

    async def _compute_handoff(
        self, project_id: str, user_id: str, cache_key: str
    ) -> _CachedRender:
        context = await self._gather_handoff_context(project_id, user_id)
        if context is None:
            raise RenderError("project_or_user_not_found", status=404)

        outcome = await self._agent.render_handoff(context)
        entry = _CachedRender(
            kind="handoff",
            project_id=project_id,
            user_id=user_id,
            doc=outcome.doc.model_dump(mode="json"),
            generated_at=datetime.now(timezone.utc),
            prompt_version=self._agent.handoff_prompt_version,
            outcome=outcome.outcome,
            attempts=outcome.attempts,
            error=outcome.error,
        )
        self._cache[cache_key] = entry
        return entry

    async def _gather_handoff_context(
        self, project_id: str, user_id: str
    ) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None
            user_repo = UserRepository(session)
            user = await user_repo.get(user_id)
            if user is None:
                return None

            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            tasks: list = []
            if req is not None:
                tasks = await PlanRepository(session).list_tasks(req.id)

            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            decisions = await DecisionRepository(session).list_for_project(
                project_id, limit=200
            )
            inbound = await RoutedSignalRepository(session).list_for_user(
                user_id, kind="inbound", limit=50
            )
            outbound = await RoutedSignalRepository(session).list_for_user(
                user_id, kind="outbound", limit=50
            )

            member_ids = {m.user_id for m in members}
            member_role: dict[str, str] = {m.user_id: m.role or "" for m in members}
            user_map: dict[str, tuple[str, str]] = {}
            for mid in member_ids:
                u = await user_repo.get(mid)
                if u is not None:
                    user_map[mid] = (
                        u.display_name or u.username,
                        member_role.get(mid, ""),
                    )

        # Only tasks assigned to the target user.
        owned_task_ids = {
            a.task_id
            for a in assignments
            if a.user_id == user_id and a.active
        }
        task_by_id = {t.id: t for t in tasks}
        active_tasks_out: list[dict[str, Any]] = []
        for tid in owned_task_ids:
            t = task_by_id.get(tid)
            if t is None:
                continue
            if t.status in ("done", "completed"):
                continue
            active_tasks_out.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "description": t.description or "",
                    "deliverable_title": None,
                }
            )

        # Decisions the user authored (resolver).
        shaped: list[dict[str, Any]] = []
        for d in decisions:
            if d.resolver_id == user_id:
                shaped.append(
                    {
                        "id": d.id,
                        "headline": (d.rationale or d.custom_text or "")[:200],
                        "rationale": d.rationale or "",
                        "role": "author",
                    }
                )

        # Recent signals (both directions). Project filter applies.
        recent_signals: list[dict[str, Any]] = []
        for s in list(inbound) + list(outbound):
            if s.project_id and s.project_id != project_id:
                continue
            role = "target" if s.target_user_id == user_id else "source"
            resolution = s.status
            if s.reply_json and isinstance(s.reply_json, dict):
                if s.reply_json.get("option_id"):
                    resolution = "accepted_option"
                elif s.reply_json.get("custom_text"):
                    resolution = "custom_reply"
            recent_signals.append(
                {
                    "framing": s.framing,
                    "role": role,
                    "resolution": resolution,
                }
            )

        # Adjacent teammates: project members minus the departing user.
        adjacent: list[dict[str, Any]] = []
        for m in members:
            if m.user_id == user_id:
                continue
            name, role = user_map.get(m.user_id, (m.user_id, ""))
            adjacent.append(
                {
                    "user_id": m.user_id,
                    "display_name": name,
                    "role": role,
                    "shared_context": f"project:{project.title}",
                }
            )

        # Open items: pending inbound routings for this user + active
        # tasks with no recent update. Simple v1 signal — not a full inbox.
        open_items: list[dict[str, Any]] = []
        for s in inbound:
            if s.project_id and s.project_id != project_id:
                continue
            if s.status == "pending":
                src_name, _ = user_map.get(s.source_user_id, (s.source_user_id, ""))
                age_days = None
                if s.created_at is not None:
                    delta = datetime.now(timezone.utc) - _as_aware(s.created_at)
                    age_days = int(delta.total_seconds() // 86400)
                open_items.append(
                    {
                        "kind": "routing",
                        "framing": s.framing,
                        "from_display_name": src_name,
                        "age_days": age_days,
                    }
                )

        # Response profile: rough counter/accept rates from replied signals
        # where the user was target.
        replied = [
            s
            for s in inbound
            if s.status in ("replied",) and isinstance(s.reply_json, dict)
        ]
        profile: dict[str, Any] = {
            "counter_rate": None,
            "accept_rate": None,
            "preferred_kinds": [],
        }
        if replied:
            # Treat "accepted_option" as accept-ish; custom text as counter-ish.
            accepts = sum(
                1 for s in replied if (s.reply_json or {}).get("option_id")
            )
            counters = sum(
                1 for s in replied if (s.reply_json or {}).get("custom_text")
            )
            total = len(replied)
            profile["accept_rate"] = round(accepts / total, 2) if total else None
            profile["counter_rate"] = (
                round(counters / total, 2) if total else None
            )
            if accepts >= counters and accepts > 0:
                profile["preferred_kinds"] = ["accept"]
            elif counters > 0:
                profile["preferred_kinds"] = ["counter"]

        profile_dict = user.profile or {}
        user_role = member_role.get(user.id, "member")
        return {
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name or user.username,
                "role": user_role,
                "declared_abilities": list(
                    profile_dict.get("declared_abilities") or []
                ),
            },
            "project": {"id": project.id, "title": project.title},
            "active_tasks": active_tasks_out,
            "shaped_decisions": shaped,
            "recent_signals": recent_signals[:30],
            "adjacent_teammates": adjacent,
            "open_items": open_items,
            "response_profile": profile,
        }


# ---- helpers -----------------------------------------------------------


def _serialize(entry: _CachedRender) -> dict[str, Any]:
    return {
        "kind": entry.kind,
        "project_id": entry.project_id,
        "user_id": entry.user_id,
        "doc": entry.doc,
        "generated_at": entry.generated_at.isoformat(),
        "prompt_version": entry.prompt_version,
        "outcome": entry.outcome,
        "attempts": entry.attempts,
        "error": entry.error,
    }


def _owner_display(
    task_id: str,
    assignments: list,
    user_map: dict[str, str],
) -> str | None:
    for a in assignments:
        if a.task_id == task_id and a.active:
            return user_map.get(a.user_id, a.user_id)
    return None


def _build_lineage(
    decision, *, user_map: dict[str, str]
) -> list[dict[str, Any]]:
    """Rough lineage trace from a DecisionRow.

    v1: a decision's lineage is the decision itself (the full trace from
    raw signal → reply → crystallized decision lives in message history +
    conflicts, which we don't join here). We produce one "decision" entry
    with the rationale so the LLM still has something concrete to cite.
    """
    entries: list[dict[str, Any]] = []
    by_name = None
    if decision.resolver_id:
        by_name = user_map.get(decision.resolver_id)
    entries.append(
        {
            "kind": "decision",
            "summary": decision.rationale or decision.custom_text or "",
            "by_display_name": by_name,
        }
    )
    return entries


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


__all__ = ["RenderService", "RenderError"]
