"""Stage 2 pre-answer routing tests.

Covers:
  * happy path: sender + target are members, pre-answer returns with
    matched_skills from target's role bundle and target metadata
  * enforcement: same-user rejected, non-member rejected, empty question
    rejected
  * real-agent sanitizer drops fabricated skills
  * rate-limit (4/min/pair) responds 429 after threshold
  * target with no role_hints yields matched_skills=[] but still
    returns a usable draft
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from workgraph_agents.pre_answer import PreAnswerDraft
from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)

from workgraph_api.main import app


async def _register_and_login(
    client: AsyncClient, username: str, password: str = "hunter22"
) -> str:
    """Register a user + log in. Returns user_id."""
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    user_id = r.json()["id"]
    # register logs in automatically, but be explicit so tests that
    # register multiple users in sequence end up authenticated as the
    # one they expect.
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text
    return user_id


async def _seed_user(
    maker,
    username: str,
    *,
    role_hints=None,
    declared=None,
) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        if role_hints or declared:
            await UserRepository(session).update_profile(
                user.id,
                role_hints=role_hints,
                declared_abilities=declared,
            )
        return user.id


async def _set_profile(maker, user_id: str, *, role_hints=None, declared=None):
    async with session_scope(maker) as session:
        await UserRepository(session).update_profile(
            user_id,
            role_hints=role_hints,
            declared_abilities=declared,
        )


async def _mk_project(maker, title="PA") -> str:
    import uuid

    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(maker, pid: str, uid: str, *, role="member"):
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )


async def _login_as(client: AsyncClient, username: str, password="hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_happy_path_returns_draft_and_target(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    sender_id = await _register_and_login(client, "pa_sender")
    await _set_profile(maker, sender_id, role_hints=["junior-engineer"])
    target_id = await _seed_user(
        maker,
        "pa_target",
        role_hints=["engineering-lead"],
        declared=["code-review"],
    )
    await _add_member(maker, pid, sender_id, role="owner")
    await _add_member(maker, pid, target_id, role="member")

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={
            "target_user_id": target_id,
            "question": "Who should approve the next release?",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["draft"]["body"]
    assert body["draft"]["confidence"] in {"high", "medium", "low"}
    # Stub fills matched_skills from role_skills → engineering-lead bundle
    assert "systems-architecture" in body["draft"]["matched_skills"]
    assert body["target"]["user_id"] == target_id
    assert "systems-architecture" in body["target"]["role_skills"]
    assert "code-review" in body["target"]["declared_abilities"]


@pytest.mark.asyncio
async def test_same_user_rejected(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    user_id = await _register_and_login(client, "pa_self")
    await _set_profile(maker, user_id, role_hints=["founder"])
    await _add_member(maker, pid, user_id, role="owner")

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={"target_user_id": user_id, "question": "?"},
    )
    assert r.status_code == 400
    assert "same_user" in r.text


@pytest.mark.asyncio
async def test_sender_not_member_forbidden(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    await _register_and_login(client, "pa_outsider")
    target_id = await _seed_user(
        maker, "pa_target_only", role_hints=["qa-lead"]
    )
    await _add_member(maker, pid, target_id, role="member")

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={"target_user_id": target_id, "question": "hi?"},
    )
    # project_service.is_member check fires before the service-level
    # sender_not_member branch.
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_target_not_member_rejected(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    sender_id = await _register_and_login(client, "pa_sender_only")
    outsider_id = await _seed_user(maker, "pa_outsider_target")
    await _set_profile(maker, sender_id, role_hints=["founder"])
    await _add_member(maker, pid, sender_id, role="owner")

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={"target_user_id": outsider_id, "question": "?"},
    )
    assert r.status_code == 400
    assert "target_not_member" in r.text


def test_real_agent_sanitizer_drops_unknown_skills():
    """Unit test of PreAnswerAgent's sanitizer helper — ensures the
    production path strips fabricated skills even when the LLM tries
    to assert expertise the target never declared."""
    from workgraph_agents.pre_answer import _sanitize_matched_skills

    draft = PreAnswerDraft(
        body="x",
        confidence="medium",
        matched_skills=["real-skill", "FAKE"],
        uncovered_topics=[],
        recommend_route=True,
        rationale="",
    )
    cleaned = _sanitize_matched_skills(
        draft,
        {
            "role_skills": ["real-skill"],
            "declared_abilities": [],
            "validated_skills": [],
        },
    )
    assert cleaned.matched_skills == ["real-skill"]


@pytest.mark.asyncio
async def test_rate_limit_kicks_in_after_threshold(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    sender_id = await _register_and_login(client, "pa_rate_sender")
    await _set_profile(maker, sender_id, role_hints=["founder"])
    target_id = await _seed_user(
        maker, "pa_rate_target", role_hints=["qa-lead"]
    )
    await _add_member(maker, pid, sender_id, role="owner")
    await _add_member(maker, pid, target_id, role="member")

    # 4 allowed, the 5th is rate-limited (window is 60s — safe within a
    # single test run).
    for _ in range(4):
        r = await client.post(
            f"/api/projects/{pid}/pre-answer",
            json={"target_user_id": target_id, "question": "q"},
        )
        assert r.status_code == 200

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={"target_user_id": target_id, "question": "q"},
    )
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_target_with_no_role_hints_still_draftable(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    sender_id = await _register_and_login(client, "pa_bare_sender")
    await _set_profile(maker, sender_id, role_hints=["founder"])
    target_id = await _seed_user(maker, "pa_bare_target")
    await _add_member(maker, pid, sender_id, role="owner")
    await _add_member(maker, pid, target_id, role="member")

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={
            "target_user_id": target_id,
            "question": "random question",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # No role → no role_skills → stub draft still returns but with empty
    # matched_skills
    assert body["draft"]["matched_skills"] == []
    assert body["target"]["role_skills"] == []


@pytest.mark.asyncio
async def test_stub_overrideable_via_app_state(api_env):
    """Tests can steer the pre-answer by assigning next_draft on the
    stub agent. Proves the stub fixture's override hook works."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    sender_id = await _register_and_login(client, "pa_override_sender")
    await _set_profile(maker, sender_id, role_hints=["founder"])
    target_id = await _seed_user(
        maker, "pa_override_target", role_hints=["qa-lead"]
    )
    await _add_member(maker, pid, sender_id, role="owner")
    await _add_member(maker, pid, target_id, role="member")

    app.state.pre_answer_agent.next_draft = PreAnswerDraft(
        body="No need to route — answered in the last decision D-42.",
        confidence="high",
        matched_skills=["playtest-coordination"],
        uncovered_topics=[],
        recommend_route=False,
        rationale="confident",
    )

    r = await client.post(
        f"/api/projects/{pid}/pre-answer",
        json={"target_user_id": target_id, "question": "Same as D-42?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["draft"]["confidence"] == "high"
    assert body["draft"]["recommend_route"] is False
    assert "D-42" in body["draft"]["body"]
