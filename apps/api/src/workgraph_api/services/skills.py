"""SkillsService — Phase Q tool execution (read-only).

The EdgeAgent.respond() prompt can return `kind="tool_call"` with a
structured `{name, args}`. The PersonalStreamService dispatches that
call through SkillsService, which:

  * Validates the skill name against ALLOWED_SKILLS.
  * Scopes every query to the project_id that originated the turn —
    a skill invocation from Maya's stream in project P never reads
    outside P.
  * Runs the skill as a pure read on the graph / KB.
  * Returns a uniform `{"ok": True, "result": {...}}` or
    `{"ok": False, "error": "..."}` envelope the caller can persist as
    an `edge-tool-result` system message body.

Skills are strictly read-only. None of them mutate the graph. This is
the invariant that makes bounded agent-loops safe: the system can
execute a tool call without asking the user, because the worst case
is "I wasted a token budget," not "I silently changed state."

Skill catalog (kept in lockstep with the respond prompt and with
`workgraph_agents.edge.ALLOWED_SKILLS`):

  * kb_search(query: str, limit: int = 3)
      → list of {id, source_kind, summary, tags, created_at}

  * recent_decisions(limit: int = 5)
      → list of {id, rationale, custom_text, option_index,
                 source_suggestion_id, created_at}

  * risk_scan(severity_floor: "low"|"medium"|"high" = "medium")
      → list of {id, title, content, severity, status, created_at}

  * member_profile(user_id: str)
      → {user_id, username, display_name, role, declared_abilities,
         role_hints, signal_tally}
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import ALLOWED_SKILLS
from workgraph_persistence import (
    DecisionRepository,
    MembraneSignalRepository,
    ProjectMemberRepository,
    RiskRow,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.skills")


# Severity ordering used by risk_scan. Higher index → higher severity.
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

# Cap responses so a runaway LLM loop can't accidentally pull megabytes.
_KB_SEARCH_MAX_LIMIT = 20
_RECENT_DECISIONS_MAX_LIMIT = 20


class SkillsService:
    """Dispatcher for read-only skills the EdgeAgent may invoke."""

    # Re-export so callers can introspect without importing from agents.
    allowed_skills = frozenset(ALLOWED_SKILLS)

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def execute(
        self, *, project_id: str, skill_name: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Dispatch by skill_name. Returns `{ok, result}` on success,
        `{ok: False, error}` on failure.

        The envelope shape stays uniform so the PersonalStreamService
        can persist the result as a JSON system-message body without
        branching per skill.
        """
        args = dict(args or {})
        if skill_name not in self.allowed_skills:
            return {"ok": False, "error": "unknown_skill"}

        try:
            if skill_name == "kb_search":
                result = await self._kb_search(project_id=project_id, **args)
            elif skill_name == "recent_decisions":
                result = await self._recent_decisions(
                    project_id=project_id, **args
                )
            elif skill_name == "risk_scan":
                result = await self._risk_scan(project_id=project_id, **args)
            elif skill_name == "member_profile":
                result = await self._member_profile(
                    project_id=project_id, **args
                )
            else:  # defensive — already guarded above
                return {"ok": False, "error": "unknown_skill"}
        except TypeError as e:
            # Wrong arg shape from the LLM — surface as a clean error
            # rather than exploding the whole turn.
            _log.warning(
                "skills.execute invalid_args",
                extra={"skill": skill_name, "error": str(e)},
            )
            return {"ok": False, "error": "invalid_args", "detail": str(e)}
        except Exception:
            _log.exception(
                "skills.execute raised", extra={"skill": skill_name}
            )
            return {"ok": False, "error": "skill_failed"}

        return {"ok": True, "skill": skill_name, "result": result}

    # ------------------------------------------------------------------
    # Skill implementations.
    # ------------------------------------------------------------------

    async def _kb_search(
        self,
        *,
        project_id: str,
        query: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Simple text-match over MembraneSignalRow content + classification.

        v1: case-insensitive substring match on raw_content, summary, and
        tags. Full-text / vector search is a v2 concern. Rejected rows
        never surface.
        """
        q = (query or "").strip().lower()
        try:
            limit_val = max(1, min(int(limit), _KB_SEARCH_MAX_LIMIT))
        except (TypeError, ValueError):
            limit_val = 3

        async with session_scope(self._sessionmaker) as session:
            repo = MembraneSignalRepository(session)
            # Pull more than `limit` so we can post-filter by substring
            # without losing recall; cap hard at 200 rows for the scan.
            rows = await repo.list_for_project(project_id, limit=200)
            # Exclude rejected — stale content the graph explicitly said
            # should never surface. Everything else is fair game.
            rows = [r for r in rows if r.status != "rejected"]

        matched: list[dict[str, Any]] = []
        for row in rows:
            classification = dict(row.classification_json or {})
            summary = (classification.get("summary") or "")
            tags = list(classification.get("tags") or [])
            haystack_parts = [
                (row.raw_content or "").lower(),
                summary.lower(),
                " ".join(str(t).lower() for t in tags),
            ]
            if q and not any(q in part for part in haystack_parts):
                continue
            matched.append(
                {
                    "id": row.id,
                    "source_kind": row.source_kind,
                    "source_identifier": row.source_identifier,
                    "summary": summary[:200] if summary else (row.raw_content or "")[:200],
                    "tags": tags,
                    "status": row.status,
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )
            if len(matched) >= limit_val:
                break
        return matched

    async def _recent_decisions(
        self, *, project_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return the N most recent DecisionRows for this project."""
        try:
            limit_val = max(1, min(int(limit), _RECENT_DECISIONS_MAX_LIMIT))
        except (TypeError, ValueError):
            limit_val = 5

        async with session_scope(self._sessionmaker) as session:
            repo = DecisionRepository(session)
            rows = await repo.list_for_project(project_id, limit=limit_val)

        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "rationale": r.rationale or "",
                    "custom_text": r.custom_text,
                    "option_index": r.option_index,
                    "source_suggestion_id": r.source_suggestion_id,
                    "conflict_id": r.conflict_id,
                    "apply_outcome": r.apply_outcome,
                    "resolver_id": r.resolver_id,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
            )
        return out

    async def _risk_scan(
        self,
        *,
        project_id: str,
        severity_floor: str = "medium",
    ) -> list[dict[str, Any]]:
        """Return open RiskRows at or above `severity_floor`.

        Anything the graph hasn't marked 'closed' / 'resolved' counts as
        open in v1 — the field is free-form. "status == open" is the
        canonical value per _GraphEntityBase default.
        """
        floor = (severity_floor or "medium").lower()
        floor_rank = _SEVERITY_ORDER.get(floor)
        if floor_rank is None:
            return []

        async with session_scope(self._sessionmaker) as session:
            stmt = (
                select(RiskRow)
                .where(RiskRow.project_id == project_id)
                .order_by(RiskRow.sort_order)
            )
            rows = list((await session.execute(stmt)).scalars().all())

        out: list[dict[str, Any]] = []
        for r in rows:
            if r.status in ("closed", "resolved", "dismissed"):
                continue
            sev = (r.severity or "medium").lower()
            sev_rank = _SEVERITY_ORDER.get(sev, 1)
            if sev_rank < floor_rank:
                continue
            out.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "severity": sev,
                    "status": r.status,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
            )
        return out

    async def _member_profile(
        self, *, project_id: str, user_id: str
    ) -> dict[str, Any]:
        """Return the member's profile ONLY if they belong to this project.

        Scoping by project membership is the authorization boundary: a
        skill call from project A cannot read profile fields of a user
        who only belongs to project B. Returns an `{error}`-shaped dict
        inside the result on miss, so the caller can surface "no such
        member" without raising.
        """
        async with session_scope(self._sessionmaker) as session:
            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, user_id):
                return {"error": "not_a_project_member"}
            user = await UserRepository(session).get(user_id)
            if user is None:
                return {"error": "user_not_found"}
            profile = dict(user.profile or {})

        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": (profile.get("role_hints") or [None])[0] or "member",
            "declared_abilities": list(
                profile.get("declared_abilities") or []
            ),
            "role_hints": list(profile.get("role_hints") or []),
            "signal_tally": dict(profile.get("signal_tally") or {}),
        }


__all__ = ["SkillsService"]
