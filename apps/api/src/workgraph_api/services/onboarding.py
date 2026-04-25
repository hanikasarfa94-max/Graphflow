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


# Templated copy in two languages. We read viewer.display_language to
# pick. Unknown languages fall back to "en". Keep keys flat — no nested
# namespaces — so .format(**kwargs) stays predictable.
_TR: dict[str, dict[str, str]] = {
    "en": {
        "title.vision": "Project thesis",
        "title.decisions": "Recent decisions",
        "title.teammates": "Adjacent teammates",
        "title.your_tasks": "Your active tasks",
        "title.open_risks": "Open risks",
        "viewer_default_name": "teammate",
        "vision.welcome_role": "Welcome, {name} — you're joining {project} as the {role}.",
        "vision.welcome_no_role": "Welcome, {name} — here's what {project} is aiming for.",
        "vision.no_commitments": (
            "No thesis commitments are on record yet. "
            "Ask the owner what outcome the project is promising."
        ),
        "vision.intro": "These are the top thesis commitments on record:",
        "vision.bullet": "- {headline} ({status})",
        "vision.unnamed": "(unnamed commitment)",
        "decisions.empty": (
            "No crystallized decisions are visible in your slice yet. "
            "If the project feels undirected, that's normal for a new "
            "surface — flag anything you'd expect to see recorded."
        ),
        "decisions.intro": "The last few crystallized decisions on your side of the graph:",
        "decisions.no_rationale": "(no rationale recorded)",
        "teammates.empty": (
            "No adjacent teammates detected yet — you haven't shared a "
            "task, deliverable, or role with anyone. Once you're assigned "
            "work, this section fills in."
        ),
        "teammates.intro": "The teammates you're most graph-adjacent to:",
        "teammates.uid_fallback": "teammate {short_id}",
        "teammates.role_fallback": "member",
        "teammates.reason_shared_tasks": "{n} shared task(s)",
        "teammates.reason_shared_deliverables": "{n} shared deliverable(s)",
        "teammates.reason_same_role": "same role",
        "teammates.reason_default": "project member",
        "teammates.bullet": (
            "- {name} ({role}) — {why}. Expect them to emit decisions and "
            "task updates around the shared work."
        ),
        "tasks.empty": (
            "You have no active task assignments yet. The owner will route "
            "work to you as the plan fills in — keep an eye on your "
            "personal stream."
        ),
        "tasks.summary": "You have {n} active task(s) — {breakdown}.",
        "tasks.bullet": "- {title} [{status}]",
        "tasks.untitled": "(untitled task)",
        "risks.empty": (
            "No open risks visible in your slice. If something worries "
            "you that isn't on this list, file it — silence is not absence."
        ),
        "risks.summary": "{n} open risk(s) on your side of the graph:",
        "risks.bullet": "- {title} ({sev})",
        "risks.untitled": "(untitled risk)",
    },
    "zh": {
        "title.vision": "项目主张",
        "title.decisions": "近期决策",
        "title.teammates": "关系最近的同事",
        "title.your_tasks": "你的进行中任务",
        "title.open_risks": "未结风险",
        "viewer_default_name": "同事",
        "vision.welcome_role": "欢迎，{name} —— 你以「{role}」身份加入 {project}。",
        "vision.welcome_no_role": "欢迎，{name} —— 这是 {project} 想要达成的方向。",
        "vision.no_commitments": (
            "项目暂未登记任何主张性承诺。"
            "建议向负责人询问该项目正在承诺交付的成果。"
        ),
        "vision.intro": "记录在案的关键主张性承诺：",
        "vision.bullet": "- {headline}（{status}）",
        "vision.unnamed": "（未命名承诺）",
        "decisions.empty": (
            "你的视图内暂无已落定的决策。"
            "如果项目方向不明确，对新视图来说属于正常 —— "
            "记得标记你预期应当被记录但未出现的内容。"
        ),
        "decisions.intro": "你这一侧图上最近落定的几条决策：",
        "decisions.no_rationale": "（未记录理由）",
        "teammates.empty": (
            "暂未识别到关系紧密的同事 —— "
            "你还没有与任何人共享任务、交付物或角色。"
            "一旦有任务分配给你，这里就会自动填充。"
        ),
        "teammates.intro": "图上与你关系最紧密的同事：",
        "teammates.uid_fallback": "同事 {short_id}",
        "teammates.role_fallback": "成员",
        "teammates.reason_shared_tasks": "共担任务 {n} 个",
        "teammates.reason_shared_deliverables": "共担交付物 {n} 个",
        "teammates.reason_same_role": "相同角色",
        "teammates.reason_default": "项目成员",
        "teammates.bullet": (
            "- {name}（{role}）—— {why}。"
            "可预期他们围绕共担工作产出决策与任务更新。"
        ),
        "tasks.empty": (
            "你目前没有进行中的任务分配。"
            "负责人会随计划展开把工作分派给你 —— "
            "留意你的个人流即可。"
        ),
        "tasks.summary": "你共有 {n} 个进行中任务 —— {breakdown}。",
        "tasks.bullet": "- {title} [{status}]",
        "tasks.untitled": "（未命名任务）",
        "risks.empty": (
            "你的视图内暂无未结风险。"
            "如果你担心的事项未列在这里，请记录下来 —— 沉默不等于不存在。"
        ),
        "risks.summary": "你这一侧图上有 {n} 个未结风险：",
        "risks.bullet": "- {title}（{sev}）",
        "risks.untitled": "（未命名风险）",
    },
}


def _tr(lang: str, key: str, **kwargs: Any) -> str:
    table = _TR.get(lang) or _TR["en"]
    template = table.get(key) or _TR["en"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


# Low-cardinality enum labels we render inside templated bullets. Falls
# through to the raw DB value for unknown values so backend additions
# don't crash the tour — just show un-translated.
_ENUMS: dict[str, dict[str, dict[str, str]]] = {
    "role": {
        "en": {
            "owner": "owner",
            "admin": "admin",
            "member": "member",
            "viewer": "viewer",
        },
        "zh": {
            "owner": "负责人",
            "admin": "管理员",
            "member": "成员",
            "viewer": "观察员",
        },
    },
    "task_status": {
        "en": {
            "open": "open",
            "in_progress": "in progress",
            "blocked": "blocked",
            "done": "done",
            "canceled": "canceled",
            "cancelled": "canceled",
            "unknown": "unknown",
        },
        "zh": {
            "open": "未开始",
            "in_progress": "进行中",
            "blocked": "受阻",
            "done": "已完成",
            "canceled": "已取消",
            "cancelled": "已取消",
            "unknown": "未知",
        },
    },
    "commitment_status": {
        "en": {
            "open": "open",
            "kept": "kept",
            "broken": "broken",
            "withdrawn": "withdrawn",
            "resolved": "resolved",
        },
        "zh": {
            "open": "进行中",
            "kept": "已兑现",
            "broken": "已违约",
            "withdrawn": "已撤回",
            "resolved": "已结",
        },
    },
    "risk_severity": {
        "en": {
            "low": "low",
            "medium": "medium",
            "high": "high",
            "critical": "critical",
        },
        "zh": {
            "low": "低",
            "medium": "中",
            "high": "高",
            "critical": "严重",
        },
    },
}


def _enum(lang: str, kind: str, value: str) -> str:
    table = _ENUMS.get(kind, {}).get(lang) or _ENUMS.get(kind, {}).get("en", {})
    return table.get(value, value)


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

        lang = await self._viewer_language(user_id)

        sections = await self._assemble_sections(
            user_id=user_id,
            project_id=project_id,
            slice_=slice_,
            lang=lang,
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
        lang: str = "en",
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
                lang=lang,
            )
        )
        sections.append(
            self._section_recent_decisions(decisions=decisions, lang=lang)
        )
        sections.append(
            self._section_adjacent_teammates(
                user_id=user_id,
                members=members,
                assignments=assignments,
                tasks=tasks,
                lang=lang,
            )
        )
        sections.append(
            self._section_your_tasks(
                user_id=user_id,
                assignments=assignments,
                tasks=tasks,
                lang=lang,
            )
        )
        sections.append(
            self._section_open_risks(risks=risks, lang=lang)
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

    async def _viewer_language(self, user_id: str) -> str:
        """Returns 'en' or 'zh'. Anything else falls through to 'en'.
        Read from UserRow.display_language; default 'en' when missing."""
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
        lang = (user.display_language if user else None) or "en"
        return lang if lang in _TR else "en"

    # ---- sections --------------------------------------------------------

    async def _section_vision(
        self,
        *,
        project_id: str,
        project_title: str,
        viewer_display: str,
        viewer_role: str | None,
        lang: str = "en",
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
        thesis = [c for c in commitments if c.status != "withdrawn"][:3]

        claims: list[CitedClaim] = []
        lines: list[str] = []
        viewer_name = viewer_display or _tr(lang, "viewer_default_name")
        if viewer_role:
            lines.append(
                _tr(
                    lang,
                    "vision.welcome_role",
                    name=viewer_name,
                    project=project_title,
                    role=_enum(lang, "role", viewer_role),
                )
            )
        else:
            lines.append(
                _tr(
                    lang,
                    "vision.welcome_no_role",
                    name=viewer_name,
                    project=project_title,
                )
            )
        if not thesis:
            lines.append(_tr(lang, "vision.no_commitments"))
        else:
            lines.append(_tr(lang, "vision.intro"))
            for c in thesis:
                headline = (c.headline or "").strip() or _tr(lang, "vision.unnamed")
                status = c.status or "open"
                lines.append(
                    _tr(
                        lang,
                        "vision.bullet",
                        headline=headline,
                        status=_enum(lang, "commitment_status", status),
                    )
                )
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
            title=_tr(lang, "title.vision"),
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_recent_decisions(
        self, *, decisions: list[dict[str, Any]], lang: str = "en"
    ) -> _Section:
        """License-scoped recent decisions. Observer tier already
        drops decisions they didn't resolve; we take the top 5
        whatever the slice produced.
        """
        recent = decisions[:5]
        title = _tr(lang, "title.decisions")
        if not recent:
            return _Section(
                kind="decisions",
                title=title,
                body_md=_tr(lang, "decisions.empty"),
                claims=[],
            )

        claims: list[CitedClaim] = []
        lines: list[str] = [_tr(lang, "decisions.intro")]
        for d in recent:
            summary = (
                d.get("rationale") or d.get("custom_text") or ""
            ).strip() or _tr(lang, "decisions.no_rationale")
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
            title=title,
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
        lang: str = "en",
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
            lines.append(_tr(lang, "teammates.empty"))
        else:
            lines.append(_tr(lang, "teammates.intro"))
            for uid, rec in ranked:
                m = members_by_id.get(uid) or {}
                name = (
                    m.get("display_name")
                    or m.get("username")
                    or _tr(lang, "teammates.uid_fallback", short_id=uid[:8])
                )
                raw_role = m.get("role") or "member"
                role = _enum(lang, "role", raw_role)
                reasons: list[str] = []
                if rec["shared_tasks"]:
                    reasons.append(
                        _tr(
                            lang,
                            "teammates.reason_shared_tasks",
                            n=rec["shared_tasks"],
                        )
                    )
                if rec["shared_deliverables"]:
                    reasons.append(
                        _tr(
                            lang,
                            "teammates.reason_shared_deliverables",
                            n=rec["shared_deliverables"],
                        )
                    )
                if rec["same_role"]:
                    reasons.append(_tr(lang, "teammates.reason_same_role"))
                separator = "、" if lang == "zh" else ", "
                why = (
                    separator.join(reasons)
                    if reasons
                    else _tr(lang, "teammates.reason_default")
                )
                lines.append(
                    _tr(
                        lang,
                        "teammates.bullet",
                        name=name,
                        role=role,
                        why=why,
                    )
                )
                # CitationKind has no `user` member, so we cannot link
                # teammate names to graph nodes. Don't emit empty-
                # citation claims — the OnboardingOverlay would render
                # them as a second copy of the body lines.

        return _Section(
            kind="teammates",
            title=_tr(lang, "title.teammates"),
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_your_tasks(
        self,
        *,
        user_id: str,
        assignments: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        lang: str = "en",
    ) -> _Section:
        viewer_task_ids = {
            a["task_id"]
            for a in assignments
            if a.get("user_id") == user_id
            and bool(a.get("active", True))
        }
        mine = [t for t in tasks if t.get("id") in viewer_task_ids]
        title = _tr(lang, "title.your_tasks")

        claims: list[CitedClaim] = []
        if not mine:
            return _Section(
                kind="your_tasks",
                title=title,
                body_md=_tr(lang, "tasks.empty"),
                claims=claims,
            )

        counts = Counter((t.get("status") or "unknown") for t in mine)
        separator = "、" if lang == "zh" else ", "
        breakdown = separator.join(
            f"{n} {_enum(lang, 'task_status', s)}"
            for s, n in counts.most_common()
        )
        lines = [
            _tr(lang, "tasks.summary", n=len(mine), breakdown=breakdown)
        ]
        for t in mine:
            title_text = (t.get("title") or "").strip() or _tr(lang, "tasks.untitled")
            status = t.get("status") or "unknown"
            lines.append(
                _tr(
                    lang,
                    "tasks.bullet",
                    title=title_text,
                    status=_enum(lang, "task_status", status),
                )
            )
            tid = t.get("id")
            if tid:
                claims.append(
                    CitedClaim(
                        text=title_text,
                        citations=[
                            Citation(node_id=str(tid), kind="task")
                        ],
                    )
                )
        return _Section(
            kind="your_tasks",
            title=title,
            body_md="\n".join(lines),
            claims=claims,
        )

    def _section_open_risks(
        self, *, risks: list[dict[str, Any]], lang: str = "en"
    ) -> _Section:
        open_risks = [
            r
            for r in risks
            if (r.get("status") or "open") not in ("resolved", "closed")
        ]
        title = _tr(lang, "title.open_risks")
        claims: list[CitedClaim] = []
        if not open_risks:
            return _Section(
                kind="open_risks",
                title=title,
                body_md=_tr(lang, "risks.empty"),
                claims=claims,
            )
        lines = [_tr(lang, "risks.summary", n=len(open_risks))]
        for r in open_risks[:8]:
            title_text = (r.get("title") or "").strip() or _tr(lang, "risks.untitled")
            sev = r.get("severity") or "medium"
            lines.append(
                _tr(
                    lang,
                    "risks.bullet",
                    title=title_text,
                    sev=_enum(lang, "risk_severity", sev),
                )
            )
            rid = r.get("id")
            if rid:
                claims.append(
                    CitedClaim(
                        text=title_text,
                        citations=[
                            Citation(node_id=str(rid), kind="risk")
                        ],
                    )
                )
        return _Section(
            kind="open_risks",
            title=title,
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
