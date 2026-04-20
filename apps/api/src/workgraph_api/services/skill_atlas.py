"""SkillAtlasService — per-member capability inventory.

Naming note: there are TWO "skill" concepts in this repo. Keep them
straight:

  * `services/skills.py` (SkillsService) — edge-LLM tool dispatcher.
    Registers tool handlers the agent can invoke (kb_search, why_chain,
    routing_suggest, ...). Scoped to a single user's personal stream.

  * `services/skill_atlas.py` (this file; SkillAtlasService) — the
    GROUP'S capability map. "What does this team collectively know and
    can do?" Renders at /projects/{id}/skills.

Two skill types locked to every project member:

  * **Role skill** — imposed by their functional role (game-director,
    qa-lead, eng-lead, etc.). Derived from `UserRow.profile.role_hints`
    via ROLE_SKILL_BUNDLES. Stays with the role; on handoff, the new
    occupant inherits these.

  * **Profile skill** — seeded by the member's self-declared abilities
    at onboarding (`UserRow.profile.declared_abilities`) + validated
    over time by observed emissions (the Sprint 2a profile tallies).
    Stays with the person; non-PII *working routines* pass to a
    successor on handoff.

Visibility (per user's product spec):
  * project owners see the full atlas — all members, both skill types
  * non-owners see ONLY their own card

v2 adds:
  * Role ORM entity with editable role→skill mapping (today's
    ROLE_SKILL_BUNDLES is a hardcoded starter)
  * Skills as graph nodes with edges to decisions/tasks they resolved
  * Pre-answer routing: target's edge runs a skill-scoped draft before
    the actual route fires (the killer feature)
  * Handoff (R11) that auto-transfers skills on member departure
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    ProjectMemberRepository,
    UserRepository,
    session_scope,
)

from .profile_tallies import compute_profile

_log = logging.getLogger("workgraph.api.skill_atlas")


# Hardcoded role → skill bundles (v1). The roles here match the
# values stored in UserRow.profile.role_hints from the Stellar Drift
# seed + any new roles a member declares. Missing roles return [] so
# a member with no role_hints renders an empty Role Skills section
# without error. v2 replaces this with a Role ORM row the owner can
# edit per-project.
ROLE_SKILL_BUNDLES: dict[str, list[str]] = {
    # leadership
    "founder": ["vision-setting", "scope-decisions", "fundraising"],
    "ceo": ["vision-setting", "scope-decisions", "fundraising"],
    "game-director": [
        "scope-decisions",
        "design-vision",
        "team-coordination",
    ],
    # design
    "design-lead": [
        "systems-design",
        "balance-tuning",
        "design-coordination",
    ],
    "game-design": ["systems-design", "balance-tuning"],
    # engineering
    "engineering-lead": [
        "systems-architecture",
        "performance",
        "eng-coordination",
    ],
    "tech-lead": ["systems-architecture", "performance"],
    "junior-engineer": ["implementation"],
    "backend": ["implementation", "systems-architecture"],
    # art
    "art-director": ["art-direction", "style-coherence", "pipeline"],
    "art-lead": ["art-direction", "pipeline"],
    # qa / community
    "qa-community-lead": [
        "playtest-coordination",
        "external-data",
        "community-mgmt",
    ],
    "qa-lead": ["playtest-coordination", "external-data"],
    "qa": ["playtest-coordination"],
}


# Map observed tally fields → a "validated" skill tag that appears
# once the emission count crosses a light threshold. Distinct from
# declared abilities — these are skills the graph has SEEN the member
# exercise, regardless of whether they claimed them.
_OBSERVED_SIGNAL_SKILLS: list[tuple[str, int, str]] = [
    ("messages_posted_30d", 10, "communication"),
    ("decisions_resolved_30d", 1, "decision-making"),
    ("risks_owned", 1, "risk-management"),
    ("routings_answered_30d", 3, "expertise-routing"),
]


def _resolve_role_skills(role_hints: list[str]) -> list[str]:
    """Combine skill bundles for every role the member claims. Dedup
    while preserving first-seen order so the most-primary role's
    skills appear first."""
    seen: set[str] = set()
    out: list[str] = []
    for hint in role_hints or []:
        bundle = ROLE_SKILL_BUNDLES.get(hint.lower(), [])
        for skill in bundle:
            if skill not in seen:
                seen.add(skill)
                out.append(skill)
    return out


def _resolve_observed_skills(observed: dict[str, int]) -> list[str]:
    """Which skills has the graph actually seen this member exercise?
    Light thresholds on each signal — crossing any threshold adds the
    corresponding skill tag. Matches the "gap between declared and
    observed is itself information" north-star note: showing both
    lets the viewer see where a declaration hasn't been validated."""
    out: list[str] = []
    for field, threshold, skill in _OBSERVED_SIGNAL_SKILLS:
        if int(observed.get(field, 0)) >= threshold:
            out.append(skill)
    return out


class SkillAtlasService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def _is_owner(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            rows = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            for r in rows:
                if r.user_id == user_id:
                    return r.role == "owner"
            return False

    async def _member_card(
        self, *, session, user_id: str, role: str
    ) -> dict[str, Any] | None:
        """Build a single member card. Returns None if the user row
        is missing (shouldn't happen for a live member but defensive
        — avoids crashing the whole atlas on a half-deleted user)."""
        user = await UserRepository(session).get(user_id)
        if user is None:
            return None
        profile = dict(user.profile or {})
        role_hints = list(profile.get("role_hints") or [])
        declared = list(profile.get("declared_abilities") or [])
        tallies = await compute_profile(session, user_id)
        obs = tallies.observed
        observed_dict: dict[str, int] = {
            "messages_posted_30d": obs.messages_posted_30d,
            "decisions_resolved_30d": obs.decisions_resolved_30d,
            "risks_owned": obs.risks_owned,
            "routings_answered_30d": obs.routings_answered_30d,
        }
        role_skills = _resolve_role_skills(role_hints)
        observed_skills = _resolve_observed_skills(observed_dict)
        # Validated declared abilities = declared ∩ observed-signal-skills
        # plus declared abilities that share a token with an observed
        # skill (light fuzzy match). v2 swaps the fuzzy matcher for
        # an embedding-based similarity lookup.
        validated: set[str] = set()
        decl_lower = {d.lower() for d in declared}
        for obs_skill in observed_skills:
            if obs_skill in decl_lower:
                validated.add(obs_skill)
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "project_role": role,
            "role_hints": role_hints,
            "role_skills": role_skills,
            "profile_skills_declared": declared,
            "profile_skills_observed": observed_skills,
            "profile_skills_validated": sorted(validated),
            "observed_tallies": observed_dict,
            "last_activity_at": (
                tallies.last_activity_at.isoformat()
                if tallies.last_activity_at
                else None
            ),
        }

    async def atlas_for_project(
        self, *, project_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        """Build the capability atlas for a project.

        Visibility rule (hard-coded v1, per product spec):
          * viewer with project role == 'owner' sees every member
          * anyone else sees only their own card

        The payload shape is stable either way; only the `members`
        array length differs. Clients key off `viewer_scope` to
        decide whether to render a "restricted view" banner.
        """
        viewer_is_owner = await self._is_owner(
            project_id=project_id, user_id=viewer_user_id
        )
        async with session_scope(self._sessionmaker) as session:
            member_rows = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            cards: list[dict[str, Any]] = []
            if viewer_is_owner:
                for m in member_rows:
                    card = await self._member_card(
                        session=session, user_id=m.user_id, role=m.role
                    )
                    if card is not None:
                        cards.append(card)
            else:
                viewer_member = next(
                    (m for m in member_rows if m.user_id == viewer_user_id),
                    None,
                )
                if viewer_member is not None:
                    card = await self._member_card(
                        session=session,
                        user_id=viewer_member.user_id,
                        role=viewer_member.role,
                    )
                    if card is not None:
                        cards.append(card)

        # Collective aggregation — only populated for the owner view.
        # It's the GROUP-level answer: what role-skill coverage do we
        # have, and where are the declared abilities without any
        # observed signal?
        collective: dict[str, Any] = {}
        if viewer_is_owner:
            all_role_skills: set[str] = set()
            all_declared: set[str] = set()
            all_observed_skills: set[str] = set()
            for c in cards:
                all_role_skills.update(c["role_skills"])
                all_declared.update(
                    a.lower() for a in c["profile_skills_declared"]
                )
                all_observed_skills.update(c["profile_skills_observed"])
            collective = {
                "role_skill_coverage": sorted(all_role_skills),
                "declared_abilities_combined": sorted(all_declared),
                "observed_skills_combined": sorted(all_observed_skills),
                # Unvalidated declarations: declared but nobody has
                # observed signal for them in the last window. Quick
                # proxy for "gaps" the group should be aware of.
                "unvalidated_declarations": sorted(
                    all_declared - all_observed_skills
                ),
            }

        return {
            "viewer_scope": "owner" if viewer_is_owner else "self",
            "members": cards,
            "collective": collective,
        }


__all__ = ["SkillAtlasService", "ROLE_SKILL_BUNDLES"]
