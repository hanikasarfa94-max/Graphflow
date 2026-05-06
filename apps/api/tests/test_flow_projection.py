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
    IMSuggestionRow,
    KbItemRow,
    MessageRow,
    ProjectMemberRepository,
    ProjectRow,
    RoutedSignalRow,
    StreamRepository,
    TaskRow,
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
    body = r.json()
    assert body["packets"] == []
    # D.a: response now carries a participants sidecar; empty for an
    # empty packet list.
    assert body["participants"] == {}


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


# ---- C.0 — focused hrefs (deep-link to the actionable surface) ----------


@pytest.mark.asyncio
async def test_route_packet_href_deep_links_to_routing_anchor(api_env):
    """C.0 — route packet's Open should land the user ON the routing
    message, not on the inbox dashboard. Mirrors the anchor pattern
    /inbox itself uses (inbox/page.tsx:100): /projects/{pid}/team#routing-{id}."""
    client, maker, *_ = api_env
    maya_id = await _register(client, "fp_c0_route_maya")
    raj_id = await _register(client, "fp_c0_route_raj")
    pid = await _mk_project_with_members(maker, owner_id=maya_id, member_id=raj_id)

    await _login(client, "fp_c0_route_maya")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": pid,
            "framing": "Deep-link test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    signal_id = r.json()["signal"]["id"]

    r = await _list_flows(client, pid)
    packets = [p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"]
    assert len(packets) == 1
    href = packets[0]["next_actions"][0]["href"]
    assert href == f"/projects/{pid}/team#routing-{signal_id}", href


@pytest.mark.asyncio
async def test_handoff_packet_href_points_to_skills_surface(api_env):
    """C.0 — handoff Open must land on /projects/{pid}/skills, where the
    MemberHandoffButton + HandoffDialog actually live. Pre-C.0 this
    pointed at /team, which felt hollow because /team has no handoff
    affordance."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_c0_ho_owner")
    successor_id = await _register(client, "fp_c0_ho_successor")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=successor_id
    )

    await _login(client, "fp_c0_ho_owner")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": owner_id, "to_user_id": successor_id},
    )

    r = await _list_flows(client, pid)
    packets = [p for p in r.json()["packets"] if p["recipe_id"] == "handoff"]
    assert len(packets) == 1
    href = packets[0]["next_actions"][0]["href"]
    assert href == f"/projects/{pid}/skills", href


# ---- Slice D — evidence + source_refs + participants -------------------


@pytest.mark.asyncio
async def test_route_packet_source_refs_carry_signal_and_streams(api_env):
    """D.a: source_refs should reference the routed signal itself + the
    source/target stream surfaces (with hrefs)."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fp_d_refs_src")
    tgt_id = await _register(client, "fp_d_refs_tgt")
    pid = await _mk_project_with_members(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, "fp_d_refs_src")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": pid,
            "framing": "Refs test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    sid = r.json()["signal"]["id"]

    r = await _list_flows(client, pid)
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    refs = pkt["source_refs"]
    # Routed signal itself.
    assert any(
        ref["kind"] == "agent_run" and ref["id"] == sid for ref in refs
    ), refs
    # Both stream refs with hrefs.
    streams = [ref for ref in refs if ref["kind"] == "stream"]
    assert len(streams) == 2
    for s in streams:
        assert s["href"].startswith("/streams/"), s


@pytest.mark.asyncio
async def test_evidence_human_gates_records_target_reply(api_env):
    """D.a: when target replies with an option_id, evidence.human_gates
    records the target's gate event with action='accept' (option pick)
    or 'counter' (custom_text). Source-side action notes append on top
    once the source acts."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fp_d_gate_src")
    tgt_id = await _register(client, "fp_d_gate_tgt")
    pid = await _mk_project_with_members(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, "fp_d_gate_src")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": pid,
            "framing": "Gate test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    sid = r.json()["signal"]["id"]
    # Target replies via option pick.
    await _login(client, "fp_d_gate_tgt")
    r = await client.post(
        f"/api/routing/{sid}/reply", json={"option_id": "y"}
    )
    assert r.status_code == 200, r.text

    await _login(client, "fp_d_gate_src")
    r = await _list_flows(client, pid)
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    gates = pkt["evidence"]["human_gates"]
    # Just the target's reply — source hasn't acted yet.
    assert len(gates) == 1
    assert gates[0]["user_id"] == tgt_id
    assert gates[0]["action"] == "accept"  # option pick → accept

    # Source accepts via the C.1 endpoint; gates should grow to two.
    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept", "note": "thanks"},
    )
    assert r.status_code == 200, r.text

    r = await _list_flows(client, pid, status="completed")
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    gates = pkt["evidence"]["human_gates"]
    assert len(gates) == 2
    target_gate = next(g for g in gates if g["user_id"] == tgt_id)
    source_gate = next(g for g in gates if g["user_id"] == src_id)
    assert target_gate["action"] == "accept"
    assert source_gate["action"] == "accept"
    assert source_gate["note"] == "thanks"


@pytest.mark.asyncio
async def test_custom_followup_skipped_from_human_gates(api_env):
    """D.a: custom_followup is a continuation, not a gate decision.
    It should appear in the timeline but NOT in evidence.human_gates."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fp_d_fup_src")
    tgt_id = await _register(client, "fp_d_fup_tgt")
    pid = await _mk_project_with_members(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, "fp_d_fup_src")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": pid,
            "framing": "Fup test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    sid = r.json()["signal"]["id"]
    await _login(client, "fp_d_fup_tgt")
    await client.post(f"/api/routing/{sid}/reply", json={"option_id": "y"})
    await _login(client, "fp_d_fup_src")
    await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "custom_followup", "framing": "follow-up question"},
    )

    r = await _list_flows(client, pid)
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    gates = pkt["evidence"]["human_gates"]
    # Only the target's reply gate. custom_followup is NOT a gate.
    assert len(gates) == 1
    assert gates[0]["user_id"] == tgt_id
    # But the timeline DOES carry the followup event.
    timeline_kinds = [ev["kind"] for ev in pkt["timeline"]]
    assert "source_custom_followup" in timeline_kinds


@pytest.mark.asyncio
async def test_participants_sidecar_resolves_user_ids(api_env):
    """D.a: response carries a participants map {user_id: {display_name,
    username}} so the FE renders names without N+1 fetches."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fp_d_part_src")
    tgt_id = await _register(client, "fp_d_part_tgt")
    pid = await _mk_project_with_members(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, "fp_d_part_src")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": pid,
            "framing": "Participants test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )

    r = await _list_flows(client, pid)
    body = r.json()
    participants = body["participants"]
    assert src_id in participants
    assert tgt_id in participants
    assert participants[src_id]["username"] == "fp_d_part_src"
    assert participants[tgt_id]["username"] == "fp_d_part_tgt"
    # display_name falls back to username when not set explicitly.
    assert isinstance(participants[src_id]["display_name"], str)


@pytest.mark.asyncio
async def test_timeline_carries_source_action_events(api_env):
    """D.a: timeline appends source-side action events from
    reply_json["source_action_notes"] so the evidence block can render
    the closing event."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fp_d_tl_src")
    tgt_id = await _register(client, "fp_d_tl_tgt")
    pid = await _mk_project_with_members(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, "fp_d_tl_src")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": pid,
            "framing": "Timeline test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    sid = r.json()["signal"]["id"]
    await _login(client, "fp_d_tl_tgt")
    await client.post(f"/api/routing/{sid}/reply", json={"option_id": "y"})
    await _login(client, "fp_d_tl_src")
    await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )

    r = await _list_flows(client, pid, status="completed")
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    kinds = [ev["kind"] for ev in pkt["timeline"]]
    # Original two events plus the source acceptance.
    assert "route_dispatched" in kinds
    assert "route_replied" in kinds
    assert "source_accept" in kinds


# ---- F.1 — promote_task_to_plan (TaskRow + IMSuggestion) ---------------


async def _seed_personal_task(
    maker, *, project_id: str, owner_id: str, title: str
) -> str:
    """Create a personal-scope TaskRow directly. The HTTP promote path
    requires a real Membrane invocation that may auto-merge; this helper
    skips that and lets us stage the (task, suggestion) pair the
    projection actually consumes."""
    task_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=task_id,
                project_id=project_id,
                owner_user_id=owner_id,
                requirement_id=None,
                title=title,
                description="",
                status="open",
                scope="personal",
            )
        )
    return task_id


async def _seed_task_promote_suggestion(
    maker, *, project_id: str, task_id: str, owner_id: str
) -> str:
    """Stage the IMSuggestion(membrane_review, task_promote) row that
    `task_progress.promote` would create on a request_review verdict."""
    sug_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(
            project_id
        )
        if team_stream is None:
            team_stream = await StreamRepository(session).create(
                type="project", project_id=project_id
            )
        msg_id = str(uuid.uuid4())
        session.add(
            MessageRow(
                id=msg_id,
                project_id=project_id,
                stream_id=team_stream.id,
                author_id=owner_id,
                body="Membrane staged a personal task for promote review.",
                kind="membrane-review",
                linked_id=task_id,
            )
        )
        await session.flush()
        session.add(
            IMSuggestionRow(
                id=sug_id,
                message_id=msg_id,
                project_id=project_id,
                kind="membrane_review",
                confidence=1.0,
                proposal={
                    "action": "approve_membrane_candidate",
                    "summary": f"Approve task for the project plan",
                    "detail": {
                        "candidate_kind": "task_promote",
                        "task_id": task_id,
                        "diff_summary": None,
                        "conflict_with": [],
                    },
                },
                reasoning="membrane request_review",
                status="pending",
                outcome="ok",
                attempts=1,
            )
        )
    return sug_id


@pytest.mark.asyncio
async def test_task_promote_projects_to_packet(api_env):
    """A pending task_promote suggestion + its personal TaskRow project
    to a `promote_task_to_plan` packet visible to the proposer and to
    project owners (who are the gating reviewers)."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_tp_owner")
    member_id = await _register(client, "fp_tp_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    task_id = await _seed_personal_task(
        maker,
        project_id=pid,
        owner_id=member_id,  # member is the proposer
        title="Quick triage — bug 423",
    )
    sug_id = await _seed_task_promote_suggestion(
        maker,
        project_id=pid,
        task_id=task_id,
        owner_id=owner_id,
    )

    # Owner sees the packet.
    await _login(client, "fp_tp_owner")
    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    packets = r.json()["packets"]
    tp = [p for p in packets if p["recipe_id"] == "promote_task_to_plan"]
    assert len(tp) == 1, packets
    p = tp[0]
    assert p["id"] == f"task_promote:{sug_id}"
    assert p["status"] == "active"
    assert p["stage"] == "awaiting_membrane"
    assert p["task_id"] == task_id
    assert p["im_suggestion_id"] == sug_id
    assert p["source_user_id"] == member_id
    # Owners gate the promote — present on current_target so
    # bucket=needs_me works for them.
    assert owner_id in p["current_target_user_ids"]
    assert p["membrane_candidate"] is not None
    assert p["membrane_candidate"]["kind"] == "task_promote"
    assert "Quick triage" in p["title"]


@pytest.mark.asyncio
async def test_task_promote_packet_visible_to_proposer_not_other_member(
    api_env,
):
    """The proposer (member who initiated) sees their own packet.
    A casual non-owner non-proposer member does NOT — same visibility
    rule as kb_review packets per §10."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_tpv_owner")
    proposer_id = await _register(client, "fp_tpv_proposer")
    bystander_id = await _register(client, "fp_tpv_bystander")
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="TP Visibility"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=proposer_id, role="member"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=bystander_id, role="member"
        )
    await backfill_streams_from_projects(maker)

    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=proposer_id, title="Member-only task"
    )
    await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    # Proposer sees it.
    await _login(client, "fp_tpv_proposer")
    r = await _list_flows(client, pid)
    assert r.status_code == 200
    keys = {p["recipe_id"] for p in r.json()["packets"]}
    assert "promote_task_to_plan" in keys

    # Bystander member does NOT.
    await _login(client, "fp_tpv_bystander")
    r = await _list_flows(client, pid)
    assert r.status_code == 200
    keys = {p["recipe_id"] for p in r.json()["packets"]}
    assert "promote_task_to_plan" not in keys


@pytest.mark.asyncio
async def test_task_promote_packet_drops_when_suggestion_resolves(api_env):
    """Mirrors the kb_review convention: once the suggestion status
    flips off pending (owner accepted / dismissed), the packet drops
    out of the projection. The promoted task lives on as a plan row in
    /detail/tasks; the suggestion is in audit logs. The Active Flows
    surface stops showing it because there's nothing left to act on."""
    from datetime import datetime, timezone
    from sqlalchemy import update

    client, maker, *_ = api_env
    owner_id = await _register(client, "fp_tpc_owner")
    member_id = await _register(client, "fp_tpc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="Soon-to-promote"
    )
    sug_id = await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    # Pre-resolution: packet is projected.
    await _login(client, "fp_tpc_owner")
    r = await _list_flows(client, pid)
    assert any(
        p["id"] == f"task_promote:{sug_id}" for p in r.json()["packets"]
    )

    # Simulate accept: scope flips to 'plan', suggestion resolves.
    async with session_scope(maker) as session:
        await session.execute(
            update(IMSuggestionRow)
            .where(IMSuggestionRow.id == sug_id)
            .values(
                status="accepted",
                resolved_at=datetime.now(timezone.utc),
            )
        )
        await session.execute(
            update(TaskRow).where(TaskRow.id == task_id).values(scope="plan")
        )

    # Post-resolution: packet is gone from Active Flows.
    r = await _list_flows(client, pid)
    assert not any(
        p["id"] == f"task_promote:{sug_id}" for p in r.json()["packets"]
    )


# ---- T5 — Transition Contract invariants -------------------------------


_TRANSITION_REVIEW_METHODS = {
    "none",
    "routing_reply",
    "membrane_review",
    "vote",
    "owner_acceptance",
    "agent_semantic_review",
}

_TRANSITION_STATUSES = {
    "satisfied",
    "awaiting_evidence",
    "awaiting_authority",
    "blocked",
    "completed",
}


def _assert_transition_contract_shape(contract):
    """Every packet must carry a transition_contract with the canonical
    field set. Run on every projected packet so any new recipe that
    forgets the contract trips the test."""
    assert isinstance(contract, dict), contract
    assert set(contract.keys()) == {
        "source_state",
        "target_state",
        "required_evidence",
        "authority_user_ids",
        "review_method",
        "mutation_service",
        "lineage_output",
        "status",
    }, contract.keys()
    assert isinstance(contract["source_state"], str)
    assert isinstance(contract["target_state"], str)
    assert contract["review_method"] in _TRANSITION_REVIEW_METHODS, contract
    assert contract["status"] in _TRANSITION_STATUSES, contract
    assert isinstance(contract["mutation_service"], str)
    assert contract["mutation_service"]  # non-empty
    assert isinstance(contract["required_evidence"], list)
    assert isinstance(contract["authority_user_ids"], list)
    assert isinstance(contract["lineage_output"], list)


@pytest.mark.asyncio
async def test_t5_every_packet_has_transition_contract(api_env):
    """The first invariant the doc claims: every flow packet declares
    the transition it governs. Seed one of each recipe + assert
    every projected packet has a well-shaped contract."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_all_owner")
    member_id = await _register(client, "tc_all_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed: one route, one KB draft, one task_promote.
    await _login(client, "tc_all_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Should we drop permadeath for boss rooms?",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="Auth flow notes"
    )
    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="OTP polish"
    )
    await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    packets = r.json()["packets"]
    assert len(packets) >= 3, packets
    for p in packets:
        assert "transition_contract" in p, (p["recipe_id"], p["id"])
        _assert_transition_contract_shape(p["transition_contract"])


@pytest.mark.asyncio
async def test_t5_routed_signal_uses_unknown_to_judged_states(api_env):
    """A routed performance question is not represented merely as a
    todo. source_state names the unresolved knowledge state; target
    names the desired judged state. Review method is routing_reply."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_route_owner")
    member_id = await _register(client, "tc_route_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "tc_route_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Switch performance feasibility check",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )

    r = await _list_flows(client, pid)
    routes = [
        p for p in r.json()["packets"] if p["recipe_id"] == "ask_with_context"
    ]
    assert len(routes) == 1
    contract = routes[0]["transition_contract"]
    assert contract["source_state"] == "question_unanswered"
    assert contract["target_state"] == "expert_reply_received"
    assert contract["review_method"] == "routing_reply"
    assert contract["mutation_service"] == "RoutingService"
    # Awaiting target → authority IS the target.
    assert contract["status"] == "awaiting_authority"
    assert contract["authority_user_ids"] == [member_id]
    # required_evidence carries the framing + the routing_basis envelope
    # persisted by R2.
    kinds = {e["kind"] for e in contract["required_evidence"]}
    assert "framing" in kinds
    assert "routing_basis" in kinds


@pytest.mark.asyncio
async def test_t5_task_promote_uses_personal_to_plan_states(api_env):
    """task_promote packets show personal_task_draft → plan_task_candidate
    with Membrane as the review boundary."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_task_owner")
    member_id = await _register(client, "tc_task_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="Bug 423 triage"
    )
    sug_id = await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    await _login(client, "tc_task_owner")
    r = await _list_flows(client, pid)
    pkt = next(
        p
        for p in r.json()["packets"]
        if p["id"] == f"task_promote:{sug_id}"
    )
    contract = pkt["transition_contract"]
    assert contract["source_state"] == "personal_task_draft"
    assert contract["target_state"] == "plan_task_candidate"
    assert contract["review_method"] == "membrane_review"
    assert "MembraneService" in contract["mutation_service"]
    # Owners gate the accept.
    assert owner_id in contract["authority_user_ids"]
    # Required evidence carries the task ref + the membrane suggestion.
    kinds = {e["kind"] for e in contract["required_evidence"]}
    assert "task" in kinds
    assert "membrane_suggestion" in kinds


@pytest.mark.asyncio
async def test_t5_completed_routed_signal_carries_lineage(api_env):
    """Once the target replies AND the source accepts, the route
    packet's transition_contract.lineage_output names the reply +
    source-action audit refs."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_lin_owner")
    member_id = await _register(client, "tc_lin_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "tc_lin_owner")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Boss rage-quit calibration",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )
    sid = r.json()["signal"]["id"]

    # Target replies.
    await _login(client, "tc_lin_member")
    await client.post(f"/api/routing/{sid}/reply", json={"option_id": "y"})

    # Source accepts via the flow action endpoint.
    await _login(client, "tc_lin_owner")
    await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )

    r = await _list_flows(client, pid, status="completed")
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"route:{sid}")
    contract = pkt["transition_contract"]
    assert contract["status"] == "completed"
    # The terminal target_state names what kind of resolution.
    assert contract["target_state"] in (
        "reply_accepted",
        "reply_countered",
        "reply_escalated",
    )
    # Lineage carries the reply + the source action.
    lineage_kinds = {e["kind"] for e in contract["lineage_output"]}
    assert "routed_reply" in lineage_kinds
    assert any(k.startswith("source_") for k in lineage_kinds)


@pytest.mark.asyncio
async def test_t5_kb_review_packet_names_membrane_authority(api_env):
    """KB review packet declares membrane_review as the review method
    and lists project owners as authority while alive."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_kb_owner")
    member_id = await _register(client, "tc_kb_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    item_id = await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="KB transition test"
    )

    await _login(client, "tc_kb_owner")
    r = await _list_flows(client, pid)
    pkt = next(p for p in r.json()["packets"] if p["id"] == f"kb:{item_id}")
    contract = pkt["transition_contract"]
    assert contract["target_state"] == "canonical_world_memory"
    assert contract["review_method"] == "membrane_review"
    assert "MembraneService" in contract["mutation_service"]
    # While alive (draft / pending-review), authority is the owner pool.
    assert owner_id in contract["authority_user_ids"]


@pytest.mark.asyncio
async def test_t5_awaiting_human_packet_has_non_empty_authority(api_env):
    """Invariant: if a packet's transition_contract.status is
    'awaiting_authority', its authority_user_ids cannot be empty —
    that would mean we know a human gates this transition but we don't
    know who. That's a worse failure mode than not declaring the
    contract at all."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "tc_auth_owner")
    member_id = await _register(client, "tc_auth_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed all three packet kinds awaiting authority.
    await _login(client, "tc_auth_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Boss tuning ask",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="KB auth test"
    )
    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="task auth test"
    )
    await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    r = await _list_flows(client, pid)
    for p in r.json()["packets"]:
        contract = p["transition_contract"]
        if contract["status"] == "awaiting_authority":
            assert contract["authority_user_ids"], (
                f"packet {p['id']} is awaiting_authority but has "
                f"empty authority_user_ids — that's a contract violation"
            )
