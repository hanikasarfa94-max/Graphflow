"""OrgCapabilityService — read-only Trust Ladder projection (Org Graph v1).

Closes the north-star claim "skill is not a tag; it is a projection over
evidence" enough for v1: a member's capabilities are derived from
multiple evidence sources, not just `users.profile.declared_abilities`.

Levels (from the doc's Shared Trust Ladder):

  declared  — the user's profile says they have this skill.
  role      — inferred from ProjectMemberRow.skill_tags (per-project).
  observed  — the graph shows them touching the topic (decisions
              they resolved, tasks they were assigned to). The
              system has seen them work near the skill.
  validated — at least one piece of accepted evidence: source
              accepted their routed reply, OR a task assigned to
              them that mentions the skill landed at status='done'.
  trusted   — repeated validated evidence (≥ TRUSTED_THRESHOLD
              distinct rows). Conservative — we want a high-bar
              signal, not "active member".

Skill keys come from a closed set per member: declared_abilities ∪
role_hints ∪ skill_tags. The projection NEVER invents a new skill
from row text — it only promotes a level when one of those keys
appears in the relevant row's text. That keeps the test promise
"no capability evidence is invented from unrelated text" honest.

Output shape (per spec):

  {
    "user_id": str,
    "display_name": str,
    "capabilities": [
      {
        "skill_key": str,            # the original token
        "label": str,                # human-readable ("compliance")
        "level": Literal[...],
        "confidence": float,         # 0..1
        "evidence_refs": list[FlowRef],
        "last_seen_at": iso8601 | None,
        "signals": {
          "declared_count": int,
          "routed_answer_count": int,
          "accepted_reply_count": int,
          "completed_task_count": int,
          "decision_citation_count": int,
        },
      },
      ...
    ],
  }

Read-only: no UserRow.profile mutation, no signal_tally writes here.
The projection runs against the current graph state on every call.
SignalTallyService remains the persistent counter for non-skill-keyed
aggregates; this service is the skill-keyed view.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    AssignmentRepository,
    DecisionRepository,
    ProjectMemberRepository,
    RoutedSignalRow,
    TaskRow,
    UserRepository,
    session_scope,
)


_log = logging.getLogger("workgraph.api.org_capabilities")


CapabilityLevel = Literal[
    "declared", "role", "observed", "validated", "trusted"
]


# Conservative thresholds — moving up the ladder requires real
# evidence, not active-member noise. Documented here so reviewers can
# see the math without reading code.
#
# OBSERVED_THRESHOLD: at least one observed-level signal (assigned
#   task / resolved decision / answered route) where the skill_key
#   appears in the row's text.
# VALIDATED_THRESHOLD: at least one validated-level signal:
#   - accepted RoutedSignalRow they were the target of, with skill
#     in the framing/options/reply
#   - completed TaskRow assigned to them, with skill in title/desc.
# TRUSTED_THRESHOLD: ≥ 3 distinct validated rows. Two could happen
#   by accident on a 5-week project; three is harder.
OBSERVED_THRESHOLD = 1
VALIDATED_THRESHOLD = 1
TRUSTED_THRESHOLD = 3


# Confidence per level — bounded, monotonic, deliberately not
# "calibrated probability". Surfaced so the routing rank can use a
# softer-than-binary signal without loss of meaning.
_LEVEL_CONFIDENCE: dict[CapabilityLevel, float] = {
    "declared": 0.30,
    "role": 0.45,
    "observed": 0.60,
    "validated": 0.78,
    "trusted": 0.92,
}


# Levels in ascending order — useful for "is X >= Y" comparisons in
# routing rank.
_LEVEL_ORDER: dict[CapabilityLevel, int] = {
    "declared": 0,
    "role": 1,
    "observed": 2,
    "validated": 3,
    "trusted": 4,
}


def level_at_least(level: str, threshold: str) -> bool:
    """Public helper for callers (routing rank) that need to gate on
    "is this capability at least validated?". Tolerates unknown level
    strings by returning False — never blow up the caller."""
    a = _LEVEL_ORDER.get(level, -1)
    b = _LEVEL_ORDER.get(threshold, 99)
    return a >= b


class OrgCapabilityService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def list_for_project(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        """Project capabilities for every member of `project_id`.

        Returns one entry per member with their skill-keyed
        capability list. Members without any candidate skill_keys
        still appear (with `capabilities: []`) so consumers can
        distinguish "no skills declared" from "user not in project".
        """
        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            if not members:
                return []
            user_repo = UserRepository(session)

            # Pre-fetch the row families we'll scan for evidence. One
            # query each; we do the python-side text match locally
            # since skill_keys are short and row counts are bounded
            # at v1 scale.
            #
            # Routed signals — both directions; we only credit the
            # target (the answerer) for now. accepted status →
            # validated evidence; replied (no accept yet) → observed
            # evidence.
            routed_rows = list(
                (
                    await session.execute(
                        select(RoutedSignalRow)
                        .where(RoutedSignalRow.project_id == project_id)
                    )
                )
                .scalars()
                .all()
            )

            # Tasks — assigned + status. We need the assignment and the
            # task in hand to test "is this assignee credited for that
            # skill". list_for_project on AssignmentRepository handles
            # the join lookup.
            assignments = await AssignmentRepository(
                session
            ).list_for_project(project_id)
            task_repo_rows = (
                await session.execute(
                    select(TaskRow).where(TaskRow.project_id == project_id)
                )
            ).scalars().all()
            task_by_id = {t.id: t for t in task_repo_rows}

            # Decisions — resolver_id is the credit. custom_text +
            # rationale is the haystack.
            decisions = await DecisionRepository(session).list_for_project(
                project_id, limit=200
            )

            # Hydrate users in one go.
            users_by_id: dict[str, Any] = {}
            for m in members:
                u = await user_repo.get(m.user_id)
                if u is not None:
                    users_by_id[m.user_id] = u

        # ---- per-member projection ----
        out: list[dict[str, Any]] = []
        for m in members:
            user = users_by_id.get(m.user_id)
            if user is None:
                continue
            display_name = user.display_name or user.username
            profile = dict(user.profile or {})

            # Candidate skills: union of declared / role hints /
            # per-project skill_tags. NEVER invent new keys from text.
            declared = [
                str(s).strip()
                for s in (profile.get("declared_abilities") or [])
                if str(s).strip()
            ]
            role_hints = [
                str(s).strip()
                for s in (profile.get("role_hints") or [])
                if str(s).strip()
            ]
            project_skill_tags = [
                str(s).strip()
                for s in (m.skill_tags or [])
                if str(s).strip()
            ]
            # Skill source map — per skill, which families the key
            # came from. Lets us emit `level=role` when the source
            # was skill_tags vs `level=declared` when the source was
            # only profile.
            skill_sources: dict[str, set[str]] = {}
            for s in declared:
                skill_sources.setdefault(s.lower(), set()).add("declared")
            for s in role_hints:
                # role_hints sit in profile but the spec puts role
                # above declared on the ladder, so credit accordingly.
                skill_sources.setdefault(s.lower(), set()).add("role")
            for s in project_skill_tags:
                skill_sources.setdefault(s.lower(), set()).add("role")

            # Map back to a canonical-cased label for each lowercased
            # key — first source wins.
            label_by_key: dict[str, str] = {}
            for s in declared + role_hints + project_skill_tags:
                k = s.lower()
                if k not in label_by_key:
                    label_by_key[k] = s

            capabilities: list[dict[str, Any]] = []
            for skill_key, sources in skill_sources.items():
                # Evidence + signal counts for this (member, skill).
                accepted_refs: list[dict[str, Any]] = []
                replied_refs: list[dict[str, Any]] = []
                completed_task_refs: list[dict[str, Any]] = []
                assigned_task_refs: list[dict[str, Any]] = []
                decision_refs: list[dict[str, Any]] = []
                last_seen_at: str | None = None

                # Routed signals where this member is the target.
                for r in routed_rows:
                    if r.target_user_id != m.user_id:
                        continue
                    haystack_parts = [
                        (r.framing or "").lower(),
                    ]
                    if isinstance(r.options_json, list):
                        for opt in r.options_json:
                            if isinstance(opt, dict):
                                for fld in ("label", "background", "reason"):
                                    val = opt.get(fld)
                                    if isinstance(val, str):
                                        haystack_parts.append(val.lower())
                    if isinstance(r.reply_json, dict):
                        for fld in ("custom_text",):
                            val = r.reply_json.get(fld)
                            if isinstance(val, str):
                                haystack_parts.append(val.lower())
                    haystack = " ".join(haystack_parts)
                    if skill_key not in haystack:
                        continue
                    ref = {
                        "kind": "routed_signal",
                        "id": r.id,
                        "label": (r.framing or "")[:80],
                    }
                    last_seen_at = _max_iso(
                        last_seen_at, _to_iso(r.responded_at or r.created_at)
                    )
                    if r.status == "accepted":
                        accepted_refs.append(ref)
                    elif r.status in ("replied", "pending"):
                        replied_refs.append(ref)

                # Tasks where this member is the assignee.
                for a in assignments:
                    if a.user_id != m.user_id:
                        continue
                    if not getattr(a, "active", True):
                        continue
                    task = task_by_id.get(a.task_id)
                    if task is None:
                        continue
                    text = (
                        f"{(task.title or '').lower()}\n"
                        f"{(task.description or '').lower()}"
                    )
                    if skill_key not in text:
                        continue
                    ref = {
                        "kind": "task",
                        "id": task.id,
                        "label": (task.title or "")[:80],
                    }
                    last_seen_at = _max_iso(
                        last_seen_at, _to_iso(task.created_at)
                    )
                    if task.status == "done":
                        completed_task_refs.append(ref)
                    else:
                        assigned_task_refs.append(ref)

                # Decisions resolved by this member.
                for d in decisions:
                    if d.resolver_id != m.user_id:
                        continue
                    text = (
                        f"{(d.custom_text or '').lower()}\n"
                        f"{(d.rationale or '').lower()}"
                    )
                    if skill_key not in text:
                        continue
                    decision_refs.append(
                        {
                            "kind": "decision",
                            "id": d.id,
                            "label": (d.custom_text or "")[:80],
                        }
                    )
                    last_seen_at = _max_iso(
                        last_seen_at, _to_iso(d.created_at)
                    )

                # Tally signals.
                signals = {
                    "declared_count": 1 if "declared" in sources else 0,
                    "routed_answer_count": (
                        len(accepted_refs) + len(replied_refs)
                    ),
                    "accepted_reply_count": len(accepted_refs),
                    "completed_task_count": len(completed_task_refs),
                    "decision_citation_count": len(decision_refs),
                }

                # Level derivation — climb the ladder.
                #
                # Validated rows are the highest-trust observable: a
                # SOURCE-accepted reply or a completed task. Decisions
                # count as observed (the resolver was empowered to
                # decide, but we don't have a "this decision was reused"
                # signal yet — that's still aspirational, marked in the
                # report).
                validated_rows = (
                    len(accepted_refs) + len(completed_task_refs)
                )
                observed_rows = (
                    len(replied_refs)
                    + len(assigned_task_refs)
                    + len(decision_refs)
                )

                if validated_rows >= TRUSTED_THRESHOLD:
                    level: CapabilityLevel = "trusted"
                elif validated_rows >= VALIDATED_THRESHOLD:
                    level = "validated"
                elif observed_rows >= OBSERVED_THRESHOLD:
                    level = "observed"
                elif "role" in sources:
                    level = "role"
                else:
                    # Must be at least declared — we wouldn't get a
                    # skill_key here without one source.
                    level = "declared"

                evidence_refs: list[dict[str, Any]] = (
                    accepted_refs
                    + completed_task_refs
                    + replied_refs
                    + assigned_task_refs
                    + decision_refs
                )

                # E3 — light epistemic interpretation. Each capability
                # carries a tiny `epistemic` block so consumers reading
                # /capabilities see the same kind/status vocabulary
                # used elsewhere on the response shape.
                #
                # Mapping (per spec, conservative — does NOT overclaim):
                #   declared  → status='proposed' (self-claim only)
                #   role      → status='accepted_for_scope' for project
                #   observed  → status='proposed' (no accepted-for-scope
                #               evidence yet — observed != validated)
                #   validated → status='validated'
                #   trusted   → status='accepted_for_scope' for project
                #               (high confidence, but NOT canonical —
                #               canonical implies enterprise-wide truth
                #               we cannot project)
                if level == "declared":
                    ep_status = "proposed"
                    ep_accepted = None
                elif level == "role":
                    ep_status = "accepted_for_scope"
                    ep_accepted = {
                        "scope_type": "project",
                        "scope_id": project_id,
                        "accepted_by_user_ids": [],
                        "accepted_at": None,
                    }
                elif level == "observed":
                    ep_status = "proposed"
                    ep_accepted = None
                elif level == "validated":
                    ep_status = "validated"
                    ep_accepted = None
                else:  # trusted
                    ep_status = "accepted_for_scope"
                    ep_accepted = {
                        "scope_type": "project",
                        "scope_id": project_id,
                        "accepted_by_user_ids": [],
                        "accepted_at": last_seen_at,
                    }

                capabilities.append(
                    {
                        "skill_key": skill_key,
                        "label": label_by_key.get(skill_key, skill_key),
                        "level": level,
                        "confidence": _LEVEL_CONFIDENCE[level],
                        "evidence_refs": evidence_refs,
                        "last_seen_at": last_seen_at,
                        "signals": signals,
                        "epistemic": {
                            "kind": "capability_claim",
                            "status": ep_status,
                            "accepted_scope": ep_accepted,
                        },
                    }
                )

            # Stable ordering — by descending level, then alpha.
            capabilities.sort(
                key=lambda c: (
                    -_LEVEL_ORDER[c["level"]],
                    c["skill_key"],
                )
            )
            out.append(
                {
                    "user_id": m.user_id,
                    "display_name": display_name,
                    "capabilities": capabilities,
                }
            )
        return out


def _to_iso(dt) -> str | None:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except AttributeError:
        return str(dt)


def _max_iso(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


__all__ = [
    "OrgCapabilityService",
    "CapabilityLevel",
    "OBSERVED_THRESHOLD",
    "VALIDATED_THRESHOLD",
    "TRUSTED_THRESHOLD",
    "level_at_least",
]
