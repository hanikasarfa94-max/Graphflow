"""Phase 7'' collab endpoint tests: projects, invite, assign, comments,
messages, notifications, IM suggestions.

All paths go through the HTTP surface so the auth + membership guards are
exercised alongside the service logic.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client: AsyncClient, username: str, password: str = "hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _intake_canonical(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _alt_client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_project_invite_and_membership_lists(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner1")
    project_id = await _intake_canonical(client, "collab-evt-1")
    # Invite a second user
    await _register(client, "member1")
    await _login(client, "owner1")
    r = await client.post(
        f"/api/projects/{project_id}/invite",
        json={"username": "member1"},
    )
    assert r.status_code == 200, r.text
    members = await client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    usernames = {m["username"] for m in members.json()}
    assert usernames == {"owner1", "member1"}


@pytest.mark.asyncio
async def test_non_member_cannot_read_project_state(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner2")
    project_id = await _intake_canonical(client, "collab-evt-2")

    async with _alt_client() as outsider:
        await _register(outsider, "stranger")
        r = await outsider.get(f"/api/projects/{project_id}/state")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_plan_assignment_emits_notification_to_assignee(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "owner3")
    project_id = await _intake_canonical(client, "collab-evt-3")
    # run clarify → answer → plan so tasks exist
    q = await client.post(f"/api/projects/{project_id}/clarify")
    assert q.status_code == 200, q.text
    questions = q.json()["questions"]
    for question in questions:
        await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": question["id"], "answer": "ok"},
        )
    plan_resp = await client.post(f"/api/projects/{project_id}/plan")
    assert plan_resp.status_code == 200, plan_resp.text
    state = await client.get(f"/api/projects/{project_id}/state")
    tasks = state.json()["plan"]["tasks"]
    assert tasks, "expected at least one task after planning"
    task_id = tasks[0]["id"]

    # Invite member and assign them
    await _register(client, "assignee1")
    await _login(client, "owner3")
    invite = await client.post(
        f"/api/projects/{project_id}/invite", json={"username": "assignee1"}
    )
    assert invite.status_code == 200

    members = (await client.get(f"/api/projects/{project_id}/members")).json()
    assignee_id = next(m["user_id"] for m in members if m["username"] == "assignee1")

    assign = await client.post(
        f"/api/tasks/{task_id}/assignment", json={"user_id": assignee_id}
    )
    assert assign.status_code == 200, assign.text

    # Assignee sees the notification.
    await _login(client, "assignee1")
    notifs = await client.get("/api/notifications")
    assert notifs.status_code == 200
    body = notifs.json()
    kinds = {n["kind"] for n in body["items"]}
    assert "assigned" in kinds
    assert body["unread_count"] >= 1


@pytest.mark.asyncio
async def test_comment_mention_notifies_target_user(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner4")
    project_id = await _intake_canonical(client, "collab-evt-4")
    # Walk through clarify + plan to get a real task id.
    q = await client.post(f"/api/projects/{project_id}/clarify")
    for question in q.json()["questions"]:
        await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": question["id"], "answer": "ok"},
        )
    await client.post(f"/api/projects/{project_id}/plan")
    tasks = (await client.get(f"/api/projects/{project_id}/state")).json()[
        "plan"
    ]["tasks"]
    task_id = tasks[0]["id"]

    # Invite user that will be mentioned.
    await _register(client, "mentioned1")
    await _login(client, "owner4")
    await client.post(
        f"/api/projects/{project_id}/invite", json={"username": "mentioned1"}
    )

    post = await client.post(
        f"/api/tasks/{task_id}/comments",
        json={"body": "hey @mentioned1 take a look"},
    )
    assert post.status_code == 200, post.text

    await _login(client, "mentioned1")
    notifs = await client.get("/api/notifications?unread_only=true")
    kinds = {n["kind"] for n in notifs.json()["items"]}
    assert "mentioned" in kinds


@pytest.mark.asyncio
async def test_message_post_and_list_round_trip(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner5")
    project_id = await _intake_canonical(client, "collab-evt-5")

    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "hello team, kickoff today"},
    )
    assert r.status_code == 200
    await asyncio.sleep(0.05)  # let the classify task settle

    messages = await client.get(f"/api/projects/{project_id}/messages")
    assert messages.status_code == 200
    body = messages.json()
    assert len(body["messages"]) == 1
    assert body["messages"][0]["body"] == "hello team, kickoff today"


@pytest.mark.asyncio
async def test_message_rate_limit_returns_429(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner6")
    project_id = await _intake_canonical(client, "collab-evt-6")
    # Hub limit_per_sec=10. Blast 12 messages back-to-back.
    statuses = []
    for i in range(12):
        r = await client.post(
            f"/api/projects/{project_id}/messages",
            json={"body": f"msg {i}"},
        )
        statuses.append(r.status_code)
    assert 429 in statuses


@pytest.mark.asyncio
async def test_im_suggestion_runs_for_long_message_and_is_listed(api_env):
    client, _, _, _, _, _ = api_env
    im_service = app.state.im_service
    await _register(client, "owner7")
    project_id = await _intake_canonical(client, "collab-evt-7")

    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "I'm completely blocked on the design review today"},
    )
    assert r.status_code == 200
    await im_service.drain()

    messages = await client.get(f"/api/projects/{project_id}/messages")
    body = messages.json()
    m = body["messages"][0]
    assert m.get("suggestion") is not None
    assert m["suggestion"]["kind"] in {"blocker", "decision", "tag", "none"}


@pytest.mark.asyncio
async def test_im_accept_opens_risk_and_touches_graph(api_env):
    client, _, _, _, _, _ = api_env
    im_service = app.state.im_service
    await _register(client, "owner8")
    project_id = await _intake_canonical(client, "collab-evt-8")

    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "I'm blocked on the SDK rollout — can't move forward"},
    )
    assert r.status_code == 200
    await im_service.drain()

    # Stub classifier marks "blocked" as blocker kind.
    messages = (await client.get(f"/api/projects/{project_id}/messages")).json()[
        "messages"
    ]
    suggestion = messages[0]["suggestion"]
    assert suggestion["kind"] == "blocker"

    before = (await client.get(f"/api/projects/{project_id}/state")).json()[
        "graph"
    ]["risks"]
    before_count = len(before)

    accept = await client.post(f"/api/im_suggestions/{suggestion['id']}/accept")
    assert accept.status_code == 200, accept.text
    applied = accept.json()["applied"]
    assert applied["action"] == "open_risk"
    assert applied["graph_touched"] is True

    after = (await client.get(f"/api/projects/{project_id}/state")).json()[
        "graph"
    ]["risks"]
    assert len(after) == before_count + 1


@pytest.mark.asyncio
async def test_mark_notification_read(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner9")
    project_id = await _intake_canonical(client, "collab-evt-9")
    await _register(client, "member9")
    await _login(client, "owner9")
    await client.post(
        f"/api/projects/{project_id}/invite", json={"username": "member9"}
    )
    # Member receives a message notification.
    await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "hi all"},
    )
    await _login(client, "member9")
    notifs = (await client.get("/api/notifications")).json()
    assert notifs["unread_count"] >= 1
    first = notifs["items"][0]
    r = await client.post(f"/api/notifications/{first['id']}/read")
    assert r.status_code == 200
    after = (await client.get("/api/notifications")).json()
    assert after["unread_count"] == notifs["unread_count"] - 1
