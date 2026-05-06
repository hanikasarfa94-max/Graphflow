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
    DecisionRow,
    HandoffRow,
    IMSuggestionRow,
    KbItemRow,
    MessageRow,
    ProjectMemberRepository,
    ProjectRow,
    RoutedSignalRow,
    StreamMemberRepository,
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


# ---- DC — Decision Flow Packet Projection ------------------------------


async def _seed_decision_pending_suggestion(
    maker,
    *,
    project_id: str,
    project_stream_id: str,
    proposer_id: str,
    summary: str = "Cut revive from launch",
) -> str:
    """Stage an IMSuggestion(kind='decision', status='pending') with a
    real source message in the project stream so the projection's
    smallest-relevant-vote membership lookup returns non-empty."""
    msg_id = str(uuid.uuid4())
    sug_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            MessageRow(
                id=msg_id,
                project_id=project_id,
                stream_id=project_stream_id,
                author_id=proposer_id,
                body="Looking at Sofia's report — let's cut revive.",
                kind="text",
                linked_id=None,
            )
        )
        await session.flush()
        session.add(
            IMSuggestionRow(
                id=sug_id,
                message_id=msg_id,
                project_id=project_id,
                kind="decision",
                confidence=0.78,
                proposal={
                    "action": "crystallize_decision",
                    "summary": summary,
                    "detail": {
                        "decision_class": "scope_cut",
                    },
                },
                reasoning="IMAssist flagged decision-shaped turn",
                status="pending",
                outcome="ok",
                attempts=1,
            )
        )
    return sug_id


async def _seed_decision_row(
    maker,
    *,
    project_id: str,
    resolver_id: str,
    custom_text: str = "Cut revive from launch",
    rationale: str = "Out of scope for the 6-week alpha.",
    source_suggestion_id: str | None = None,
    scope_stream_id: str | None = None,
    apply_outcome: str = "advisory",
) -> str:
    from datetime import datetime, timezone

    decision_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            DecisionRow(
                id=decision_id,
                project_id=project_id,
                resolver_id=resolver_id,
                custom_text=custom_text,
                rationale=rationale,
                source_suggestion_id=source_suggestion_id,
                scope_stream_id=scope_stream_id,
                apply_actions=[],
                apply_outcome=apply_outcome,
                created_at=datetime.now(timezone.utc),
            )
        )
    return decision_id


async def _add_to_stream(maker, stream_id: str, user_ids: list[str]) -> None:
    async with session_scope(maker) as session:
        sm_repo = StreamMemberRepository(session)
        for uid in user_ids:
            try:
                await sm_repo.upsert(stream_id=stream_id, user_id=uid)
            except AttributeError:
                # Fallback shape — different repos use different add APIs.
                await sm_repo.add(stream_id=stream_id, user_id=uid)


@pytest.mark.asyncio
async def test_dc_pending_decision_suggestion_projects(api_env):
    """A pending IMSuggestion(kind='decision') projects as a
    crystallize_decision packet with awaiting_authority status and
    discussion_or_suggestion → canonical_decision states."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_pend_owner")
    member_id = await _register(client, "dc_pend_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # The project stream needs to exist + have the proposer as a
    # member so smallest-relevant-vote authority resolves.
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        assert team_stream is not None
        team_stream_id = team_stream.id
    await _add_to_stream(maker, team_stream_id, [owner_id, member_id])

    sug_id = await _seed_decision_pending_suggestion(
        maker,
        project_id=pid,
        project_stream_id=team_stream_id,
        proposer_id=member_id,
    )

    await _login(client, "dc_pend_owner")
    r = await _list_flows(client, pid)
    assert r.status_code == 200, r.text
    decisions = [
        p
        for p in r.json()["packets"]
        if p["recipe_id"] == "crystallize_decision"
    ]
    assert len(decisions) == 1
    pkt = decisions[0]
    assert pkt["id"] == f"decision_pending:{sug_id}"
    assert pkt["status"] == "active"
    contract = pkt["transition_contract"]
    assert contract["source_state"] == "discussion_or_suggestion"
    assert contract["target_state"] == "canonical_decision"
    assert contract["status"] == "awaiting_authority"
    assert contract["review_method"] == "owner_acceptance"
    # Authority pool includes scope-stream members (smallest-relevant
    # vote) plus owners.
    assert owner_id in contract["authority_user_ids"]
    assert member_id in contract["authority_user_ids"]


@pytest.mark.asyncio
async def test_dc_crystallized_decision_carries_lineage(api_env):
    """A recent DecisionRow projects as a completed crystallize_decision
    packet whose lineage_output names the DecisionRow itself."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_xtl_owner")
    member_id = await _register(client, "dc_xtl_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed a source suggestion so the lineage carries it.
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        team_stream_id = team_stream.id
    sug_id = await _seed_decision_pending_suggestion(
        maker,
        project_id=pid,
        project_stream_id=team_stream_id,
        proposer_id=member_id,
        summary="Adopt the new auth pool sizing",
    )
    decision_id = await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        source_suggestion_id=sug_id,
        custom_text="Adopt the new auth pool sizing",
    )

    await _login(client, "dc_xtl_owner")
    r = await _list_flows(client, pid)
    decisions = [
        p
        for p in r.json()["packets"]
        if p["id"] == f"decision:{decision_id}"
    ]
    assert len(decisions) == 1
    pkt = decisions[0]
    assert pkt["status"] == "completed"
    contract = pkt["transition_contract"]
    assert contract["status"] == "completed"
    # Lineage_output names the DecisionRow.
    lineage_kinds = [e["kind"] for e in contract["lineage_output"]]
    assert "decision" in lineage_kinds
    decision_ref = next(
        e for e in contract["lineage_output"] if e["kind"] == "decision"
    )
    assert decision_ref["id"] == decision_id
    # Required evidence carries the source suggestion ref.
    ev_kinds = [e["kind"] for e in contract["required_evidence"]]
    assert "im_suggestion" in ev_kinds


@pytest.mark.asyncio
async def test_dc_scope_stream_decision_uses_vote_method(api_env):
    """When the crystallized DecisionRow has scope_stream_id set
    (smallest-relevant-vote), the contract names review_method='vote'."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_scope_owner")
    member_id = await _register(client, "dc_scope_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        scope_stream_id = team_stream.id

    decision_id = await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        scope_stream_id=scope_stream_id,
        custom_text="Voted: cap pool at 200",
    )

    await _login(client, "dc_scope_owner")
    r = await _list_flows(client, pid)
    pkt = next(
        p for p in r.json()["packets"] if p["id"] == f"decision:{decision_id}"
    )
    contract = pkt["transition_contract"]
    assert contract["review_method"] == "vote"
    # The scope_stream ref is in required_evidence.
    assert any(
        e["kind"] == "stream" and e["id"] == scope_stream_id
        for e in contract["required_evidence"]
    )


@pytest.mark.asyncio
async def test_dc_completed_decision_visible_to_non_owner_member(api_env):
    """Completed decisions are project-public — a non-owner non-resolver
    member must still see the packet, because decisions are the
    canonical record."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_vis_owner")
    member_id = await _register(client, "dc_vis_member")
    bystander_id = await _register(client, "dc_vis_bystander")
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="DC visibility"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=bystander_id, role="member"
        )
    await backfill_streams_from_projects(maker)

    decision_id = await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=member_id,  # not the bystander
        custom_text="Picked option B",
    )

    # Bystander (non-owner, non-resolver) should still see it.
    await _login(client, "dc_vis_bystander")
    r = await _list_flows(client, pid)
    assert any(
        p["id"] == f"decision:{decision_id}" for p in r.json()["packets"]
    )


@pytest.mark.asyncio
async def test_dc_decision_packet_satisfies_universal_contract_shape(
    api_env,
):
    """Smoke: the universal transition_contract shape invariant from
    T5 holds for the new decision packets too — both pending and
    crystallized."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_uni_owner")
    member_id = await _register(client, "dc_uni_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        team_stream_id = team_stream.id

    await _seed_decision_pending_suggestion(
        maker,
        project_id=pid,
        project_stream_id=team_stream_id,
        proposer_id=member_id,
    )
    await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        custom_text="Crystallized record",
    )

    await _login(client, "dc_uni_owner")
    r = await _list_flows(client, pid, recipe="crystallize_decision")
    assert r.status_code == 200
    packets = r.json()["packets"]
    assert len(packets) == 2
    for p in packets:
        _assert_transition_contract_shape(p["transition_contract"])
        # Decision contracts always have the same source/target axis.
        assert p["transition_contract"]["source_state"] == (
            "discussion_or_suggestion"
        )
        assert p["transition_contract"]["target_state"] == "canonical_decision"


# ---- DC.1 follow-up — upstream-message linked_id evidence edge ---------


@pytest.mark.asyncio
async def test_dc_pending_decision_carries_upstream_routed_signal_evidence(
    api_env,
):
    """When the decision-suggestion's source message has a linked_id
    pointing at an upstream RoutedSignalRow (kind 'routed-reply' /
    'routed-inbound' / 'edge-route-proposal'), the pending packet's
    transition_contract.required_evidence carries a routed_signal
    FlowRef to that upstream id."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_up_owner")
    member_id = await _register(client, "dc_up_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed a routed signal so we have a real upstream row id to point
    # at. The linked_id on the source message references this row.
    routed_signal_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        team_stream_id = team_stream.id
        # Both source/target streams default to the team stream for the
        # purposes of this test — we only need the row id, not its
        # full lifecycle.
        session.add(
            RoutedSignalRow(
                id=routed_signal_id,
                source_user_id=owner_id,
                target_user_id=member_id,
                source_stream_id=team_stream_id,
                target_stream_id=team_stream_id,
                project_id=pid,
                framing="Should we cap pool at 200?",
                background_json=[],
                options_json=[],
                status="replied",
            )
        )
    await _add_to_stream(maker, team_stream_id, [owner_id, member_id])

    # Source message is a 'routed-reply' (the kind RoutingService posts
    # when a target replies, with linked_id=routed_signal_id). The
    # IMSuggestion classifies this reply as decision-shaped.
    msg_id = str(uuid.uuid4())
    sug_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            MessageRow(
                id=msg_id,
                project_id=pid,
                stream_id=team_stream_id,
                author_id=member_id,
                body="Reply: yes, cap at 200 — confirmed by the perf test.",
                kind="routed-reply",
                linked_id=routed_signal_id,
            )
        )
        await session.flush()
        session.add(
            IMSuggestionRow(
                id=sug_id,
                message_id=msg_id,
                project_id=pid,
                kind="decision",
                confidence=0.82,
                proposal={
                    "action": "crystallize_decision",
                    "summary": "Cap pool at 200",
                },
                reasoning="IMAssist flagged the reply as decision-shaped.",
                status="pending",
                outcome="ok",
                attempts=1,
            )
        )

    await _login(client, "dc_up_owner")
    r = await _list_flows(client, pid, recipe="crystallize_decision")
    assert r.status_code == 200
    packets = r.json()["packets"]
    assert len(packets) == 1
    pkt = packets[0]
    contract = pkt["transition_contract"]

    # The upstream routed_signal ref is in required_evidence with the
    # right id and kind.
    routed_refs = [
        e for e in contract["required_evidence"] if e["kind"] == "routed_signal"
    ]
    assert len(routed_refs) == 1, contract["required_evidence"]
    assert routed_refs[0]["id"] == routed_signal_id
    # Plus the source_message + im_suggestion + stream refs we already
    # had — additive only.
    kinds = {e["kind"] for e in contract["required_evidence"]}
    assert "im_suggestion" in kinds
    assert "source_message" in kinds
    assert "stream" in kinds


@pytest.mark.asyncio
async def test_dc_unknown_message_kind_does_not_invent_upstream_ref(api_env):
    """Negative invariant: when the source message kind is not in the
    decision-relevant lineage allow-list (e.g. plain 'text'), the
    projection emits NO upstream FlowRef rather than mis-classifying
    the linked_id as something it isn't. Guards against the closed
    allow-list silently growing."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "dc_unk_owner")
    member_id = await _register(client, "dc_unk_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        team_stream_id = team_stream.id
    await _add_to_stream(maker, team_stream_id, [owner_id, member_id])

    # 'text' kind with a stray linked_id is a real shape (e.g. some
    # legacy paths set linked_id even on plain messages). Projection
    # must not invent a typed ref for it.
    stray_link = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    sug_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            MessageRow(
                id=msg_id,
                project_id=pid,
                stream_id=team_stream_id,
                author_id=member_id,
                body="Just talking — let's cap pool at 200.",
                kind="text",
                linked_id=stray_link,  # unknown semantic; must be ignored
            )
        )
        await session.flush()
        session.add(
            IMSuggestionRow(
                id=sug_id,
                message_id=msg_id,
                project_id=pid,
                kind="decision",
                confidence=0.7,
                proposal={
                    "action": "crystallize_decision",
                    "summary": "Cap pool at 200",
                },
                reasoning="IMAssist",
                status="pending",
                outcome="ok",
                attempts=1,
            )
        )

    await _login(client, "dc_unk_owner")
    r = await _list_flows(client, pid, recipe="crystallize_decision")
    pkt = r.json()["packets"][0]
    contract = pkt["transition_contract"]
    # No routed_signal / kb_item / task ref invented.
    inferred_kinds = {
        e["kind"] for e in contract["required_evidence"]
    } & {"routed_signal", "kb_item", "task"}
    assert inferred_kinds == set(), contract["required_evidence"]


# ---- E4 — Epistemic Event Contract invariants --------------------------


_EPISTEMIC_KINDS = {
    "question",
    "claim",
    "proposal",
    "decision",
    "memory",
    "task_transition",
    "capability_claim",
    "handoff",
    "risk",
    "constraint",
}

_EPISTEMIC_STATUSES = {
    "private",
    "draft",
    "hypothesis",
    "proposed",
    "review_pending",
    "accepted_for_scope",
    "canonical",
    "validated",
    "superseded",
    "rejected",
    "archived",
}

_EPISTEMIC_VISIBILITY_SCOPES = {
    "personal",
    "room",
    "project",
    "department",
    "enterprise",
}

_EPISTEMIC_MEMBRANE_POLICIES = {
    "none",
    "auto_merge",
    "request_review",
    "request_clarification",
    "reject",
    "advisory",
}


def _assert_epistemic_event_shape(ev):
    """Universal invariants: shape + closed-set vocabularies + the
    hard rules the spec calls out."""
    assert isinstance(ev, dict), ev
    expected_keys = {
        "kind",
        "status",
        "proposition",
        "source_actor_id",
        "target_audience",
        "visibility_scope",
        "accepted_scope",
        "evidence_refs",
        "preconditions",
        "authority_required",
        "membrane_policy",
        "update_effects",
        "lineage_output",
        "supersedes",
        "expires_at",
    }
    assert set(ev.keys()) == expected_keys, ev.keys()

    # Hard rule: kind and status are SEPARATE — each in its own
    # closed vocab.
    assert ev["kind"] in _EPISTEMIC_KINDS, ev
    assert ev["status"] in _EPISTEMIC_STATUSES, ev
    # No common_knowledge anywhere.
    assert "common_knowledge" not in ev

    assert ev["visibility_scope"] in _EPISTEMIC_VISIBILITY_SCOPES, ev
    assert ev["membrane_policy"] in _EPISTEMIC_MEMBRANE_POLICIES, ev

    # accepted_for_scope MUST come with an accepted_scope block.
    if ev["status"] == "accepted_for_scope":
        assert ev["accepted_scope"] is not None, ev
        sc = ev["accepted_scope"]
        assert sc["scope_type"] in _EPISTEMIC_VISIBILITY_SCOPES, sc
        assert "scope_id" in sc
        assert isinstance(sc["accepted_by_user_ids"], list)

    # review_pending MUST carry non-empty authority_required for any
    # human-facing kind. capability_claim is the only
    # potentially-system-only kind we allow exceptions for, and even
    # that's a stretch — rule applies universally for now.
    if ev["status"] == "review_pending":
        assert ev["authority_required"], ev

    # Lists are lists, not None.
    for k in (
        "target_audience",
        "evidence_refs",
        "preconditions",
        "authority_required",
        "update_effects",
        "lineage_output",
        "supersedes",
    ):
        assert isinstance(ev[k], list), (k, ev[k])


@pytest.mark.asyncio
async def test_e4_every_packet_has_epistemic_event(api_env):
    """First invariant: every projected packet has a well-shaped
    epistemic_event envelope."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_all_owner")
    member_id = await _register(client, "ee_all_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed one of each recipe.
    await _login(client, "ee_all_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Should we drop permadeath?",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )
    await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="Auth notes"
    )
    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="OTP polish"
    )
    await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    r = await _list_flows(client, pid)
    packets = r.json()["packets"]
    assert len(packets) >= 3
    for p in packets:
        assert "epistemic_event" in p, p["id"]
        _assert_epistemic_event_shape(p["epistemic_event"])


@pytest.mark.asyncio
async def test_e4_kind_and_status_are_separate(api_env):
    """The kind axis (question/memory/etc.) and the status axis
    (proposed/review_pending/accepted_for_scope/...) must NOT
    collapse into a combined enum — each comes from its own closed
    vocabulary on every packet."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_sep_owner")
    member_id = await _register(client, "ee_sep_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "ee_sep_owner")
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
        maker, project_id=pid, owner_id=owner_id, title="kind/status sep test"
    )

    r = await _list_flows(client, pid)
    for p in r.json()["packets"]:
        ev = p["epistemic_event"]
        # Kind values come from the kind set; status values come from
        # the status set. These sets do not overlap (sanity).
        assert ev["kind"] not in _EPISTEMIC_STATUSES, ev
        assert ev["status"] not in _EPISTEMIC_KINDS, ev


@pytest.mark.asyncio
async def test_e4_no_common_knowledge_field_anywhere(api_env):
    """The spec's hardest line: NO common_knowledge field, anywhere
    in the response. Walk the entire response payload."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_ck_owner")
    member_id = await _register(client, "ee_ck_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "ee_ck_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Common knowledge test",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
            ],
        },
    )
    r = await _list_flows(client, pid)
    body = r.json()
    text = __import__("json").dumps(body, ensure_ascii=False)
    assert "common_knowledge" not in text, body


@pytest.mark.asyncio
async def test_e4_routed_signal_is_directed_epistemic_action(api_env):
    """Routed signal projects as kind='question' (not notification),
    target_audience names the target, evidence_refs include the
    routing_basis envelope from R2."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_rt_owner")
    member_id = await _register(client, "ee_rt_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "ee_rt_owner")
    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": member_id,
            "project_id": pid,
            "framing": "Switch perf feasibility ask",
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
    ev = routes[0]["epistemic_event"]
    assert ev["kind"] == "question"
    assert member_id in ev["target_audience"]
    assert ev["status"] == "proposed"
    # routing_basis envelope from R2 is in evidence_refs.
    kinds = [e["kind"] for e in ev["evidence_refs"]]
    assert "framing" in kinds
    assert "routing_basis" in kinds


@pytest.mark.asyncio
async def test_e4_kb_review_packet_membrane_policy_request_review(api_env):
    """KB packet: kind=memory, status=review_pending,
    membrane_policy=request_review, authority_required non-empty."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_kb_owner")
    member_id = await _register(client, "ee_kb_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="KB review event test"
    )
    await _login(client, "ee_kb_owner")
    r = await _list_flows(client, pid, recipe="promote_to_memory")
    pkt = r.json()["packets"][0]
    ev = pkt["epistemic_event"]
    assert ev["kind"] == "memory"
    # The seeded row's status is 'draft' — projection maps that to 'draft'.
    # Either draft or review_pending is acceptable depending on KbItemRow.status.
    assert ev["status"] in ("draft", "review_pending")
    # Both alive states gate on Membrane review.
    assert ev["membrane_policy"] == "request_review"
    assert ev["authority_required"], ev
    assert owner_id in ev["authority_required"]


@pytest.mark.asyncio
async def test_e4_task_promote_packet_names_membrane_boundary(api_env):
    """Task promote packet: kind=task_transition, status=review_pending,
    membrane_policy names Membrane as the boundary."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_tp_owner")
    member_id = await _register(client, "ee_tp_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    task_id = await _seed_personal_task(
        maker, project_id=pid, owner_id=member_id, title="Triage bug"
    )
    await _seed_task_promote_suggestion(
        maker, project_id=pid, task_id=task_id, owner_id=owner_id
    )

    await _login(client, "ee_tp_owner")
    r = await _list_flows(client, pid, recipe="promote_task_to_plan")
    pkt = r.json()["packets"][0]
    ev = pkt["epistemic_event"]
    assert ev["kind"] == "task_transition"
    assert ev["status"] == "review_pending"
    assert ev["membrane_policy"] == "request_review"
    assert owner_id in ev["authority_required"]


@pytest.mark.asyncio
async def test_e4_crystallized_decision_carries_accepted_scope(api_env):
    """Crystallized DecisionRow projects as kind=decision,
    status=accepted_for_scope; accepted_scope reflects scope_stream_id
    when set, else project."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_dc_owner")
    member_id = await _register(client, "ee_dc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(pid)
        scope_stream_id = team_stream.id

    decision_id = await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        scope_stream_id=scope_stream_id,
        custom_text="Voted: cap pool at 200",
    )

    await _login(client, "ee_dc_owner")
    r = await _list_flows(client, pid)
    pkt = next(
        p for p in r.json()["packets"] if p["id"] == f"decision:{decision_id}"
    )
    ev = pkt["epistemic_event"]
    assert ev["kind"] == "decision"
    assert ev["status"] == "accepted_for_scope"
    sc = ev["accepted_scope"]
    assert sc is not None
    # scope_type=room because scope_stream_id is set.
    assert sc["scope_type"] == "room"
    assert sc["scope_id"] == scope_stream_id
    assert owner_id in sc["accepted_by_user_ids"]


@pytest.mark.asyncio
async def test_e4_kb_published_canonical_event_has_accepted_scope(api_env):
    """Canonical (published) KB rows ARE in projection because the
    upstream query filters in 'draft'/'pending-review'. So we verify
    archived-or-published flows by directly mutating after seeding —
    the projection at that point drops the row, demonstrating the
    invariant 'archived/superseded KB is not projected as canonical'."""
    from sqlalchemy import update
    from workgraph_persistence import KbItemRow

    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_kbpub_owner")
    member_id = await _register(client, "ee_kbpub_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    item_id = await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="Soon-to-publish"
    )
    await _login(client, "ee_kbpub_owner")
    # Pre: the draft packet exists.
    r = await _list_flows(client, pid, recipe="promote_to_memory")
    assert any(p["id"] == f"kb:{item_id}" for p in r.json()["packets"])

    # Flip status='published' directly.
    async with session_scope(maker) as session:
        await session.execute(
            update(KbItemRow)
            .where(KbItemRow.id == item_id)
            .values(status="published")
        )

    # Post: packet is gone — the projection's draft/pending-review
    # filter dropped it, so canonical KB is NOT projected as a flow
    # packet (lives elsewhere as the wiki / KB tree row).
    r = await _list_flows(client, pid, recipe="promote_to_memory")
    assert not any(p["id"] == f"kb:{item_id}" for p in r.json()["packets"])


@pytest.mark.asyncio
async def test_e4_archived_kb_is_not_projected_as_canonical(api_env):
    """Same shape as the published test but for archive — archived
    KB drops from projection, so consumers can't mistake an archived
    row for canonical."""
    from sqlalchemy import update
    from workgraph_persistence import KbItemRow

    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_kbarch_owner")
    member_id = await _register(client, "ee_kbarch_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    item_id = await _seed_kb_draft(
        maker, project_id=pid, owner_id=owner_id, title="Soon-to-archive"
    )

    async with session_scope(maker) as session:
        await session.execute(
            update(KbItemRow)
            .where(KbItemRow.id == item_id)
            .values(status="archived")
        )

    await _login(client, "ee_kbarch_owner")
    r = await _list_flows(client, pid, recipe="promote_to_memory")
    assert not any(p["id"] == f"kb:{item_id}" for p in r.json()["packets"])


@pytest.mark.asyncio
async def test_e4_accepted_for_scope_requires_accepted_scope(api_env):
    """Universal invariant: any packet with status='accepted_for_scope'
    has a non-None accepted_scope block. Verified across all packet
    kinds via the shape helper."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "ee_afs_owner")
    member_id = await _register(client, "ee_afs_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    # Seed a crystallized decision (project scope) — that gives us an
    # accepted_for_scope status to verify.
    await _seed_decision_row(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        custom_text="A canonical-ish decision",
    )

    await _login(client, "ee_afs_owner")
    r = await _list_flows(client, pid)
    for p in r.json()["packets"]:
        ev = p["epistemic_event"]
        if ev["status"] == "accepted_for_scope":
            assert ev["accepted_scope"] is not None, p["id"]


@pytest.mark.asyncio
async def test_e4_capability_projection_does_not_claim_trusted_from_self_declared(
    api_env,
):
    """Capability projection: a self-declared skill alone is NOT
    'trusted' (or 'accepted_for_scope' or 'validated'). It's
    'declared' / 'proposed' until evidence accumulates."""
    from workgraph_api.services import OrgCapabilityService
    from workgraph_persistence import UserRow

    _, maker, *_ = api_env
    pid = str(uuid.uuid4())
    uid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="cap honest"))
        session.add(
            UserRow(
                id=uid,
                username="ee_cap_dec",
                display_name="ee_cap_dec",
                password_hash="pw",
                password_salt="salt",
                profile={"declared_abilities": ["compliance"]},
            )
        )
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role="member"
        )

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    cap = next(c for c in out[0]["capabilities"] if c["skill_key"] == "compliance")
    assert cap["level"] == "declared"
    assert cap["epistemic"]["status"] == "proposed", cap
    assert cap["epistemic"]["accepted_scope"] is None


# ---- M5 — manual_room Membrane gate -----------------------------------


async def _invite_user_to_project(
    maker, project_id: str, user_id: str, role: str = "member"
) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )


@pytest.mark.asyncio
async def test_m5_owner_room_create_auto_merges(api_env):
    """Project owner creating a room goes straight through — no gate
    deferral, response carries the stream payload as before."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m5_om_owner")
    member_id = await _register(client, "m5_om_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "m5_om_owner")
    r = await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": "Owner room", "member_user_ids": [member_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("deferred") is not True
    assert body["stream"] is not None
    assert body["stream"]["type"] == "room"


@pytest.mark.asyncio
async def test_m5_non_owner_room_create_is_deferred(api_env):
    """Non-owner member creating a room gets `deferred=True`; no
    StreamRow exists yet; an IMSuggestion(membrane_review,
    candidate_kind=manual_room) is queued for owner approval."""
    from sqlalchemy import select
    from workgraph_persistence import StreamRow

    client, maker, *_ = api_env
    owner_id = await _register(client, "m5_nom_owner")
    member_id = await _register(client, "m5_nom_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "m5_nom_member")
    r = await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": "Member-proposed room", "member_user_ids": [owner_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deferred"] is True, body
    assert body["stream"] is None
    sug_id = body["suggestion_id"]
    assert sug_id is not None

    # No StreamRow with this name materialized yet.
    async with session_scope(maker) as session:
        rooms = list(
            (
                await session.execute(
                    select(StreamRow)
                    .where(StreamRow.project_id == pid)
                    .where(StreamRow.type == "room")
                    .where(StreamRow.name == "Member-proposed room")
                )
            )
            .scalars()
            .all()
        )
    assert rooms == [], "StreamRow must not exist before owner approval"

    # The pending packet is in /flows under the new recipe.
    await _login(client, "m5_nom_owner")
    r = await _list_flows(client, pid, recipe="manual_create_room")
    pkts = r.json()["packets"]
    assert len(pkts) == 1
    pkt = pkts[0]
    assert pkt["id"] == f"manual_room:{sug_id}"
    assert pkt["recipe_id"] == "manual_create_room"
    # Transition contract.
    tc = pkt["transition_contract"]
    assert tc["source_state"] == "room_proposed"
    assert tc["target_state"] == "canonical_room"
    assert tc["review_method"] == "membrane_review"
    assert owner_id in tc["authority_user_ids"]
    # Epistemic event.
    ev = pkt["epistemic_event"]
    assert ev["kind"] == "proposal"
    assert ev["status"] == "review_pending"
    assert ev["membrane_policy"] == "request_review"
    assert owner_id in ev["authority_required"]
    # next_actions[0] points at the review surface.
    assert pkt["next_actions"][0]["href"] == f"/projects/{pid}/detail/im"


@pytest.mark.asyncio
async def test_m5_owner_accept_materializes_room(api_env):
    """When the owner accepts the IMSuggestion, the StreamRow lands.
    Verifies the round-trip: non-owner proposal → owner accept →
    canonical room exists with the requested name + members."""
    from sqlalchemy import select
    from workgraph_persistence import StreamRow

    client, maker, *_ = api_env
    owner_id = await _register(client, "m5_acc_owner")
    member_id = await _register(client, "m5_acc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "m5_acc_member")
    r = await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": "Accept-test room", "member_user_ids": [owner_id]},
    )
    sug_id = r.json()["suggestion_id"]

    # Owner accepts.
    await _login(client, "m5_acc_owner")
    r = await client.post(f"/api/im_suggestions/{sug_id}/accept")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True

    # StreamRow now exists.
    async with session_scope(maker) as session:
        rooms = list(
            (
                await session.execute(
                    select(StreamRow)
                    .where(StreamRow.project_id == pid)
                    .where(StreamRow.type == "room")
                    .where(StreamRow.name == "Accept-test room")
                )
            )
            .scalars()
            .all()
        )
    assert len(rooms) == 1, "owner accept must materialize the StreamRow"

    # Pending packet is gone (suggestion resolved).
    r = await _list_flows(client, pid, recipe="manual_create_room")
    assert not any(
        p["id"] == f"manual_room:{sug_id}" for p in r.json()["packets"]
    )


@pytest.mark.asyncio
async def test_m5_dm_creation_unaffected(api_env):
    """Personal/private creates (DM streams) are NOT affected by the
    gate — the constraint only applies to shared-scope `room` creates."""
    client, maker, *_ = api_env
    await _register(client, "m5_dm_a")
    a_id = (await client.get("/api/auth/me")).json()["id"]
    await _register(client, "m5_dm_b")
    b_id = (await client.get("/api/auth/me")).json()["id"]
    await _login(client, "m5_dm_a")
    r = await client.post(
        "/api/streams/dm",
        json={"other_user_id": b_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # DM is materialized directly — no deferred flag, no suggestion.
    assert body.get("deferred") is not True


@pytest.mark.asyncio
async def test_m5_review_pending_packet_has_authority_required(api_env):
    """Universal Epistemic-Event invariant — review_pending implies
    non-empty authority_required. Re-checked specifically for the
    manual_room packet kind (caught here in case a future refactor
    drops the field)."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m5_auth_owner")
    member_id = await _register(client, "m5_auth_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m5_auth_member")
    await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": "Authority test", "member_user_ids": [owner_id]},
    )
    await _login(client, "m5_auth_owner")
    r = await _list_flows(client, pid, recipe="manual_create_room")
    pkt = r.json()["packets"][0]
    ev = pkt["epistemic_event"]
    assert ev["status"] == "review_pending"
    assert ev["authority_required"], ev


@pytest.mark.asyncio
async def test_m5_no_direct_stream_row_created_on_non_owner_post(api_env):
    """Negative invariant — no manual_room bypass remains. After a
    non-owner POST, the only artifacts are an IMSuggestionRow and a
    membrane-review system message; no StreamRow with the proposed
    name exists in the DB."""
    from sqlalchemy import select
    from workgraph_persistence import StreamRow, IMSuggestionRow

    client, maker, *_ = api_env
    owner_id = await _register(client, "m5_no_byp_owner")
    member_id = await _register(client, "m5_no_byp_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m5_no_byp_member")
    await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": "Bypass attempt", "member_user_ids": [owner_id]},
    )
    async with session_scope(maker) as session:
        rooms = list(
            (
                await session.execute(
                    select(StreamRow)
                    .where(StreamRow.project_id == pid)
                    .where(StreamRow.type == "room")
                    .where(StreamRow.name == "Bypass attempt")
                )
            )
            .scalars()
            .all()
        )
        sugs = list(
            (
                await session.execute(
                    select(IMSuggestionRow)
                    .where(IMSuggestionRow.project_id == pid)
                    .where(IMSuggestionRow.kind == "membrane_review")
                )
            )
            .scalars()
            .all()
        )
    assert rooms == []
    assert any(
        (s.proposal or {}).get("detail", {}).get("candidate_kind")
        == "manual_room"
        for s in sugs
    )


# ---- M5.1 — manual_skill_change Membrane gate -------------------------


@pytest.mark.asyncio
async def test_m51_owner_skill_change_auto_merges(api_env):
    """Owner editing skill_tags goes straight through; no deferral."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_sk_om_owner")
    member_id = await _register(client, "m51_sk_om_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_sk_om_owner")
    r = await client.patch(
        f"/api/projects/{pid}/members/{member_id}/skills",
        json={"skill_tags": ["backend", "qa"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("deferred") is not True
    assert sorted(body["skill_tags"]) == ["backend", "qa"]


@pytest.mark.asyncio
async def test_m51_non_owner_self_skill_change_is_deferred(api_env):
    """Non-owner editing their OWN skill_tags now defers — closes the
    gap that let any member silently mint role-level capability."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_sk_self_owner")
    member_id = await _register(client, "m51_sk_self_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_sk_self_member")
    r = await client.patch(
        f"/api/projects/{pid}/members/{member_id}/skills",
        json={"skill_tags": ["compliance"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deferred"] is True, body
    assert body["suggestion_id"] is not None
    assert body["skill_tags"] is None  # not yet applied

    # The pending packet shows up under recipe=manual_skill_change.
    await _login(client, "m51_sk_self_owner")
    r = await _list_flows(client, pid, recipe="manual_skill_change")
    pkts = r.json()["packets"]
    assert len(pkts) == 1
    pkt = pkts[0]
    assert pkt["id"] == f"manual_skill_change:{body['suggestion_id']}"
    tc = pkt["transition_contract"]
    assert tc["source_state"] == "capability_claim_proposed"
    assert tc["target_state"] == "project_role_capability_accepted"
    assert tc["review_method"] == "membrane_review"
    assert owner_id in tc["authority_user_ids"]
    ev = pkt["epistemic_event"]
    assert ev["kind"] == "capability_claim"
    assert ev["status"] == "review_pending"
    assert ev["membrane_policy"] == "request_review"
    assert ev["accepted_scope"] is None
    assert owner_id in ev["authority_required"]


@pytest.mark.asyncio
async def test_m51_non_owner_cross_skill_change_still_403s(api_env):
    """Cross-edit by a non-owner stays a hard 403; the gate is for
    self-edit deferral only, not bypass of the cross-member ACL."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_sk_x_owner")
    a_id = await _register(client, "m51_sk_x_a")
    b_id = await _register(client, "m51_sk_x_b")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=a_id
    )
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=b_id, role="member"
        )
    await _login(client, "m51_sk_x_a")
    r = await client.patch(
        f"/api/projects/{pid}/members/{b_id}/skills",
        json={"skill_tags": ["backend"]},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_m51_skill_change_owner_accept_applies(api_env):
    """Owner accepts the deferred manual_skill_change suggestion;
    the member's skill_tags actually update on the ProjectMember row."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_sk_acc_owner")
    member_id = await _register(client, "m51_sk_acc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_sk_acc_member")
    r = await client.patch(
        f"/api/projects/{pid}/members/{member_id}/skills",
        json={"skill_tags": ["frontend"]},
    )
    sug_id = r.json()["suggestion_id"]

    await _login(client, "m51_sk_acc_owner")
    r = await client.post(f"/api/im_suggestions/{sug_id}/accept")
    assert r.status_code == 200, r.text

    async with session_scope(maker) as session:
        rows = await ProjectMemberRepository(session).list_for_project(pid)
    target = next(m for m in rows if m.user_id == member_id)
    assert sorted(target.skill_tags or []) == ["frontend"]


# ---- M5.1 — manual_invite Membrane gate -------------------------------


@pytest.mark.asyncio
async def test_m51_owner_invite_auto_merges(api_env):
    """Owner-issued invite goes straight through to add_member."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_inv_om_owner")
    invitee_id = await _register(client, "m51_inv_om_target")
    member_id = await _register(client, "m51_inv_om_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_inv_om_owner")
    r = await client.post(
        f"/api/projects/{pid}/invite",
        json={"username": "m51_inv_om_target"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body.get("deferred") is not True
    assert body["user_id"] == invitee_id


@pytest.mark.asyncio
async def test_m51_non_owner_invite_is_deferred(api_env):
    """Non-owner invite stages an IMSuggestion(manual_invite); no
    ProjectMember row appears for the proposed username yet."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_inv_def_owner")
    invitee_id = await _register(client, "m51_inv_def_target")
    member_id = await _register(client, "m51_inv_def_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_inv_def_member")
    r = await client.post(
        f"/api/projects/{pid}/invite",
        json={"username": "m51_inv_def_target"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["deferred"] is True, body
    sug_id = body["suggestion_id"]
    assert sug_id is not None

    # Invitee NOT yet in member list.
    async with session_scope(maker) as session:
        rows = await ProjectMemberRepository(session).list_for_project(pid)
    assert all(m.user_id != invitee_id for m in rows), (
        "invitee must not land before owner accept"
    )

    # Pending flow packet under recipe=manual_invite.
    await _login(client, "m51_inv_def_owner")
    r = await _list_flows(client, pid, recipe="manual_invite")
    pkts = r.json()["packets"]
    assert len(pkts) == 1
    pkt = pkts[0]
    assert pkt["id"] == f"manual_invite:{sug_id}"
    tc = pkt["transition_contract"]
    assert tc["source_state"] == "member_invite_proposed"
    assert tc["target_state"] == "project_member_accepted"
    assert tc["review_method"] == "membrane_review"
    assert owner_id in tc["authority_user_ids"]
    ev = pkt["epistemic_event"]
    assert ev["status"] == "review_pending"
    assert ev["membrane_policy"] == "request_review"


@pytest.mark.asyncio
async def test_m51_invite_owner_accept_applies(api_env):
    """Owner accepts the deferred manual_invite; the invitee shows up
    in the project member list."""
    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_inv_acc_owner")
    invitee_id = await _register(client, "m51_inv_acc_target")
    member_id = await _register(client, "m51_inv_acc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "m51_inv_acc_member")
    r = await client.post(
        f"/api/projects/{pid}/invite",
        json={"username": "m51_inv_acc_target"},
    )
    sug_id = r.json()["suggestion_id"]

    await _login(client, "m51_inv_acc_owner")
    r = await client.post(f"/api/im_suggestions/{sug_id}/accept")
    assert r.status_code == 200, r.text

    async with session_scope(maker) as session:
        rows = await ProjectMemberRepository(session).list_for_project(pid)
    assert any(m.user_id == invitee_id for m in rows)


# ---- M5.1 Lane B — decision warnings + supersedes persistence --------


@pytest.mark.asyncio
async def test_m51_decision_packet_surfaces_persisted_warnings(api_env):
    """A crystallized DecisionRow whose apply_detail carries
    membrane_warnings + supersedes shows them in the flow packet's
    epistemic_event evidence + supersedes blocks."""
    from workgraph_persistence import DecisionRepository

    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_dec_owner")
    member_id = await _register(client, "m51_dec_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        prior = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=owner_id,
            option_index=None,
            custom_text="ship without analytics",
            rationale="speed > telemetry for v0",
            apply_actions=[],
            apply_outcome="advisory",
        )
        prior_id = prior.id
        # Crystallized decision with warnings + supersedes already
        # persisted into apply_detail (as Lane B's IMService write
        # path would produce).
        await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=owner_id,
            option_index=None,
            custom_text="add analytics for v1",
            rationale="we now need retention numbers",
            apply_actions=[{"kind": "advisory"}],
            source_suggestion_id=None,
            apply_outcome="ok",
            apply_detail={
                "applied": {"graph_touched": False},
                "membrane_warnings": [
                    "This decision was crystallized without a recorded "
                    "rationale.",
                    "A prior decision in this project has the same "
                    "title-equivalent.",
                ],
                "supersedes": prior_id,
            },
        )

    await _login(client, "m51_dec_owner")
    r = await _list_flows(client, pid, recipe="crystallize_decision")
    pkts = r.json()["packets"]
    pkt = next(p for p in pkts if "add analytics" in (p["title"] or ""))
    ev = pkt["epistemic_event"]

    # Warnings rendered as `membrane_warning` evidence_refs.
    warning_refs = [
        e for e in ev["evidence_refs"]
        if e.get("kind") == "membrane_warning"
    ]
    assert len(warning_refs) == 2

    # Supersedes ref carried.
    sup = ev["supersedes"]
    assert len(sup) == 1
    assert sup[0]["kind"] == "decision"
    assert sup[0]["id"] == prior_id


@pytest.mark.asyncio
async def test_m51_decision_packet_no_warnings_keeps_clean_shape(api_env):
    """Decisions whose apply_detail has no membrane_warnings /
    supersedes still produce a valid packet — fields default to []."""
    from workgraph_persistence import DecisionRepository

    client, maker, *_ = api_env
    owner_id = await _register(client, "m51_dec_clean_owner")
    member_id = await _register(client, "m51_dec_clean_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    async with session_scope(maker) as session:
        await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=owner_id,
            option_index=None,
            custom_text="no-warning decision",
            rationale="straightforward",
            apply_actions=[{"kind": "advisory"}],
            source_suggestion_id=None,
            apply_outcome="advisory",
            apply_detail={"applied": {"graph_touched": False}},
        )
    await _login(client, "m51_dec_clean_owner")
    r = await _list_flows(client, pid, recipe="crystallize_decision")
    pkt = r.json()["packets"][0]
    ev = pkt["epistemic_event"]
    assert all(
        e.get("kind") != "membrane_warning"
        for e in ev["evidence_refs"]
    )
    assert ev["supersedes"] == []
