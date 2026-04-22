"""OnboardingService — Phase 1.B ambient onboarding.

North-star §5.11: "Day-1, 10 minutes replacing 2 weeks of ramp." A new
member's first visit to /projects/[id] opens a sub-agent-narrated
overlay covering their personal graph slice — vision commits, recent
decisions, adjacent teammates, their active tasks, and open risks.

Design choices:
  * License-scoped. Every section reads through LicenseContextService
    so an observer-tier auditor gets a narrower walkthrough than a
    full-tier member. The effective tier is surfaced in the payload
    so the UI can render a "restricted view" chip.
  * Citations reuse the `CitedClaim` shape from workgraph_agents —
    same chips the edge agent emits. The walkthrough is NOT itself
    a stream turn, but the UI can render it with the same
    <CitedClaimList> component.
  * Narration tone is templated, not LLM-generated. Rationale: the
    walkthrough is a structural tour of the user's slice (vision
    thesis → decisions → teammates → tasks → risks), not a freeform
    answer. Templated copy is cheaper, deterministic, translatable,
    and safer (no prompt-injection surface on the first page a new
    hire sees). The templated summaries still cite the backing
    nodes so the trust-by-citation contract holds.
  * Idempotent + cached. The structured walkthrough is cached on
    OnboardingStateRow.walkthrough_json for 24h. Replay clears the
    cache so re-runs pick up whatever landed since.

Ordering rationale (vision → decisions → teammates → tasks → risks):
  1. Vision first — "what are we doing here" is the prerequisite
     for everything else.
  2. Recent decisions — "what have we already settled" before you
     pile on new questions.
  3. Adjacent teammates — "who do you pair with" once you know the
     shared goals.
  4. Your active tasks — "what specifically is in your queue."
  5. Open risks — "what might bite us," last so it's fresh when the
     user closes the overlay and starts working.

This mirrors docs/north-star.md §5.11's "role → state → team →
assignments → hazards" chain.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents.citations import Citation, CitedClaim, claims_payload
from workgraph_persistence import (
    CommitmentRepository,
    OnboardingStateRepository,
    UserRepository,
    session_scope,
)

from .license_context import LicenseContextService


# Canonical section order + valid checkpoint values. The router
# enforces these so the client can't store a bogus checkpoint.
_SECTIONS: tuple[str, ...] = (
    "vision",
    "decisions",
    "teammates",
    "your_tasks",
    "open_risks",
)
VALID_CHECKPOINTS: frozenset[str] = frozenset(
    {"not_started", *_SECTIONS, "completed"}
)

# Cache TTL: regenerate walkthrough if the cached copy is older than
# this. 24h balances "graph changed since yesterday" against LLM /
# DB cost (the slice builder does a non-trivial read).
_CACHE_TTL_SECONDS = 24 * 60 * 60


@dataclass
class _Section:
    kind: str
    title: str
    body_md: str
    claims: list[CitedClaim]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "body_md": self.body_md,
            "claims": claims_payload(self.claims),
        }


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite via aiosqlite returns naive datetimes even on a
    timezone=True column. Coerce to UTC-aware for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class OnboardingService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        license_context_service: LicenseContextService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._license_ctx = license_context_service

    # ---- public API ------------------------------------------------------

    async def get_or_init_state(
        self, *, user_id: str, project_id: str
    ) -> tuple[dict[str, Any], bool]:
        """Return the serialized onboarding-state row + created flag.

        First-visit side effect: if no row exists, creates one with
        first_seen_at=now and last_checkpoint='not_started'.
        """
        async with session_scope(self._sessionmaker) as session:
            row, created = await OnboardingStateRepository(
                session
            ).get_or_create(user_id=user_id, project_id=project_id)
            serialized = self._serialize_state(row)
        return serialized, created

    async def build_walkthrough(
        self, *, user_id: str, project_id: str
    ) -> dict[str, Any]:
        """Build (or reuse) the structured walkthrough script.

        Shape:
            {
              sections: [{kind, title, body_md, claims[]}, ...],
              user_id, project_id, generated_at,
              license_tier, scope_user_id,
            }

        The cached copy on OnboardingStateRow.walkthrough_json is
        reused if it's still fresh (<24h). Regenerates otherwise.
        """
        async with session_scope(self._sessionmaker) as session:
            row = await OnboardingStateRepository(session).get(
                user_id=user_id, project_id=project_id
            )
            cached_json = row.walkthrough_json if row else None
            cached_at = _aware(row.walkthrough_generated_at) if row else None

        if cached_json and cached_at and self._is_fresh(cached_at):
            return dict(cached_json)

        slice_ = await self._license_ctx.build_slice(
            project_id=project_id,
            viewer_user_id=user_id,
            audience_user_id=None,
        )

        sections = await self._assemble_sections(
            user_id=user_id,
            project_id=project_id,
            slice_=slice_,
        )

        payload = {
            "sections": [s.to_dict() for s in sections],
            "user_id": user_id,
            "project_id": project_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "license_tier": slice_.get("license_tier", "full"),
            "scope_user_id": slice_.get("scope_user_id", user_id),
        }

        # Cache. If the row doesn't exist yet (caller invoked us
        # before hitting the state endpoint), we create one —
        # first_seen_at defaults to now, which is correct.
        async with session_scope(self._sessionmaker) as session:
            repo = OnboardingStateRepository(session)
            row = await repo.get(user_id=user_id, project_id=project_id)
            if row is None:
                await repo.create(user_id=user_id, project_id=project_id)
            await repo.cache_walkthrough(
                user_id=user_id,
                project_id=project_id,
                walkthrough=payload,
            )

        return payload

    async def advance_checkpoint(
        self,
        *,
        user_id: str,
        project_id: str,
        checkpoint: str,
    ) -> dict[str, Any]:
        if checkpoint not in VALID_CHECKPOINTS:
            return {"ok": False, "error": "invalid_checkpoint"}
        async with session_scope(self._sessionmaker) as session:
            repo = OnboardingStateRepository(session)
            row = await repo.get(
                user_id=user_id, project_id=project_id
            )
            if row is None:
                # First-time visitors who hit checkpoint without a
                # prior GET — create the row so the advance succeeds.
                row = await repo.create(
                    user_id=user_id, project_id=project_id
                )
            row = await repo.set_checkpoint(
                user_id=user_id,
                project_id=project_id,
                checkpoint=checkpoint,
            )
            return {"ok": True, "state": self._serialize_state(row)}

    async def dismiss(
        self, *, user_id: str, project_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = OnboardingStateRepository(session)
            row = await repo.get(
                user_id=user_id, project_id=project_id
            )
            if row is None:
                row = await repo.create(
                    user_id=user_id, project_id=project_id
                )
            row = await repo.dismiss(
                user_id=user_id, project_id=project_id
            )
            return {"ok": True, "state": self._serialize_state(row)}

    async def replay(
        self, *, user_id: str, project_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = OnboardingStateRepository(session)
            row = await repo.get(
                user_id=user_id, project_id=project_id
            )
            if row is None:
                row = await repo.create(
                    user_id=user_id, project_id=project_id
                )
            row = await repo.replay(
                user_id=user_id, project_id=project_id
            )
            return {"ok": True, "state": self._serialize_state(row)}

    # ---- internals -------------------------------------------------------

    def _is_fresh(self, generated_at: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return (now - generated_at).total_seconds() < _CACHE_TTL_SECONDS

    async def _assemble_sections(
        self,
        *,
        user_id: str,
        project_id: str,
        slice_: dict[str, Any],
    ) -> list[_Section]:
        project_title = (
            (slice_.get("project") or {}).get("title") or "this project"
        )
        members = slice_.get("members") or []
        assignments = slice_.get("assignments") or []
        plan = slice_.get("plan") or {}
        tasks = plan.get("tasks") or []
        graph = slice_.get("graph") or {}
        risks = graph.get("risks") or []
        decisions = slice_.get("decisions") or []

        viewer_role = self._viewer_role(members, user_id)
        viewer_display = await self._viewer_display_name(user_id)

        sections: list[_Section] = []
        sections.append(
            await self._section_vision(
                project_id=project_id,
                project_title=project_title,
                viewer_display=viewer_display,
                viewer_role=viewer_role,
            )
        )
        sections.append(
            self._section_recent_decisions(decisions=decisions)
        )
        sections.append(
            self._section_adjacent_teammates(
                user_id=user_id,
                members=members,
                assignments=assignments,
                tasks=tasks,
            )
        )
        sections.append(
            self._section_your_tasks(
                user_id=user_id,
                assignments=assignments,
                tasks=tasks,
            )
        )
        sections.append(
            self._section_open_risks(risks=risks)
        )
        return sections

    def _viewer_role(
        self, members: list[dict[str, Any]], user_id: str
    ) -> str | None:
        for m in members:
            if m.get("user_id") == user_id:
                return m.get("role")
        return None

    async def _viewer_display_name(self, user_id: str) -> str:
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                return ""
            return user.display_name or user.username

    # ---- sections --------------------------------------------------------

    async def _section_vision(
        self,
        *,
        project_id: str,
        project_title: str,
        viewer_display: str,
        viewer_role: str | None,
    ) -> _Section:
        """Vision section reads CommitmentRow headlines (thesis-commits).

        We scope to the earliest / top-N commitments that represent
        the project's thesis. Drift + SLA are handled elsewhere; the
        walkthrough only narrates the promises so the newcomer knows
        what shape of outcome the project is aiming at.
        """
        async with session_scope(self._sessionmaker) as session:
            commitments = await CommitmentRepository(
                session
            ).list_for_project(project_id, limit=20)
        # Keep the 3 oldest open / resolved — those tend to be the
        # thesis-level commitments, not tactical ones.
        thesis = [c for c in commitments if c.status != "withdrawn"][:3]

        claims: list[CitedClaim] = []
        lines: list[str] = []
        if viewer_role:
            lines.append(
                f"Welcome, {viewer_display or 'teammate'} — "
                f"you're joining {project_title} as the {viewer_role}."
            )
        else:
            lines.append(
                f"Welcome, {viewer_display or 'teammate'} — "
                f"here's what {project_title} is aiming for."
            )
        if not thesis:
            lines.append(
                "No thesis commitments are on record yet. "
                "Ask the owner what outcome the project is promising."
            )
        else:
            lines.append(
                "These are the top thesis commitments on record:"
            )
            for c in thesis:
                headline = (c.headline or "").strip() or "(unnamed commitment)"
                status = c.status or "open"
                lines.append(f"- {headline} ({status})")
                claims.append(
                    CitedClaim(
                        text=headline,
                        citations=[
                            Citation(node_id=c.id, kind="commitment")
                        ],
                    )
                )

        return _Section(
            kind="vision",
            title="Project thesis",
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_recent_decisions(
        self, *, decisions: list[dict[str, Any]]
    ) -> _Section:
        """License-scoped recent decisions. Observer tier already
        drops decisions they didn't resolve; we take the top 5
        whatever the slice produced.
        """
        recent = decisions[:5]
        if not recent:
            body = (
                "No crystallized decisions are visible in your slice "
                "yet. If the project feels undirected, that's normal "
                "for a new surface — flag anything you'd expect to "
                "see recorded."
            )
            return _Section(
                kind="decisions",
                title="Recent decisions",
                body_md=body,
                claims=[],
            )

        claims: list[CitedClaim] = []
        lines: list[str] = [
            "The last few crystallized decisions on your side of the graph:",
        ]
        for d in recent:
            summary = (
                d.get("rationale") or d.get("custom_text") or ""
            ).strip() or "(no rationale recorded)"
            summary = summary[:200]
            lines.append(f"- {summary}")
            did = d.get("id")
            if did:
                claims.append(
                    CitedClaim(
                        text=summary,
                        citations=[
                            Citation(node_id=str(did), kind="decision")
                        ],
                    )
                )
        return _Section(
            kind="decisions",
            title="Recent decisions",
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_adjacent_teammates(
        self,
        *,
        user_id: str,
        members: list[dict[str, Any]],
        assignments: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> _Section:
        """Who's adjacent? For each member, count the edges that
        connect them to the viewer:
          * shared task assignments (both assigned to the same task)
          * shared deliverable (their task sits under a deliverable
            the viewer also has a task under)
          * same role (members list carries `role`)
        One-sentence renders per teammate. Skips the viewer's own row.
        """
        viewer_tasks = {
            a["task_id"]
            for a in assignments
            if a.get("user_id") == user_id
            and bool(a.get("active", True))
        }
        task_by_id: dict[str, dict[str, Any]] = {
            t["id"]: t for t in tasks if t.get("id")
        }
        viewer_deliverables = {
            task_by_id[tid].get("deliverable_id")
            for tid in viewer_tasks
            if tid in task_by_id and task_by_id[tid].get("deliverable_id")
        }

        viewer_role = self._viewer_role(members, user_id)

        # user_id → edge counts
        adjacency: dict[str, dict[str, Any]] = {}
        for a in assignments:
            if not bool(a.get("active", True)):
                continue
            other = a.get("user_id")
            if other == user_id or not other:
                continue
            tid = a.get("task_id")
            if not tid:
                continue
            record = adjacency.setdefault(
                other,
                {
                    "shared_tasks": 0,
                    "shared_deliverables": 0,
                    "same_role": False,
                },
            )
            if tid in viewer_tasks:
                record["shared_tasks"] += 1
            deliv_id = task_by_id.get(tid, {}).get("deliverable_id")
            if deliv_id and deliv_id in viewer_deliverables:
                record["shared_deliverables"] += 1

        for m in members:
            uid = m.get("user_id")
            if not uid or uid == user_id:
                continue
            if (
                viewer_role is not None
                and m.get("role") == viewer_role
            ):
                adjacency.setdefault(
                    uid,
                    {
                        "shared_tasks": 0,
                        "shared_deliverables": 0,
                        "same_role": False,
                    },
                )["same_role"] = True

        # Sort by total edge weight descending; cap at 5 teammates.
        def _rank(entry: tuple[str, dict[str, Any]]) -> int:
            _, rec = entry
            return (
                rec["shared_tasks"] * 3
                + rec["shared_deliverables"] * 2
                + (1 if rec["same_role"] else 0)
            )

        ranked = sorted(
            adjacency.items(), key=_rank, reverse=True
        )[:5]

        members_by_id = {m.get("user_id"): m for m in members}
        claims: list[CitedClaim] = []
        lines: list[str] = []
        if not ranked:
            lines.append(
                "No adjacent teammates detected yet — you haven't "
                "shared a task, deliverable, or role with anyone. "
                "Once you're assigned work, this section fills in."
            )
        else:
            lines.append("The teammates you're most graph-adjacent to:")
            for uid, rec in ranked:
                m = members_by_id.get(uid) or {}
                name = (
                    m.get("display_name")
                    or m.get("username")
                    or f"teammate {uid[:8]}"
                )
                role = m.get("role") or "member"
                reasons: list[str] = []
                if rec["shared_tasks"]:
                    reasons.append(
                        f"{rec['shared_tasks']} shared task(s)"
                    )
                if rec["shared_deliverables"]:
                    reasons.append(
                        f"{rec['shared_deliverables']} shared deliverable(s)"
                    )
                if rec["same_role"]:
                    reasons.append("same role")
                why = ", ".join(reasons) if reasons else "project member"
                sentence = (
                    f"{name} ({role}) — {why}. "
                    f"Expect them to emit decisions and task updates "
                    f"around the shared work."
                )
                lines.append(f"- {sentence}")
                # No canonical kind for 'user' in CitedClaim — use
                # the members list as plain text; citations stay empty
                # for this section. (Members are not graph nodes in
                # the CitationKind taxonomy.)
                claims.append(CitedClaim(text=sentence, citations=[]))

        return _Section(
            kind="teammates",
            title="Adjacent teammates",
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_your_tasks(
        self,
        *,
        user_id: str,
        assignments: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> _Section:
        viewer_task_ids = {
            a["task_id"]
            for a in assignments
            if a.get("user_id") == user_id
            and bool(a.get("active", True))
        }
        mine = [t for t in tasks if t.get("id") in viewer_task_ids]

        claims: list[CitedClaim] = []
        if not mine:
            body = (
                "You have no active task assignments yet. The owner "
                "will route work to you as the plan fills in — keep "
                "an eye on your personal stream."
            )
            return _Section(
                kind="your_tasks",
                title="Your active tasks",
                body_md=body,
                claims=claims,
            )

        # Status histogram helps the user see at-a-glance shape.
        counts = Counter((t.get("status") or "unknown") for t in mine)
        breakdown = ", ".join(f"{n} {s}" for s, n in counts.most_common())
        lines = [f"You have {len(mine)} active task(s) — {breakdown}."]
        for t in mine:
            title = (t.get("title") or "").strip() or "(untitled task)"
            status = t.get("status") or "unknown"
            lines.append(f"- {title} [{status}]")
            tid = t.get("id")
            if tid:
                claims.append(
                    CitedClaim(
                        text=title,
                        citations=[
                            Citation(node_id=str(tid), kind="task")
                        ],
                    )
                )
        return _Section(
            kind="your_tasks",
            title="Your active tasks",
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_open_risks(
        self, *, risks: list[dict[str, Any]]
    ) -> _Section:
        open_risks = [
            r
            for r in risks
            if (r.get("status") or "open") not in ("resolved", "closed")
        ]
        claims: list[CitedClaim] = []
        if not open_risks:
            body = (
                "No open risks visible in your slice. If something "
                "worries you that isn't on this list, file it — "
                "silence is not absence."
            )
            return _Section(
                kind="open_risks",
                title="Open risks",
                body_md=body,
                claims=claims,
            )
        lines = [
            f"{len(open_risks)} open risk(s) on your side of the graph:",
        ]
        for r in open_risks[:8]:
            title = (r.get("title") or "").strip() or "(untitled risk)"
            sev = r.get("severity") or "medium"
            lines.append(f"- {title} ({sev})")
            rid = r.get("id")
            if rid:
                claims.append(
                    CitedClaim(
                        text=title,
                        citations=[
                            Citation(node_id=str(rid), kind="risk")
                        ],
                    )
                )
        return _Section(
            kind="open_risks",
            title="Open risks",
            body_md="\n".join(lines),
            claims=claims,
        )

    # ---- serialize -------------------------------------------------------

    @staticmethod
    def _serialize_state(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        return {
            "id": row.id,
            "user_id": row.user_id,
            "project_id": row.project_id,
            "first_seen_at": (
                row.first_seen_at.isoformat()
                if row.first_seen_at
                else None
            ),
            "walkthrough_started_at": (
                row.walkthrough_started_at.isoformat()
                if row.walkthrough_started_at
                else None
            ),
            "walkthrough_completed_at": (
                row.walkthrough_completed_at.isoformat()
                if row.walkthrough_completed_at
                else None
            ),
            "last_checkpoint": row.last_checkpoint,
            "dismissed": bool(row.dismissed),
        }


__all__ = ["OnboardingService", "VALID_CHECKPOINTS"]
