"""Seed rich tasks / risks / milestones / decisions / assignments for
both the EN and ZH Moonshot projects.

The intake pipeline is flaky — PlanAgent sometimes fails to produce
tasks on LLM hiccups. This script bypasses the pipeline entirely and
injects a realistic plan directly into the DB so the detail views
and the graph actually have content.

Idempotent: existing rows of the same kind are wiped for each project
before insert, so re-runs always converge on the same seed.

Usage:
    uv run python scripts/demo/seed_rich_details.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "persistence" / "src"))
sys.path.insert(0, str(REPO / "apps" / "api" / "src"))

from workgraph_persistence.db import (  # noqa: E402
    build_engine,
    build_sessionmaker,
    session_scope,
)
from workgraph_persistence.orm import (  # noqa: E402
    AssignmentRow,
    DecisionRow,
    DeliverableRow,
    MilestoneRow,
    ProjectRow,
    RequirementRow,
    RiskRow,
    TaskDependencyRow,
    TaskRow,
    UserRow,
)

DB_URL = f"sqlite+aiosqlite:///{REPO / 'data' / 'workgraph.sqlite'}"

# ---- seed content per language --------------------------------------------

EN = {
    "project_match": "stellar drift",
    "milestones": [
        ("Alpha lock", 7),
        ("External QA Wave 2", 18),
        ("Certification submission", 24),
        ("Ship", 28),
    ],
    "risks": [
        ("Switch performance drops below 30fps on boss-3", "high"),
        ("Boss-1 rage-quit rate above 30% blocks ship", "high"),
        ("Matchmaking NAT fallback unverified", "medium"),
        ("Boss-3 palette delay cascades art pipeline", "low"),
    ],
    "tasks": [
        # (title, assignee_role, estimate, status, milestone_idx, username)
        ("Lock final matchmaking NAT fallback", "backend", 16, "in_progress", 0, "james"),
        ("Boss-1 difficulty rework with memento-revive", "design", 20, "in_progress", 1, "raj"),
        ("Memory profile on Switch — boss-3 encounter", "backend", 12, "todo", 1, "aiko"),
        ("Wave-2 external playtest coordination", "qa", 8, "todo", 1, "sofia"),
        ("Boss-3 palette swap from boss-2 rig", "design", 4, "done", 0, "diego"),
        ("Controller mapping audit (Xbox / PS / Switch)", "qa", 6, "in_progress", 2, "sofia"),
        ("Daily-run seed determinism test suite", "backend", 10, "todo", 2, "james"),
        ("Steam page copy + screenshots final pass", "design", 6, "blocked", 3, "diego"),
        ("Leaderboard persistence + cheat validation", "backend", 14, "todo", 2, "aiko"),
        ("Cert submission build + QA signoff", "qa", 8, "todo", 2, "sofia"),
    ],
    # (from_idx, to_idx) pairs — references tasks by index in the list above
    "deps": [(0, 6), (1, 3), (4, 5), (2, 8), (6, 9)],
    "decisions": [
        (
            "Keep permadeath but add memento-revive midgame unlock",
            "Threads the needle between Sofia's rage-quit data (40% on boss-1) and "
            "Raj's design thesis. Aiko signed off on 2-week engineering cost. "
            "Crystallized from routed signal Raj→Aiko→accept.",
        ),
        (
            "Freeze feature set at alpha lock (T-14 days)",
            "Maya committed the scope freeze to protect ship date. New feature "
            "requests require owner + risk delta + Maya+Aiko sign-off.",
        ),
        (
            "Cut mid-run merchant vendor unless Switch perf headroom appears",
            "Alpha build is at 28fps on boss-3 — no headroom for a new mid-run "
            "system. Moved to season-2 backlog.",
        ),
    ],
}

ZH = {
    "project_match": "星际漂流",
    "milestones": [
        ("Alpha 封版", 7),
        ("外部 QA 第二轮", 18),
        ("平台认证提交", 24),
        ("正式发布", 28),
    ],
    "risks": [
        ("Switch 性能在 Boss-3 场景低于 30fps", "high"),
        ("Boss-1 怒退率高于 30% 会阻塞发布", "high"),
        ("匹配系统 NAT 回落路径未验证", "medium"),
        ("Boss-3 调色延迟影响美术管线", "low"),
    ],
    "tasks": [
        ("锁定匹配系统 NAT 回落方案", "backend", 16, "in_progress", 0, "james_zh"),
        ("Boss-1 难度重做 + 纪念品复活机制", "design", 20, "in_progress", 1, "raj_zh"),
        ("Switch 内存剖析 — Boss-3 场景", "backend", 12, "todo", 1, "aiko_zh"),
        ("第二轮外部试玩组织协调", "qa", 8, "todo", 1, "sofia_zh"),
        ("Boss-3 调色复用 Boss-2 光照", "design", 4, "done", 0, "diego_zh"),
        ("手柄映射审查(Xbox / PS / Switch)", "qa", 6, "in_progress", 2, "sofia_zh"),
        ("每日种子确定性测试套件", "backend", 10, "todo", 2, "james_zh"),
        ("Steam 页面文案与截图终版", "design", 6, "blocked", 3, "diego_zh"),
        ("排行榜持久化 + 反作弊校验", "backend", 14, "todo", 2, "aiko_zh"),
        ("平台认证提交构建 + QA 签字", "qa", 8, "todo", 2, "sofia_zh"),
    ],
    "deps": [(0, 6), (1, 3), (4, 5), (2, 8), (6, 9)],
    "decisions": [
        (
            "保留永久死亡 + 引入中盘纪念品复活机制",
            "在索菲亚的 40% 怒退数据和拉杰的设计论点之间找到平衡。"
            "爱子确认 2 周工程成本可接受。从路由信号 Raj→Aiko→accept 生成。",
        ),
        (
            "Alpha 封版后冻结功能范围(T-14 天)",
            "梅雅为保护发布日期承诺范围冻结。封版后新增功能需:负责人 + "
            "风险增量 + 梅雅和爱子签字。",
        ),
        (
            "除非 Switch 性能有余量否则砍掉中盘商人",
            "Alpha 版本在 Boss-3 场景仅 28fps,没有余量容纳新系统。"
            "挪到第二季 backlog。",
        ),
    ],
}


async def _get_project(session: AsyncSession, match: str) -> ProjectRow | None:
    rows = (await session.execute(select(ProjectRow))).scalars().all()
    for r in rows:
        if match.lower() in (r.title or "").lower():
            return r
    return None


async def _get_requirement(session: AsyncSession, project_id: str) -> RequirementRow | None:
    row = (
        await session.execute(
            select(RequirementRow)
            .where(RequirementRow.project_id == project_id)
            .order_by(RequirementRow.version.desc())
        )
    ).scalars().first()
    return row


async def _get_deliverables(
    session: AsyncSession, requirement_id: str
) -> list[DeliverableRow]:
    return list(
        (
            await session.execute(
                select(DeliverableRow).where(
                    DeliverableRow.requirement_id == requirement_id
                )
            )
        )
        .scalars()
        .all()
    )


async def _get_users(session: AsyncSession) -> dict[str, UserRow]:
    rows = (await session.execute(select(UserRow))).scalars().all()
    return {r.username: r for r in rows}


async def _wipe_existing(
    session: AsyncSession, project_id: str, requirement_id: str
) -> None:
    """Clear previous rich-detail seed so re-runs are idempotent."""
    # Tasks under this requirement (dependencies CASCADE via FK)
    tasks = list(
        (
            await session.execute(
                select(TaskRow).where(TaskRow.requirement_id == requirement_id)
            )
        ).scalars().all()
    )
    task_ids = {t.id for t in tasks}

    if task_ids:
        await session.execute(
            delete(AssignmentRow).where(AssignmentRow.task_id.in_(task_ids))
        )
        await session.execute(
            delete(TaskDependencyRow).where(
                TaskDependencyRow.requirement_id == requirement_id
            )
        )
        await session.execute(
            delete(TaskRow).where(TaskRow.requirement_id == requirement_id)
        )

    await session.execute(
        delete(MilestoneRow).where(MilestoneRow.requirement_id == requirement_id)
    )
    await session.execute(
        delete(RiskRow).where(RiskRow.requirement_id == requirement_id)
    )
    await session.execute(
        delete(DecisionRow).where(DecisionRow.project_id == project_id)
    )


async def _seed_project(
    session: AsyncSession, *, project: ProjectRow, content: dict
) -> dict:
    req = await _get_requirement(session, project.id)
    if req is None:
        return {"skipped": True, "reason": "no_requirement"}

    deliverables = await _get_deliverables(session, req.id)
    users = await _get_users(session)

    await _wipe_existing(session, project.id, req.id)

    now = datetime.now(timezone.utc)
    # ---- milestones
    milestone_ids: list[str] = []
    for i, (title, days_out) in enumerate(content["milestones"]):
        mid = str(uuid.uuid4())
        session.add(
            MilestoneRow(
                id=mid,
                project_id=project.id,
                requirement_id=req.id,
                sort_order=i,
                status="open",
                title=title,
                target_date=now + timedelta(days=days_out),
            )
        )
        milestone_ids.append(mid)

    # ---- risks
    for i, (title, severity) in enumerate(content["risks"]):
        session.add(
            RiskRow(
                id=str(uuid.uuid4()),
                project_id=project.id,
                requirement_id=req.id,
                sort_order=i,
                status="open",
                title=title,
                severity=severity,
            )
        )

    # ---- tasks
    task_ids: list[str] = []
    for i, (title, role, hours, status, ms_idx, username) in enumerate(content["tasks"]):
        tid = str(uuid.uuid4())
        deliverable_id = (
            deliverables[i % len(deliverables)].id if deliverables else None
        )
        session.add(
            TaskRow(
                id=tid,
                project_id=project.id,
                requirement_id=req.id,
                sort_order=i,
                status=status,
                title=title,
                description="",
                deliverable_id=deliverable_id,
                assignee_role=role,
                estimate_hours=hours,
                acceptance_criteria=None,
            )
        )
        task_ids.append(tid)
        # assignment
        user = users.get(username)
        if user is not None:
            session.add(
                AssignmentRow(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    task_id=tid,
                    user_id=user.id,
                    active=True,
                )
            )

    # ---- dependencies
    for from_i, to_i in content["deps"]:
        if from_i < len(task_ids) and to_i < len(task_ids):
            session.add(
                TaskDependencyRow(
                    id=str(uuid.uuid4()),
                    requirement_id=req.id,
                    from_task_id=task_ids[from_i],
                    to_task_id=task_ids[to_i],
                )
            )

    # ---- milestone→task backrefs (set related_task_ids)
    # tasks at indices 0..2 → ms 0, 3..5 → ms 1, 6..8 → ms 2, 9 → ms 3
    ms_to_tasks: dict[str, list[str]] = {mid: [] for mid in milestone_ids}
    for i, task_id in enumerate(task_ids):
        ms_idx = content["tasks"][i][4]
        if 0 <= ms_idx < len(milestone_ids):
            ms_to_tasks[milestone_ids[ms_idx]].append(task_id)
    # Set via a second pass — fetch and update
    for ms_id, rel_ids in ms_to_tasks.items():
        ms = (
            await session.execute(select(MilestoneRow).where(MilestoneRow.id == ms_id))
        ).scalar_one()
        ms.related_task_ids = rel_ids

    # ---- decisions (resolver_id = project owner — required NOT NULL)
    resolver = next(iter(users.values())).id  # first user; good enough for seed
    # Prefer Maya/owner when present for realism
    for preferred in ("maya", "maya_zh"):
        if preferred in users:
            resolver = users[preferred].id
            break
    for i, (summary, rationale) in enumerate(content["decisions"]):
        session.add(
            DecisionRow(
                id=str(uuid.uuid4()),
                project_id=project.id,
                conflict_id=None,
                resolver_id=resolver,
                option_index=None,
                custom_text=summary,
                rationale=rationale,
                apply_actions=[],
                apply_outcome="ok",
                apply_detail={},
                source_suggestion_id=None,
            )
        )

    await session.flush()
    return {
        "project": project.title,
        "tasks": len(task_ids),
        "milestones": len(milestone_ids),
        "risks": len(content["risks"]),
        "decisions": len(content["decisions"]),
        "dependencies": len(content["deps"]),
    }


async def main() -> int:
    engine = build_engine(DB_URL)
    sessionmaker = build_sessionmaker(engine)

    results = []
    async with session_scope(sessionmaker) as session:
        for content in (EN, ZH):
            project = await _get_project(session, content["project_match"])
            if project is None:
                results.append(
                    {"skipped": True, "match": content["project_match"]}
                )
                continue
            summary = await _seed_project(
                session, project=project, content=content
            )
            results.append(summary)

    await engine.dispose()
    import json

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
