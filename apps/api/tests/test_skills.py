"""SkillsService tests (Phase Q).

Each skill is a pure read on the project graph / KB. These tests seed
the graph directly via repositories (not HTTP), then drive
SkillsService.execute and assert the result envelope.

Coverage:
  * unknown skill_name → {"ok": False, "error": "unknown_skill"}
  * kb_search — text-match, limit, substring recall, rejected excluded
  * recent_decisions — shape + project scoping
  * risk_scan — severity floor + status filter
  * member_profile — returns profile fields; non-member → error
  * project scoping — items in project A do not leak to project B
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from workgraph_api.services import SkillsService
from workgraph_persistence import (
    DecisionRepository,
    MembraneSignalRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    RiskRow,
    UserRepository,
    session_scope,
)


# ---------------------------------------------------------------------------
# Shared seed helpers.
# ---------------------------------------------------------------------------


async def _mk_project(maker, title: str = "Phase-Q test") -> str:
    async with session_scope(maker) as session:
        import uuid

        pid = str(uuid.uuid4())
        row = ProjectRow(id=pid, title=title)
        session.add(row)
        await session.flush()
    return pid


async def _mk_requirement(maker, project_id: str) -> str:
    async with session_scope(maker) as session:
        import uuid

        rid = str(uuid.uuid4())
        row = RequirementRow(
            id=rid,
            project_id=project_id,
            version=1,
            raw_text="stub requirement",
            parse_outcome="ok",
        )
        session.add(row)
        await session.flush()
    return rid


async def _mk_user(
    maker,
    username: str,
    *,
    display_name: str = "",
    role_hints: list[str] | None = None,
    declared_abilities: list[str] | None = None,
) -> str:
    async with session_scope(maker) as session:
        user_repo = UserRepository(session)
        user = await user_repo.create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=display_name or username,
        )
        if role_hints is not None or declared_abilities is not None:
            await user_repo.update_profile(
                user.id,
                role_hints=role_hints,
                declared_abilities=declared_abilities,
            )
        return user.id


async def _add_member(maker, project_id: str, user_id: str) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id
        )


async def _mk_kb_item(
    maker,
    project_id: str,
    *,
    source_identifier: str,
    raw_content: str,
    summary: str = "",
    tags: list[str] | None = None,
    status: str = "approved",
    source_kind: str = "user-drop",
) -> str:
    async with session_scope(maker) as session:
        repo = MembraneSignalRepository(session)
        row = await repo.create(
            project_id=project_id,
            source_kind=source_kind,
            source_identifier=source_identifier,
            raw_content=raw_content,
        )
        if summary or tags:
            await repo.set_classification(
                row.id,
                classification={
                    "is_relevant": True,
                    "tags": list(tags or []),
                    "summary": summary,
                    "proposed_target_user_ids": [],
                    "proposed_action": "ambient-log",
                    "confidence": 0.8,
                    "safety_notes": "",
                },
                status=status,
            )
        elif status != "pending-review":
            await repo.set_classification(
                row.id,
                classification={
                    "is_relevant": True,
                    "tags": [],
                    "summary": "",
                    "proposed_target_user_ids": [],
                    "proposed_action": "ambient-log",
                    "confidence": 0.8,
                    "safety_notes": "",
                },
                status=status,
            )
        return row.id


async def _mk_decision(
    maker, project_id: str, *, resolver_id: str, rationale: str
) -> str:
    async with session_scope(maker) as session:
        decision = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=project_id,
            resolver_id=resolver_id,
            option_index=None,
            custom_text="decision text",
            rationale=rationale,
            apply_actions=[],
            apply_outcome="advisory",
        )
        return decision.id


async def _mk_risk(
    maker,
    project_id: str,
    requirement_id: str,
    *,
    title: str,
    severity: str = "medium",
    status: str = "open",
    sort_order: int = 0,
) -> str:
    async with session_scope(maker) as session:
        import uuid

        rid = str(uuid.uuid4())
        row = RiskRow(
            id=rid,
            project_id=project_id,
            requirement_id=requirement_id,
            sort_order=sort_order,
            title=title,
            content="",
            severity=severity,
            status=status,
        )
        session.add(row)
        await session.flush()
    return rid


# ---------------------------------------------------------------------------
# Unknown skill / invalid args.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_rejects_unknown_skill_name(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="definitely_not_a_real_skill", args={}
    )
    assert out == {"ok": False, "error": "unknown_skill"}


@pytest.mark.asyncio
async def test_execute_kb_search_bad_args_surfaces_invalid_args(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="kb_search", args={"not_a_real_param": 5}
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_args"


# ---------------------------------------------------------------------------
# kb_search.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kb_search_finds_substring_match(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    await _mk_kb_item(
        maker,
        pid,
        source_identifier="kb-1",
        raw_content="Boss 1 design notes: rage-quit 40% on first encounter.",
        summary="boss 1 design",
        tags=["design", "boss"],
    )
    await _mk_kb_item(
        maker,
        pid,
        source_identifier="kb-2",
        raw_content="Inventory rework planning doc.",
        summary="inventory rework",
        tags=["inventory"],
    )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss", "limit": 5},
    )
    assert out["ok"] is True
    items = out["result"]
    assert len(items) == 1
    assert items[0]["source_identifier"] == "kb-1"
    assert "design" in items[0]["tags"]


@pytest.mark.asyncio
async def test_kb_search_respects_limit(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    for i in range(5):
        await _mk_kb_item(
            maker,
            pid,
            source_identifier=f"kb-l-{i}",
            raw_content=f"boss note {i}",
            summary=f"boss note {i}",
        )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss", "limit": 2},
    )
    assert out["ok"] is True
    assert len(out["result"]) == 2


@pytest.mark.asyncio
async def test_kb_search_excludes_rejected(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    await _mk_kb_item(
        maker,
        pid,
        source_identifier="kb-r",
        raw_content="sensitive rejected content about boss 1",
        summary="rejected",
        status="rejected",
    )
    await _mk_kb_item(
        maker,
        pid,
        source_identifier="kb-ok",
        raw_content="live boss 1 content",
        summary="live",
        status="approved",
    )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss 1"},
    )
    ids = [item["source_identifier"] for item in out["result"]]
    assert "kb-r" not in ids
    assert "kb-ok" in ids


@pytest.mark.asyncio
async def test_kb_search_scoped_to_project(api_env):
    _, maker, *_ = api_env
    pid_a = await _mk_project(maker, "A")
    pid_b = await _mk_project(maker, "B")
    await _mk_kb_item(
        maker,
        pid_a,
        source_identifier="a-1",
        raw_content="project A boss notes",
        summary="A",
    )
    await _mk_kb_item(
        maker,
        pid_b,
        source_identifier="b-1",
        raw_content="project B boss notes",
        summary="B",
    )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid_a, skill_name="kb_search", args={"query": "boss"}
    )
    ids = [item["source_identifier"] for item in out["result"]]
    assert ids == ["a-1"]


# ---------------------------------------------------------------------------
# recent_decisions.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_decisions_returns_shape_and_ordering(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "sk_u1")
    await _add_member(maker, pid, uid)
    await _mk_decision(maker, pid, resolver_id=uid, rationale="first")
    await _mk_decision(maker, pid, resolver_id=uid, rationale="second")
    await _mk_decision(maker, pid, resolver_id=uid, rationale="third")

    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="recent_decisions", args={"limit": 2}
    )
    assert out["ok"] is True
    items = out["result"]
    assert len(items) == 2
    # Most recent first (DecisionRepository orders by created_at desc).
    rationales = [i["rationale"] for i in items]
    assert "third" in rationales
    assert all("id" in i and "created_at" in i for i in items)


@pytest.mark.asyncio
async def test_recent_decisions_scoped_to_project(api_env):
    _, maker, *_ = api_env
    pid_a = await _mk_project(maker, "A")
    pid_b = await _mk_project(maker, "B")
    uid = await _mk_user(maker, "sk_u_scope")
    await _add_member(maker, pid_a, uid)
    await _add_member(maker, pid_b, uid)
    await _mk_decision(maker, pid_a, resolver_id=uid, rationale="A decision")
    await _mk_decision(maker, pid_b, resolver_id=uid, rationale="B decision")
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid_a, skill_name="recent_decisions", args={}
    )
    rationales = [i["rationale"] for i in out["result"]]
    assert rationales == ["A decision"]


# ---------------------------------------------------------------------------
# risk_scan.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risk_scan_respects_severity_floor(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    req = await _mk_requirement(maker, pid)
    await _mk_risk(
        maker,
        pid,
        req,
        title="low risk",
        severity="low",
        sort_order=0,
    )
    await _mk_risk(
        maker,
        pid,
        req,
        title="medium risk",
        severity="medium",
        sort_order=1,
    )
    await _mk_risk(
        maker,
        pid,
        req,
        title="high risk",
        severity="high",
        sort_order=2,
    )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="risk_scan",
        args={"severity_floor": "medium"},
    )
    assert out["ok"] is True
    titles = [r["title"] for r in out["result"]]
    assert "low risk" not in titles
    assert "medium risk" in titles
    assert "high risk" in titles


@pytest.mark.asyncio
async def test_risk_scan_filters_closed_risks(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    req = await _mk_requirement(maker, pid)
    await _mk_risk(
        maker, pid, req, title="open", severity="medium", status="open"
    )
    await _mk_risk(
        maker,
        pid,
        req,
        title="closed",
        severity="high",
        status="closed",
        sort_order=1,
    )
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="risk_scan", args={"severity_floor": "low"}
    )
    titles = [r["title"] for r in out["result"]]
    assert titles == ["open"]


@pytest.mark.asyncio
async def test_risk_scan_invalid_floor_returns_empty(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="risk_scan",
        args={"severity_floor": "wat"},
    )
    assert out["ok"] is True
    assert out["result"] == []


# ---------------------------------------------------------------------------
# member_profile.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_profile_returns_profile_fields(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker,
        "sk_raj",
        display_name="Raj",
        role_hints=["design-lead"],
        declared_abilities=["combat", "systems"],
    )
    await _add_member(maker, pid, uid)
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="member_profile", args={"user_id": uid}
    )
    assert out["ok"] is True
    profile = out["result"]
    assert profile["user_id"] == uid
    assert profile["display_name"] == "Raj"
    assert profile["role"] == "design-lead"
    assert profile["declared_abilities"] == ["combat", "systems"]


@pytest.mark.asyncio
async def test_member_profile_non_member_returns_error_envelope(api_env):
    _, maker, *_ = api_env
    pid_a = await _mk_project(maker, "A")
    pid_b = await _mk_project(maker, "B")
    uid = await _mk_user(maker, "sk_outsider")
    await _add_member(maker, pid_b, uid)  # only in project B
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid_a, skill_name="member_profile", args={"user_id": uid}
    )
    assert out["ok"] is True
    # The skill itself succeeds; the result carries the scoping error.
    assert out["result"] == {"error": "not_a_project_member"}


@pytest.mark.asyncio
async def test_member_profile_missing_user_id_arg_is_invalid(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid, skill_name="member_profile", args={}
    )
    assert out["ok"] is False
    assert out["error"] == "invalid_args"
