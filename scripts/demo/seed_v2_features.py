"""Seed the Sprint 2a/2b/3a/3c features for demo visibility.

After seed_moonshot + seed_moonshot_zh + seed_rich_details run, this
script adds:

  * **Commitments** (Sprint 2a) with SLA windows (Sprint 2b) on both
    Stellar Drift projects. Three per project — one in the OK band,
    one DUE-SOON, one OVERDUE — so the graph's SLA badge variety is
    visible immediately. Two per project are anchored to a deliverable
    so the dashed-amber scope edge renders.

  * A peer **"Mobile Studio" project** (Sprint 3a) sharing two members
    with Stellar Drift. Lights up the Org view — without a peer, the
    toggle only shows the empty-state pill.

  * One **task_scoped contractor** member (Sprint 3c). Gets assigned to
    one of Stellar Drift's existing tasks. When they log in, the
    license banner fires and their /state is the filtered subgraph.

Idempotent on re-run: headlines / project titles / usernames are
matched before insert; we wipe and re-seed the commitments block but
leave the peer project and contractor in place if present.

Usage (local):
    uv run python scripts/demo/seed_v2_features.py

Usage (inside the api container):
    docker compose ... exec -T api python /app/scripts/demo/seed_v2_features.py
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

from workgraph_api.services.auth import (  # noqa: E402
    _hash_password as hash_password,
    _new_salt as new_salt,
)
from workgraph_persistence.db import (  # noqa: E402
    build_engine,
    build_sessionmaker,
    session_scope,
)
from workgraph_persistence.orm import (  # noqa: E402
    AssignmentRow,
    CommitmentRow,
    DeliverableRow,
    ProjectMemberRow,
    ProjectRow,
    RequirementRow,
    TaskRow,
    UserRow,
)

DB_URL = f"sqlite+aiosqlite:///{REPO / 'data' / 'workgraph.sqlite'}"


# Password constant matches seed_moonshot — so the contractor can log
# in with the same pattern the existing cast uses.
CONTRACTOR_PASSWORD = "moonshot2026"


# ---------------------------------------------------------------------------
# Commitments seed content. Each project gets these three rows.
# ---------------------------------------------------------------------------

COMMITMENTS_EN = [
    {
        "headline": "Ship Stellar Drift Season 1 by Apr 30",
        "metric": "All 10 Season 1 tasks shipped, no critical risks open",
        "target_days_out": -1,  # already past → OVERDUE band
        "sla_days": 3,
        "anchor_to_deliverable_index": 0,
    },
    {
        "headline": "External playtest wave 2 complete in 2 days",
        "metric": "Playtest report posted, rage-quit < 20%",
        "target_days_out": 2,  # within a 3d SLA → DUE-SOON
        "sla_days": 3,
        "anchor_to_deliverable_index": 1,
    },
    {
        "headline": "Cert submission build locked in 2 weeks",
        "metric": "All three platforms cert-ready",
        "target_days_out": 14,  # > 3d SLA → OK band, no badge
        "sla_days": 3,
        "anchor_to_deliverable_index": None,
    },
]

COMMITMENTS_ZH = [
    {
        "headline": "4 月 30 日前上线星际漂流第一季",
        "metric": "第一季 10 项任务全部交付,无严重风险未决",
        "target_days_out": -1,
        "sla_days": 3,
        "anchor_to_deliverable_index": 0,
    },
    {
        "headline": "两日内完成外部玩家测试 Wave 2",
        "metric": "测试报告已发布,退出率 < 20%",
        "target_days_out": 2,
        "sla_days": 3,
        "anchor_to_deliverable_index": 1,
    },
    {
        "headline": "两周内锁定认证送审版本",
        "metric": "三平台均具备送审条件",
        "target_days_out": 14,
        "sla_days": 3,
        "anchor_to_deliverable_index": None,
    },
]


# ---------------------------------------------------------------------------
# Peer project for Org view (Sprint 3a).
# ---------------------------------------------------------------------------

PEER_PROJECT_TITLE = "Stellar Drift — Mobile Port"
PEER_PROJECT_INTAKE_STUB = (
    "Port Stellar Drift to mobile — Q3 scope, feature parity with "
    "Season 1 core loop."
)


# ---------------------------------------------------------------------------
# Contractor user for license-scope (Sprint 3c).
# ---------------------------------------------------------------------------

CONTRACTOR_USERNAME = "bob_contract"
CONTRACTOR_DISPLAY = "Bob — Contract QA"


def log(msg: str) -> None:
    print(f"  {msg}")


async def _find_project_by_title_contains(
    session: AsyncSession, needle: str
) -> ProjectRow | None:
    rows = (await session.execute(select(ProjectRow))).scalars().all()
    for r in rows:
        if needle.lower() in (r.title or "").lower():
            return r
    return None


async def _get_requirement(
    session: AsyncSession, project_id: str
) -> RequirementRow | None:
    stmt = (
        select(RequirementRow)
        .where(RequirementRow.project_id == project_id)
        .order_by(RequirementRow.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _get_deliverables(
    session: AsyncSession, requirement_id: str
) -> list[DeliverableRow]:
    stmt = (
        select(DeliverableRow)
        .where(DeliverableRow.requirement_id == requirement_id)
        .order_by(DeliverableRow.sort_order)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _find_user_by_username(
    session: AsyncSession, username: str
) -> UserRow | None:
    stmt = select(UserRow).where(UserRow.username == username)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _find_owner_id(session: AsyncSession, project_id: str) -> str | None:
    stmt = select(ProjectMemberRow).where(
        ProjectMemberRow.project_id == project_id,
        ProjectMemberRow.role == "owner",
    )
    row = (await session.execute(stmt)).scalars().first()
    return row.user_id if row else None


async def _seed_commitments(
    session: AsyncSession, *, project: ProjectRow, content: list[dict]
) -> int:
    """Wipe existing commitments on this project, re-seed from `content`.
    Idempotent across runs."""
    owner_id = await _find_owner_id(session, project.id)
    if owner_id is None:
        log(f"[skip] {project.title}: no owner to attribute commitments to")
        return 0

    req = await _get_requirement(session, project.id)
    deliverables = (
        await _get_deliverables(session, req.id) if req is not None else []
    )

    await session.execute(
        delete(CommitmentRow).where(CommitmentRow.project_id == project.id)
    )

    now = datetime.now(timezone.utc)
    written = 0
    for spec in content:
        target = now + timedelta(days=spec["target_days_out"])
        anchor_idx = spec.get("anchor_to_deliverable_index")
        scope_kind = None
        scope_id = None
        if anchor_idx is not None and anchor_idx < len(deliverables):
            scope_kind = "deliverable"
            scope_id = deliverables[anchor_idx].id

        session.add(
            CommitmentRow(
                id=str(uuid.uuid4()),
                project_id=project.id,
                created_by_user_id=owner_id,
                owner_user_id=owner_id,
                headline=spec["headline"],
                target_date=target,
                metric=spec.get("metric"),
                scope_ref_kind=scope_kind,
                scope_ref_id=scope_id,
                status="open",
                sla_window_seconds=spec["sla_days"] * 86400,
            )
        )
        written += 1
    return written


async def _seed_peer_project(
    session: AsyncSession, stellar_drift_en: ProjectRow
) -> ProjectRow | None:
    """Create (or find) a peer project, add maya + james as members so the
    Org view has shared-member edges to Stellar Drift."""
    existing = await _find_project_by_title_contains(session, "Mobile Port")
    if existing is not None:
        log(f"[exists] peer project '{existing.title}' ({existing.id[:8]}…)")
        project = existing
    else:
        project = ProjectRow(
            id=str(uuid.uuid4()),
            title=PEER_PROJECT_TITLE,
        )
        session.add(project)
        await session.flush()
        log(f"[new] peer project '{project.title}' ({project.id[:8]}…)")

    # Seed membership: reuse maya + james from Stellar Drift EN so the
    # org-graph edge lights up with two shared members.
    shared_usernames = ("maya", "james")
    for uname in shared_usernames:
        user = await _find_user_by_username(session, uname)
        if user is None:
            log(f"[skip-peer-member] {uname} missing — run seed_moonshot first")
            continue
        existing_pm = (
            await session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project.id,
                    ProjectMemberRow.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if existing_pm is not None:
            continue
        session.add(
            ProjectMemberRow(
                id=str(uuid.uuid4()),
                project_id=project.id,
                user_id=user.id,
                role="owner" if uname == "maya" else "member",
                license_tier="full",
            )
        )
    return project


async def _seed_contractor(
    session: AsyncSession, stellar_drift_en: ProjectRow
) -> str | None:
    """Register the contractor if missing, add to Stellar Drift EN with
    license_tier='task_scoped', assign them one existing task."""
    user = await _find_user_by_username(session, CONTRACTOR_USERNAME)
    if user is None:
        salt = new_salt()
        user = UserRow(
            id=str(uuid.uuid4()),
            username=CONTRACTOR_USERNAME,
            display_name=CONTRACTOR_DISPLAY,
            password_hash=hash_password(CONTRACTOR_PASSWORD, salt),
            password_salt=salt,
            display_language="en",
        )
        session.add(user)
        await session.flush()
        log(f"[new] contractor user {CONTRACTOR_USERNAME}")

    existing_pm = (
        await session.execute(
            select(ProjectMemberRow).where(
                ProjectMemberRow.project_id == stellar_drift_en.id,
                ProjectMemberRow.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing_pm is None:
        session.add(
            ProjectMemberRow(
                id=str(uuid.uuid4()),
                project_id=stellar_drift_en.id,
                user_id=user.id,
                role="member",
                license_tier="task_scoped",
            )
        )
        log(f"[new] {CONTRACTOR_USERNAME} joined Stellar Drift as task_scoped")
    else:
        existing_pm.license_tier = "task_scoped"
        log(f"[update] {CONTRACTOR_USERNAME} tier → task_scoped")

    # Pick one task to assign. Any QA-flavored task works; fall back to
    # the first task in the project if no QA-role match.
    req = await _get_requirement(session, stellar_drift_en.id)
    if req is None:
        log("[skip-contractor-task] no requirement for Stellar Drift")
        return user.id
    tasks = list(
        (
            await session.execute(
                select(TaskRow)
                .where(TaskRow.requirement_id == req.id)
                .order_by(TaskRow.sort_order)
            )
        )
        .scalars()
        .all()
    )
    if not tasks:
        log("[skip-contractor-task] no tasks in Stellar Drift")
        return user.id
    preferred = next(
        (t for t in tasks if (t.assignee_role or "").lower() == "qa"),
        tasks[0],
    )

    existing_a = (
        await session.execute(
            select(AssignmentRow).where(
                AssignmentRow.project_id == stellar_drift_en.id,
                AssignmentRow.task_id == preferred.id,
                AssignmentRow.user_id == user.id,
                AssignmentRow.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing_a is None:
        session.add(
            AssignmentRow(
                id=str(uuid.uuid4()),
                project_id=stellar_drift_en.id,
                task_id=preferred.id,
                user_id=user.id,
                active=True,
            )
        )
        log(f"[new] contractor assigned to task '{preferred.title[:48]}'")
    return user.id


async def main() -> int:
    print("Seeding v2 feature demo data (commitments / org peer / contractor)...")
    engine = build_engine(DB_URL)
    maker = build_sessionmaker(engine)
    try:
        async with session_scope(maker) as session:
            en = await _find_project_by_title_contains(session, "Stellar Drift")
            zh = await _find_project_by_title_contains(session, "星际漂流")
            if en is None and zh is None:
                print("[FAIL] neither Stellar Drift project found. Run seed_moonshot first.")
                return 1

            # Distinguish the EN project from the peer "Mobile Port" if
            # that's been seeded before — match on exact needle.
            if en and "Mobile" in (en.title or ""):
                # Our "contains Stellar Drift" found the peer. Find the
                # canonical EN project instead.
                stmt = select(ProjectRow).where(
                    ProjectRow.title == "Stellar Drift — Season 1 Launch"
                )
                en = (await session.execute(stmt)).scalar_one_or_none()

            if en is not None:
                n = await _seed_commitments(
                    session, project=en, content=COMMITMENTS_EN
                )
                log(f"[en] wrote {n} commitments")
            if zh is not None:
                n = await _seed_commitments(
                    session, project=zh, content=COMMITMENTS_ZH
                )
                log(f"[zh] wrote {n} commitments")

            if en is not None:
                await _seed_peer_project(session, en)
                await _seed_contractor(session, en)

        print("Done.")
        print()
        print("  maya / moonshot2026 — full view, sees all commitments + contractor.")
        print(
            f"  {CONTRACTOR_USERNAME} / {CONTRACTOR_PASSWORD} "
            "— task_scoped view; banner fires + /state is the filtered subgraph."
        )
        print("  Org view should now show the Mobile Port peer + shared-member edge.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
