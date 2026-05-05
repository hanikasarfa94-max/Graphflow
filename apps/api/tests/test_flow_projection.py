"""Slice A — Flow Packet projection tests.

Covers the projection-only model from `docs/flow-packets-spec.md`:
- Synthetic id format (route:/kb:/handoff:)
- Three Slice A recipes derived from existing rows
- Bucket/recipe/status filtering
- Membership gate on the new GET endpoint
- §15 invariant: projection does NOT mutate source rows.

These tests exercise the HTTP surface (`GET /api/projects/{pid}/flows`)
end-to-end so any wiring miss in main.py / services / __init__.py /
routers is caught alongside the service logic.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    HandoffRow,
    KbItemRow,
    ProjectMemberRepository,
    ProjectRow,
    RoutedSignalRow,
    backfill_streams_from_projects,
    session_scope,
)


# ---- helpers (mirroring the existing test suites' style) ----------------


async def _register(client, username: str) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _mk_project_with_members(maker, *, owner_id: str, member_id: str):
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Flow Test"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    # Routing dispatch needs personal streams for both members.
    await backfill_streams_from_projects(maker)
    return pid


async def _list_flows(client, pid: str, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    url = f"/api/projects/{pid}/flows"
    if qs:
        url = f"{url}?{qs}"
    return await client.get(url)


# ---- empty project ------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_project_returns_empty_packet_list(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_empty_owner")
    member_id = await _register(client, "fp_empty_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "fp_empty_owner")
    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    assert r.json() == {"packets": []}


# ---- ask_with_context (RoutedSignalRow) ---------------------------------


@pytest.mark.asyncio
async def test_routed_signal_projects_to_ask_with_context_packet(api_env):
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_maya")
    raj_id = await _register(client, "fp_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    # Maya routes a question to Raj.
    await _login(client, "fp_maya")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Should we drop permadeath for boss rooms?",
            "background": [
                {"source": "graph", "snippet": "Sofia playtest: 40% rage-quit"}
            ],
            "options": [
                {
                    "id": "drop",
                    "label": "Drop permadeath",
                    "kind": "action",
                    "weight": 0.7,
                },
                {
                    "id": "keep",
                    "label": "Keep permadeath",
                    "kind": "action",
                    "weight": 0.3,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    signal_id = r.json()["signal"]["id"]

    # Maya asks for the project's flows — should see one ask_with_context.
    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    packets = r.json()["packets"]
    assert len(packets) == 1
    p = packets[0]
    assert p["id"] == f"route:{signal_id}"
    assert p["recipe_id"] == "ask_with_context"
    assert p["status"] == "active"
    assert p["stage"] == "awaiting_target"
    assert p["source_user_id"] == maya_id
    assert p["target_user_ids"] == [raj_id]
    # While pending the target IS the current waiter (§6 derivation).
    assert p["current_target_user_ids"] == [raj_id]
    # Title = first line of framing, capped to 120.
    assert "permadeath" in p["title"]
    # Evidence shell exists but is empty in Slice A.
    assert p["evidence"]["citations"] == []
    # Routed signal id is exposed for downstream linking.
    assert p["routed_signal_id"] == signal_id


# ---- promote_to_memory (KbItemRow draft) --------------------------------


async def _seed_kb_draft(maker, *, project_id: str, owner_id: str, title: str) -> str:
    """Create a draft KB row directly. The HTTP route only produces drafts
    when the membrane downgrades a duplicate group-scope title; that path
    is its own domain and not what this projection test wants to exercise."""
    item_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            KbItemRow(
                id=item_id,
                project_id=project_id,
                owner_user_id=owner_id,
                ingested_by_user_id=owner_id,
                folder_id=None,
                scope="group",
                title=title,
                content_md="Prefer session pool over per-request token mint.",
                source="manual",
                source_kind=None,
                source_identifier=None,
                raw_content="",
                classification_json={},
                status="draft",
            )
        )
    return item_id


@pytest.mark.asyncio
async def test_kb_draft_projects_to_promote_to_memory_packet(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_kb_owner")
    member_id = await _register(client, "fp_kb_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    item_id = await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="Auth flow notes"
    )

    await _login(client, "fp_kb_owner")
    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    packets = r.json()["packets"]
    kb_packets = [p for p in packets if p["recipe_id"] == "promote_to_memory"]
    assert len(kb_packets) == 1
    p = kb_packets[0]
    assert p["id"] == f"kb:{item_id}"
    assert p["status"] == "active"
    assert p["stage"] == "awaiting_membrane"
    assert p["kb_item_id"] == item_id
    # The membrane_candidate envelope is populated for awaiting-membrane
    # packets so the FE can render the right CTA.
    assert p["membrane_candidate"] is not None
    assert p["membrane_candidate"]["kind"] == "kb_item_group"
    # Title carries through.
    assert "Auth flow notes" in p["title"]


# ---- handoff (HandoffRow) -----------------------------------------------


@pytest.mark.asyncio
async def test_handoff_projects_to_handoff_packet(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_ho_owner")
    successor_id = await _register(client, "fp_ho_successor")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=successor_id
    )

    await _login(client, "fp_ho_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": owner_id, "to_user_id": successor_id},
    )
    assert r.status_code == 200, r.text
    handoff_id = r.json()["handoff"]["id"]

    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    handoff_packets = [
        p for p in r.json()["packets"] if p["recipe_id"] == "handoff"
    ]
    assert len(handoff_packets) == 1
    p = handoff_packets[0]
    assert p["id"] == f"handoff:{handoff_id}"
    assert p["status"] == "active"
    assert p["source_user_id"] == owner_id
    assert p["target_user_ids"] == [successor_id]
    assert p["handoff_id"] == handoff_id


# ---- recipe filter ------------------------------------------------------


@pytest.mark.asyncio
async def test_recipe_filter_isolates_one_recipe_at_a_time(api_env):
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_rf_maya")
    raj_id = await _register(client, "fp_rf_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    # Create one route + one KB draft + one handoff. KB draft seeded
    # directly (HTTP route requires duplicate to trigger draft state).
    await _login(client, "fp_rf_maya")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Quick design call?",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await _seed_kb_draft(maker, project_id=pid, owner_id=maya_id, title="Note")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": maya_id, "to_user_id": raj_id},
    )

    # Default — three recipes.
    r = await _list_flows(client, pid)
    recipes = {p["recipe_id"] for p in r.json()["packets"]}
    assert recipes == {"ask_with_context", "promote_to_memory", "handoff"}

    # recipe filter narrows.
    r = await _list_flows(client, pid, recipe="ask_with_context")
    assert {p["recipe_id"] for p in r.json()["packets"]} == {"ask_with_context"}

    r = await _list_flows(client, pid, recipe="handoff")
    assert {p["recipe_id"] for p in r.json()["packets"]} == {"handoff"}


# ---- bucket filter ------------------------------------------------------


@pytest.mark.asyncio
async def test_bucket_needs_me_vs_waiting_on_others(api_env):
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_bk_maya")
    raj_id = await _register(client, "fp_bk_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    await _login(client, "fp_bk_maya")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Can you weigh in?",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )

    # From Maya's POV (source): packet is waiting_on_others, not needs_me.
    r = await _list_flows(client, pid, bucket="waiting_on_others")
    assert r.status_code == 200
    waiting = r.json()["packets"]
    assert len(waiting) == 1

    r = await _list_flows(client, pid, bucket="needs_me")
    assert r.status_code == 200
    assert r.json()["packets"] == []

    # From Raj's POV (target): same packet should appear in needs_me.
    await _login(client, "fp_bk_raj")
    r = await _list_flows(client, pid, bucket="needs_me")
    assert r.status_code == 200
    needs = r.json()["packets"]
    assert len(needs) == 1
    assert needs[0]["recipe_id"] == "ask_with_context"

    r = await _list_flows(client, pid, bucket="waiting_on_others")
    assert r.json()["packets"] == []


# ---- membership gate ----------------------------------------------------


@pytest.mark.asyncio
async def test_non_member_gets_403(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_nm_owner")
    member_id = await _register(client, "fp_nm_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)
    # An outsider with no membership.
    outsider_id = await _register(client, "fp_nm_outsider")
    del outsider_id  # registered + logged in below

    await _login(client, "fp_nm_outsider")
    r = await _list_flows(client, pid)
    assert r.status_code == 403


# ---- §15 invariant: projection is read-only -----------------------------


@pytest.mark.asyncio
async def test_projection_does_not_mutate_source_rows(api_env):
    """List/projection MUST NOT change row state. Snapshot a routed signal
    and a handoff before/after a /flows call; assert byte-for-byte equality
    on the persisted columns the projection reads."""
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_inv_maya")
    raj_id = await _register(client, "fp_inv_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    await _login(client, "fp_inv_maya")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Snapshot test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": maya_id, "to_user_id": raj_id},
    )

    def _snapshot(row) -> tuple:
        return (
            row.id,
            row.status,
            getattr(row, "framing", None),
            getattr(row, "reply_json", None),
            getattr(row, "responded_at", None),
            getattr(row, "finalized_at", None),
            getattr(row, "brief_markdown", None),
        )

    async with session_scope(maker) as session:
        rs_before = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.project_id == pid)
            )
        ).scalar_one()
        ho_before = (
            await session.execute(
                select(HandoffRow).where(HandoffRow.project_id == pid)
            )
        ).scalar_one()
        rs_snap = _snapshot(rs_before)
        ho_snap = _snapshot(ho_before)

    # Trigger projection.
    r = await _list_flows(client, pid)
    assert r.status_code == 200
    assert len(r.json()["packets"]) == 2

    async with session_scope(maker) as session:
        rs_after = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.project_id == pid)
            )
        ).scalar_one()
        ho_after = (
            await session.execute(
                select(HandoffRow).where(HandoffRow.project_id == pid)
            )
        ).scalar_one()

    assert _snapshot(rs_after) == rs_snap
    assert _snapshot(ho_after) == ho_snap


# ---- synthetic id stability ---------------------------------------------


@pytest.mark.asyncio
async def test_packet_ids_are_deterministic_from_source_row(api_env):
    """Two list calls without source-row mutation must yield identical
    packet ids — the projection key is the source row's primary key,
    not a fresh uuid per call (§11)."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_id_owner")
    successor_id = await _register(client, "fp_id_successor")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=successor_id
    )
    await _login(client, "fp_id_owner")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": owner_id, "to_user_id": successor_id},
    )

    r1 = await _list_flows(client, pid)
    r2 = await _list_flows(client, pid)
    ids1 = {p["id"] for p in r1.json()["packets"]}
    ids2 = {p["id"] for p in r2.json()["packets"]}
    assert ids1 == ids2
    assert all(pid_str.startswith("handoff:") for pid_str in ids1)


# ---- A.1 — visibility, owner-needs-me, hrefs ----------------------------


async def _add_member(maker, *, project_id: str, user_id: str, role: str = "member"):
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )
    await backfill_streams_from_projects(maker)


@pytest.mark.asyncio
async def test_non_participant_member_cannot_see_route_packet(api_env):
    """A.1 visibility: a project member who is neither source nor target
    of a routed signal — and not an owner — must NOT see that packet via
    the /flows projection. Project membership alone was the leak."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_v_owner")
    maya_id = await _register(client, "fp_v_maya")
    raj_id = await _register(client, "fp_v_raj")
    bystander_id = await _register(client, "fp_v_bystander")
    # Project: owner_id is owner; maya/raj/bystander are members.
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=maya_id)
    await _add_member(maker, project_id=pid, user_id=raj_id)
    await _add_member(maker, project_id=pid, user_id=bystander_id)

    # Maya routes a question to Raj.
    await _login(client, "fp_v_maya")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Private question between Maya and Raj.",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    assert r.status_code == 200, r.text

    # Source sees it.
    r = await _list_flows(client, pid)
    routes = [p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"]
    assert len(routes) == 1

    # Target sees it.
    await _login(client, "fp_v_raj")
    r = await _list_flows(client, pid)
    routes = [p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"]
    assert len(routes) == 1

    # Project owner sees it (audit).
    await _login(client, "fp_v_owner")
    r = await _list_flows(client, pid)
    routes = [p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"]
    assert len(routes) == 1

    # Bystander member does NOT see it. This is the A.1 fix.
    await _login(client, "fp_v_bystander")
    r = await _list_flows(client, pid)
    assert r.status_code == 200
    routes = [p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"]
    assert routes == []


@pytest.mark.asyncio
async def test_owner_sees_kb_and_handoff_in_needs_me(api_env):
    """A.1 owner authority: KB review and handoff packets must populate
    `current_target_user_ids` with project owners while the underlying
    row is awaiting Membrane/finalization, so /flows?bucket=needs_me
    returns them for owners.
    """
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_om_owner")
    member_id = await _register(client, "fp_om_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Member drafts a KB item awaiting owner review.
    await _seed_kb_draft(maker, project_id=pid, owner_id=member_id, title="Owner-needs-me")
    # Owner prepares a handoff (awaiting finalize).
    await _login(client, "fp_om_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": owner_id, "to_user_id": member_id},
    )
    assert r.status_code == 200, r.text

    # Owner queries needs_me — should see BOTH the KB review and the handoff.
    r = await _list_flows(client, pid, bucket="needs_me")
    assert r.status_code == 200, r.text
    recipes = sorted(p["recipe_id"] for p in r.json()["packets"])
    assert recipes == ["handoff", "promote_to_memory"]

    # Authority + current_target are populated, not empty.
    for p in r.json()["packets"]:
        assert owner_id in p["authority_user_ids"]
        assert owner_id in p["current_target_user_ids"]


@pytest.mark.asyncio
async def test_every_active_next_action_has_href(api_env):
    """A.1 hrefs: drawer should not have to know routing rules. Every
    active packet's next_action must carry an href so the FE can render
    a link without recipe-specific routing logic."""
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_h_maya")
    raj_id = await _register(client, "fp_h_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    # Create one packet of each recipe.
    await _login(client, "fp_h_maya")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await _seed_kb_draft(maker, project_id=pid, owner_id=maya_id, title="Href test")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": maya_id, "to_user_id": raj_id},
    )

    r = await _list_flows(client, pid)
    packets = r.json()["packets"]
    assert len(packets) == 3
    for p in packets:
        assert p["status"] == "active"
        assert p["next_actions"], f"{p['recipe_id']} has empty next_actions"
        for action in p["next_actions"]:
            assert action.get("href"), (
                f"{p['recipe_id']} action {action['id']} missing href"
            )
            assert action["href"].startswith("/"), (
                f"{p['recipe_id']} href is not absolute: {action['href']}"
            )
