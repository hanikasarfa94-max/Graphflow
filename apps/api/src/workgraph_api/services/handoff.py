"""HandoffService — Stage 3 skill succession.

When a project member departs or transitions out, the owner prepares a
handoff from {from_user_id} to {to_user_id}. Two layers transfer:

  * Role skills — already role-derived (SkillAtlasService.ROLE_SKILL_BUNDLES).
    Whoever holds the role gets them. This service snapshots which role
    skills the departing member held, so the brief can say "these are
    what you're inheriting by virtue of taking the role."

  * Profile-skill ROUTINES — the working patterns the departing member
    produced while in the project. Derived from their recent emissions
    (decisions resolved + routed signals answered) in the last 90 days.
    PII-stripped: stakeholders are referenced by role_hint, never by
    name; message bodies never quoted verbatim.

Lifecycle:
  1. prepare(project_id, from, to) — owner-only. Derives routines,
     persists as status='draft', returns the draft for UI review.
  2. finalize(handoff_id) — owner-only. Flips status='finalized'.
  3. for_successor(project_id, user_id) — returns finalized routines
     applicable to this user (one slice per predecessor, merged per
     skill).

PII stripping is enforced here at the derivation layer. The ORM column
contract (see orm.py:HandoffRow) only promises that `profile_skill_routines`
MAY be surfaced into agent prompts — so the contract lives in this file.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    DecisionRepository,
    HandoffRepository,
    ProjectMemberRepository,
    RoutedSignalRow,
    UserRepository,
    session_scope,
)

from .skill_atlas import ROLE_SKILL_BUNDLES

_log = logging.getLogger("workgraph.api.handoff")

# Observation window for derivation. 90d is long enough to capture a
# sprint's worth of decisions + routings; shorter (30d) undersamples a
# member who's in a quiet phase. If the member joined less than 90d
# ago, we still query all their emissions; no lower bound.
_OBSERVATION_DAYS = 90


def _aware(dt: datetime) -> datetime:
    """SQLite via aiosqlite returns naive datetimes even when the column
    is declared timezone=True. Coerce to UTC-aware for safe comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Shape returned inside profile_skill_routines for each skill-keyed
# routine. Same as the persisted JSON; keeping this close to the
# service makes the contract concrete.
@dataclass
class _RoutineDraft:
    skill: str
    summary: str
    evidence_count: int
    applies_to_roles: list[str]
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "summary": self.summary,
            "evidence_count": self.evidence_count,
            "applies_to_roles": list(self.applies_to_roles),
            "sources": list(self.sources),
        }


# Best-effort map from action-kind → inferred skill. When the departing
# member resolved a decision whose apply_actions included e.g. a
# close_risk, we credit them for "risk-management" in the routine
# summary. This is a conservative heuristic; v2 replaces it with an
# explicit skill classifier on the decision itself.
_ACTION_KIND_TO_SKILL: dict[str, str] = {
    "close_risk": "risk-management",
    "open_risk": "risk-management",
    "adjust_scope": "scope-decisions",
    "reassign_task": "team-coordination",
    "defer_milestone": "scope-decisions",
    "resolve_conflict": "decision-making",
}


class HandoffService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    # --- internal helpers -------------------------------------------------

    async def _is_owner(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            for r in await ProjectMemberRepository(
                session
            ).list_for_project(project_id):
                if r.user_id == user_id:
                    return r.role == "owner"
        return False

    async def _member_roles(
        self, project_id: str
    ) -> dict[str, list[str]]:
        """user_id → role_hints for each project member.

        Used to translate raw user_ids in evidence into role_hint
        references — the core PII-stripping move. Users not found are
        omitted so the derivation can't leak a stale row."""
        mapping: dict[str, list[str]] = {}
        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            for m in members:
                user = await UserRepository(session).get(m.user_id)
                if user is None:
                    continue
                profile = dict(user.profile or {})
                hints = list(profile.get("role_hints") or [])
                mapping[m.user_id] = hints
        return mapping

    async def _user_display(self, user_id: str) -> str:
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
            return user.display_name or user.username if user else ""

    async def _user_profile(self, user_id: str) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
            return dict(user.profile or {}) if user else {}

    async def _recent_decisions(
        self, project_id: str, resolver_id: str
    ) -> list[Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=_OBSERVATION_DAYS
        )
        async with session_scope(self._sessionmaker) as session:
            decisions = await DecisionRepository(
                session
            ).list_for_project(project_id, limit=500)
        return [
            d
            for d in decisions
            if d.resolver_id == resolver_id
            and _aware(d.created_at) >= cutoff
        ]

    async def _recent_routings_out(
        self, project_id: str, source_user_id: str
    ) -> list[RoutedSignalRow]:
        """Fetch routings this user OUTBOUND — i.e. questions they
        routed to others — within the observation window. These are a
        complementary signal to decisions: how they delegate. We also
        pull INBOUND later to capture how they ANSWER.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=_OBSERVATION_DAYS
        )
        async with session_scope(self._sessionmaker) as session:
            stmt = (
                select(RoutedSignalRow)
                .where(RoutedSignalRow.project_id == project_id)
                .where(RoutedSignalRow.source_user_id == source_user_id)
                .where(RoutedSignalRow.created_at >= cutoff)
            )
            return list(
                (await session.execute(stmt)).scalars().all()
            )

    async def _recent_routings_in(
        self, project_id: str, target_user_id: str
    ) -> list[RoutedSignalRow]:
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=_OBSERVATION_DAYS
        )
        async with session_scope(self._sessionmaker) as session:
            stmt = (
                select(RoutedSignalRow)
                .where(RoutedSignalRow.project_id == project_id)
                .where(RoutedSignalRow.target_user_id == target_user_id)
                .where(RoutedSignalRow.created_at >= cutoff)
            )
            return list(
                (await session.execute(stmt)).scalars().all()
            )

    # --- derivation -------------------------------------------------------

    def _derive_routines(
        self,
        *,
        role_skills: list[str],
        decisions: list[Any],
        outbound_routings: list[RoutedSignalRow],
        inbound_routings: list[RoutedSignalRow],
        member_roles: dict[str, list[str]],
    ) -> list[_RoutineDraft]:
        """Produce the PII-stripped routine list.

        Strategy:
          1. For each decision, infer a skill from its apply_actions
             kinds; default to 'decision-making'.
          2. For each answered inbound routing, credit
             'expertise-routing'.
          3. For each outbound routing, credit 'team-coordination'.
          4. Stakeholder refs for the summary are taken from
             member_roles (user_id → role_hints); raw user_ids never
             appear in output.
          5. Only skills with at least one evidence entry are emitted.
             Skills from role_skills without evidence are still listed
             in role_skills_transferred separately — those are imposed,
             not earned.
        """
        evidence: dict[str, int] = defaultdict(int)
        sources: dict[str, set[str]] = defaultdict(set)
        stakeholder_roles: dict[str, set[str]] = defaultdict(set)

        for dec in decisions:
            skill_bucket = "decision-making"
            for action in dec.apply_actions or []:
                kind = (action or {}).get("kind") if isinstance(action, dict) else None
                mapped = _ACTION_KIND_TO_SKILL.get(kind or "")
                if mapped:
                    skill_bucket = mapped
                    break
            evidence[skill_bucket] += 1
            sources[skill_bucket].add("decision")

        for routing in inbound_routings:
            if (routing.reply_json or {}).get("kind"):
                # Only count answered routings as "expertise" evidence.
                evidence["expertise-routing"] += 1
                sources["expertise-routing"].add("routing")
                # Stakeholder = the person who asked. Translate their
                # user_id to role_hints via member_roles.
                for hint in member_roles.get(routing.source_user_id, []):
                    stakeholder_roles["expertise-routing"].add(hint)

        for routing in outbound_routings:
            evidence["team-coordination"] += 1
            sources["team-coordination"].add("routing")
            for hint in member_roles.get(routing.target_user_id, []):
                stakeholder_roles["team-coordination"].add(hint)

        routines: list[_RoutineDraft] = []
        for skill, count in sorted(
            evidence.items(), key=lambda kv: -kv[1]
        ):
            stakeholders = sorted(stakeholder_roles.get(skill, set()))
            is_role_skill = skill in role_skills
            summary = self._summarize(
                skill=skill,
                count=count,
                is_role_skill=is_role_skill,
                stakeholder_roles=stakeholders,
                source_kinds=sorted(sources[skill]),
            )
            routines.append(
                _RoutineDraft(
                    skill=skill,
                    summary=summary,
                    evidence_count=count,
                    applies_to_roles=stakeholders,
                    sources=sorted(sources[skill]),
                )
            )
        return routines

    def _summarize(
        self,
        *,
        skill: str,
        count: int,
        is_role_skill: bool,
        stakeholder_roles: list[str],
        source_kinds: list[str],
    ) -> str:
        """Produce the one-line human-readable routine summary.

        PII-stripped by construction: the template fills only
        skill/count/source-kind/role-hint strings. User display names
        never enter this function.
        """
        source_phrase = " and ".join(source_kinds) if source_kinds else "activity"
        role_phrase = (
            ", typically with the " + ", ".join(stakeholder_roles)
            if stakeholder_roles
            else ""
        )
        origin_phrase = (
            " — this is a role-imposed skill they exercised"
            if is_role_skill
            else " — this is a profile-earned pattern"
        )
        plural = "s" if count != 1 else ""
        return (
            f"{count} {source_phrase} event{plural} around "
            f"`{skill}`{role_phrase}{origin_phrase}."
        )

    # --- public API -------------------------------------------------------

    async def prepare(
        self,
        *,
        project_id: str,
        from_user_id: str,
        to_user_id: str,
        viewer_user_id: str,
    ) -> dict[str, Any]:
        """Build + persist a draft handoff. Returns a payload the UI
        renders for owner review. Errors map to service-level codes."""
        if from_user_id == to_user_id:
            return {"ok": False, "error": "same_user"}
        if not await self._is_owner(
            project_id=project_id, user_id=viewer_user_id
        ):
            return {"ok": False, "error": "not_owner"}

        member_roles = await self._member_roles(project_id)
        if from_user_id not in member_roles:
            return {"ok": False, "error": "from_not_member"}
        if to_user_id not in member_roles:
            return {"ok": False, "error": "to_not_member"}

        from_role_hints = member_roles[from_user_id]
        role_skills = self._resolve_role_skills(from_role_hints)

        decisions = await self._recent_decisions(
            project_id, from_user_id
        )
        outbound = await self._recent_routings_out(
            project_id, from_user_id
        )
        inbound = await self._recent_routings_in(
            project_id, from_user_id
        )

        routines = self._derive_routines(
            role_skills=role_skills,
            decisions=decisions,
            outbound_routings=outbound,
            inbound_routings=inbound,
            member_roles=member_roles,
        )

        from_display = await self._user_display(from_user_id)
        to_display = await self._user_display(to_user_id)
        from_profile = await self._user_profile(from_user_id)

        brief = self._render_brief(
            from_display=from_display,
            to_display=to_display,
            role_hints=from_role_hints,
            role_skills=role_skills,
            declared_abilities=list(
                (from_profile.get("declared_abilities") or [])
            ),
            routines=routines,
        )

        async with session_scope(self._sessionmaker) as session:
            row = await HandoffRepository(session).create(
                project_id=project_id,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                role_skills_transferred=role_skills,
                profile_skill_routines=[r.to_dict() for r in routines],
                brief_markdown=brief,
                from_display_name=from_display,
                to_display_name=to_display,
            )

        _log.info(
            "handoff.prepared",
            extra={
                "handoff_id": row.id,
                "project_id": project_id,
                "from": from_user_id,
                "to": to_user_id,
                "role_skills": len(role_skills),
                "routines": len(routines),
            },
        )
        return {
            "ok": True,
            "handoff": self._serialize(row),
        }

    async def finalize(
        self, *, handoff_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await HandoffRepository(session).get(handoff_id)
        if row is None:
            return {"ok": False, "error": "not_found"}
        if not await self._is_owner(
            project_id=row.project_id, user_id=viewer_user_id
        ):
            return {"ok": False, "error": "not_owner"}
        if row.status == "finalized":
            return {"ok": True, "handoff": self._serialize(row)}
        async with session_scope(self._sessionmaker) as session:
            row = await HandoffRepository(session).finalize(handoff_id)
        _log.info(
            "handoff.finalized",
            extra={"handoff_id": handoff_id},
        )
        return {"ok": True, "handoff": self._serialize(row)}

    async def list_for_project(
        self, *, project_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        # Owner sees all handoffs on the project; non-owner sees only
        # handoffs where they are the successor (so they can inspect
        # what was transferred into their own skill map).
        is_owner = await self._is_owner(
            project_id=project_id, user_id=viewer_user_id
        )
        async with session_scope(self._sessionmaker) as session:
            rows = await HandoffRepository(session).list_for_project(
                project_id
            )
        if not is_owner:
            rows = [r for r in rows if r.to_user_id == viewer_user_id]
        return {
            "viewer_scope": "owner" if is_owner else "successor",
            "handoffs": [self._serialize(r) for r in rows],
        }

    async def for_successor(
        self, *, project_id: str, user_id: str
    ) -> dict[str, Any]:
        """Return the merged routine map for a successor.

        Routines from multiple predecessors are merged per-skill: the
        evidence_count is summed, applies_to_roles unioned, sources
        unioned. A single summary is synthesized so the successor's
        agent gets one line per inherited skill.
        """
        async with session_scope(self._sessionmaker) as session:
            rows = await HandoffRepository(
                session
            ).list_finalized_for_successor(
                project_id=project_id, to_user_id=user_id
            )

        per_skill_count: dict[str, int] = defaultdict(int)
        per_skill_roles: dict[str, set[str]] = defaultdict(set)
        per_skill_sources: dict[str, set[str]] = defaultdict(set)
        role_skills: set[str] = set()
        predecessors: list[dict[str, Any]] = []
        for r in rows:
            role_skills.update(r.role_skills_transferred or [])
            predecessors.append(
                {
                    "handoff_id": r.id,
                    "from_display_name": r.from_display_name,
                    "finalized_at": (
                        r.finalized_at.isoformat()
                        if r.finalized_at
                        else None
                    ),
                }
            )
            for routine in r.profile_skill_routines or []:
                skill = (routine or {}).get("skill") or ""
                if not skill:
                    continue
                per_skill_count[skill] += int(
                    (routine or {}).get("evidence_count", 0)
                )
                for rr in (routine or {}).get("applies_to_roles", []) or []:
                    per_skill_roles[skill].add(rr)
                for src in (routine or {}).get("sources", []) or []:
                    per_skill_sources[skill].add(src)

        merged: list[dict[str, Any]] = []
        for skill, count in sorted(
            per_skill_count.items(), key=lambda kv: -kv[1]
        ):
            roles = sorted(per_skill_roles[skill])
            sources = sorted(per_skill_sources[skill])
            merged.append(
                {
                    "skill": skill,
                    "evidence_count": count,
                    "applies_to_roles": roles,
                    "sources": sources,
                    "summary": self._summarize(
                        skill=skill,
                        count=count,
                        is_role_skill=skill in role_skills,
                        stakeholder_roles=roles,
                        source_kinds=sources,
                    ),
                }
            )
        return {
            "project_id": project_id,
            "successor_user_id": user_id,
            "inherited_role_skills": sorted(role_skills),
            "inherited_routines": merged,
            "predecessors": predecessors,
        }

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _resolve_role_skills(role_hints: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for hint in role_hints or []:
            for skill in ROLE_SKILL_BUNDLES.get(hint.lower(), []):
                if skill not in seen:
                    seen.add(skill)
                    out.append(skill)
        return out

    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "from_user_id": row.from_user_id,
            "to_user_id": row.to_user_id,
            "from_display_name": row.from_display_name,
            "to_display_name": row.to_display_name,
            "status": row.status,
            "role_skills_transferred": list(
                row.role_skills_transferred or []
            ),
            "profile_skill_routines": list(
                row.profile_skill_routines or []
            ),
            "brief_markdown": row.brief_markdown,
            "created_at": row.created_at.isoformat(),
            "finalized_at": (
                row.finalized_at.isoformat() if row.finalized_at else None
            ),
        }

    @staticmethod
    def _render_brief(
        *,
        from_display: str,
        to_display: str,
        role_hints: list[str],
        role_skills: list[str],
        declared_abilities: list[str],
        routines: list[_RoutineDraft],
    ) -> str:
        """Human-readable preview for the owner. Display names are
        allowed here (this column never reaches agent prompts). No
        user_ids, no message bodies."""
        lines: list[str] = []
        lines.append(
            f"# Handoff: {from_display} → {to_display}"
        )
        lines.append("")
        lines.append(
            f"**Role held**: {', '.join(role_hints) if role_hints else '(none declared)'}"
        )
        lines.append("")
        if role_skills:
            lines.append("## Role skills the successor inherits")
            for s in role_skills:
                lines.append(f"- `{s}`")
            lines.append("")
        if declared_abilities:
            lines.append("## Self-declared abilities (not transferred)")
            lines.append(
                "These stayed with the departing member (declarations "
                "are personal). Listed here for context only:"
            )
            for a in declared_abilities:
                lines.append(f"- `{a}`")
            lines.append("")
        if routines:
            lines.append("## Working routines (PII-stripped, agent-facing)")
            for r in routines:
                lines.append(f"- **`{r.skill}`** — {r.summary}")
            lines.append("")
        else:
            lines.append("## Working routines")
            lines.append(
                "_No recent emissions matched the observation window. "
                "Successor inherits only role skills._"
            )
            lines.append("")
        lines.append(
            "> Successor's sub-agent consults the routine layer for "
            "skill-keyed context. Display names, raw message bodies, "
            "and user IDs are never included in the routine data."
        )
        return "\n".join(lines)


__all__ = ["HandoffService"]
