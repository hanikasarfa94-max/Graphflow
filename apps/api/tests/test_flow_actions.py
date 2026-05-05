"""Slice C.1 — Source-side flow action tests.

Covers the contract locked in `docs/flow-actions-c1-design.md`:
  - POST /api/projects/{pid}/flows/{flow_id}/actions
  - Four source-side actions: accept / counter_back / escalate_to_gate /
    custom_followup
  - Seven error codes mapped to specific HTTP statuses
  - Projection lifecycle update (§11): replied → packet active +
    current_target = [source] + four source-side affordances on
    next_actions

End-to-end through the HTTP surface so router wiring + Pydantic
discriminator + service dispatch + RoutingService.source_* + repo
conditional update all get exercised together.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    RoutedSignalRow,
    backfill_streams_from_projects,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


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


async def _mk_project(maker, *, owner_id: str, member_id: str) -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Flow Action Test"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    await backfill_streams_from_projects(maker)
    return pid


async def _dispatch_routed_signal(
    client, *, pid: str, target_id: str, framing: str = "Test framing"
) -> str:
    """Caller is already logged in as the source. Dispatches a routed
    signal and returns its id. The new signal is in `pending` state.
    """
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": target_id,
            "project_id": pid,
            "framing": framing,
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["signal"]["id"]


async def _target_replies(client, *, signal_id: str) -> None:
    """Caller is already logged in as the target. Picks the 'y' option."""
    r = await client.post(
        f"/api/routing/{signal_id}/reply",
        json={"option_id": "y"},
    )
    assert r.status_code == 200, r.text


async def _setup_replied_signal(client, maker) -> tuple[str, str, str, str]:
    """Common setup: register source + target, mk project, dispatch a
    signal, target replies. Returns (pid, source_id, target_id, signal_id).
    Caller is logged in as the source on return.
    """
    source_id = await _register(client, "fa_src_" + uuid.uuid4().hex[:6])
    target_id = await _register(client, "fa_tgt_" + uuid.uuid4().hex[:6])
    pid = await _mk_project(maker, owner_id=source_id, member_id=target_id)
    await _login(client, _username_of(client, source_id))  # already logged in as target after register
    # Easier: we registered target last → cookie is target's. Re-login
    # as source cleanly.
    # The fixture's _register is convenient but doesn't track names; we
    # track them ourselves via the username we passed.
    raise RuntimeError("use the explicit setup below — this helper is unfinished")


def _username_of(client, user_id: str) -> str:  # pragma: no cover
    raise RuntimeError("not used")


# ---- happy paths --------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_happy_path(api_env):
    client, maker, *_ = api_env
    src_user = "fa_acc_src"
    tgt_user = "fa_acc_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept", "note": "looks good"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["flow_id"] == f"route:{sid}"
    assert body["status"] == "completed"
    assert body["spawned_flow_id"] is None

    # Underlying signal flipped to 'accepted'.
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == sid)
            )
        ).scalar_one()
        assert row.status == "accepted"
        # Note appended to reply_json.
        notes = (row.reply_json or {}).get("source_action_notes") or []
        assert len(notes) == 1
        assert notes[0]["action"] == "accept"
        assert notes[0]["note"] == "looks good"


@pytest.mark.asyncio
async def test_counter_back_happy_path(api_env):
    client, maker, *_ = api_env
    src_user = "fa_ctr_src"
    tgt_user = "fa_ctr_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={
            "action": "counter_back",
            "framing": "Push back: what about cost?",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["spawned_flow_id"] is not None
    assert body["spawned_flow_id"].startswith("route:")
    spawned_sid = body["spawned_flow_id"].split(":", 1)[1]

    # Original signal flipped to 'countered'; spawned signal exists in
    # 'pending' (it's a fresh dispatch awaiting the same target's reply).
    async with session_scope(maker) as session:
        original = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == sid)
            )
        ).scalar_one()
        assert original.status == "countered"
        spawned = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == spawned_sid)
            )
        ).scalar_one()
        assert spawned.status == "pending"
        assert spawned.framing == "Push back: what about cost?"
        assert spawned.source_user_id == src_id
        assert spawned.target_user_id == tgt_id


@pytest.mark.asyncio
async def test_escalate_to_gate_happy_path(api_env):
    client, maker, *_ = api_env
    src_user = "fa_esc_src"
    tgt_user = "fa_esc_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "escalate_to_gate"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["spawned_flow_id"] is None

    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == sid)
            )
        ).scalar_one()
        assert row.status == "escalated"


@pytest.mark.asyncio
async def test_custom_followup_happy_path(api_env):
    """Per memo §4.4: original signal untouched (stays 'replied'); a
    new signal is dispatched. Response.status = 'completed' for the
    original packet (replied projects to completed); spawned_flow_id
    points to the new active packet."""
    client, maker, *_ = api_env
    src_user = "fa_fup_src"
    tgt_user = "fa_fup_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={
            "action": "custom_followup",
            "framing": "Thanks. One more — what about timeline?",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["spawned_flow_id"] is not None

    async with session_scope(maker) as session:
        original = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == sid)
            )
        ).scalar_one()
        # CRITICAL: original is UNTOUCHED. Status stays 'replied'.
        assert original.status == "replied"
        # Note still appended (audit trail) even though status didn't
        # change.
        notes = (original.reply_json or {}).get("source_action_notes") or []
        assert any(n["action"] == "custom_followup" for n in notes)


# ---- error paths --------------------------------------------------------


@pytest.mark.asyncio
async def test_non_source_caller_gets_403(api_env):
    """Target tries to call the source-side action endpoint."""
    client, maker, *_ = api_env
    src_user = "fa_nsrc_src"
    tgt_user = "fa_nsrc_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    # Target tries to accept (still logged in as target).

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 403, r.text
    assert "not_source_user" in r.json()["message"]


@pytest.mark.asyncio
async def test_pending_signal_returns_409(api_env):
    """Signal still pending → source can't act yet."""
    client, maker, *_ = api_env
    src_user = "fa_pend_src"
    tgt_user = "fa_pend_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    # Source tries to accept BEFORE target replies.
    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 409, r.text
    assert "not_ready_for_source_action" in r.json()["message"]


@pytest.mark.asyncio
async def test_already_accepted_returns_409(api_env):
    """Per memo §5.1: source_accept is stricter than legacy accept().
    Already-accepted should return 409, not idempotent ok."""
    client, maker, *_ = api_env
    src_user = "fa_dup_src"
    tgt_user = "fa_dup_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    # First accept succeeds.
    r1 = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )
    assert r1.status_code == 200, r1.text
    # Second accept on the same signal — strict, not idempotent.
    r2 = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "accept"},
    )
    assert r2.status_code == 409, r2.text
    assert "not_ready_for_source_action" in r2.json()["message"]


@pytest.mark.asyncio
async def test_kb_flow_id_returns_unsupported_flow_recipe(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fa_kbrecipe_owner")
    member_id = await _register(client, "fa_kbrecipe_member")
    pid = await _mk_project(maker, owner_id=owner_id, member_id=member_id)
    await _login(client, "fa_kbrecipe_owner")

    r = await client.post(
        f"/api/projects/{pid}/flows/kb:some-id/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 400, r.text
    assert "unsupported_flow_recipe" in r.json()["message"]


@pytest.mark.asyncio
async def test_handoff_flow_id_returns_unsupported_flow_recipe(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fa_horecipe_owner")
    member_id = await _register(client, "fa_horecipe_member")
    pid = await _mk_project(maker, owner_id=owner_id, member_id=member_id)
    await _login(client, "fa_horecipe_owner")

    r = await client.post(
        f"/api/projects/{pid}/flows/handoff:some-id/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 400, r.text
    assert "unsupported_flow_recipe" in r.json()["message"]


@pytest.mark.asyncio
async def test_unknown_route_flow_id_returns_404(api_env):
    client, maker, *_ = api_env
    owner_id = await _register(client, "fa_404_owner")
    member_id = await _register(client, "fa_404_member")
    pid = await _mk_project(maker, owner_id=owner_id, member_id=member_id)
    await _login(client, "fa_404_owner")

    r = await client.post(
        f"/api/projects/{pid}/flows/route:nonexistent-id/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 404, r.text
    assert "flow_not_found" in r.json()["message"]


@pytest.mark.asyncio
async def test_counter_back_missing_framing_returns_422(api_env):
    """Pydantic discriminated union catches this at parse time."""
    client, maker, *_ = api_env
    src_user = "fa_422_src"
    tgt_user = "fa_422_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "counter_back"},  # missing framing
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_unknown_action_returns_422(api_env):
    """Pydantic discriminator rejects unknown action literal."""
    client, maker, *_ = api_env
    src_id = await _register(client, "fa_unk_src")
    tgt_id = await _register(client, "fa_unk_tgt")
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)
    await _login(client, "fa_unk_src")
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, "fa_unk_tgt")
    await _target_replies(client, signal_id=sid)
    await _login(client, "fa_unk_src")

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "delegate_up"},  # not in C.1
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_non_member_returns_403(api_env):
    """Membership gate fires before any other validation."""
    client, maker, *_ = api_env
    src_user = "fa_nmem_src"
    tgt_user = "fa_nmem_tgt"
    outsider_user = "fa_nmem_outsider"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    await _register(client, outsider_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)
    # Outsider is logged in (last register) and isn't a member.

    r = await client.post(
        f"/api/projects/{pid}/flows/route:any-id/actions",
        json={"action": "accept"},
    )
    assert r.status_code == 403, r.text
    # Membership gate uses the project's convention (string detail).
    assert "not_a_project_member" in r.json()["message"]


# ---- projection lifecycle update (memo §11) -----------------------------


@pytest.mark.asyncio
async def test_replied_signal_projects_as_active_with_source_blocking(api_env):
    """C.1 §11: pre-C.1 the projection mapped 'replied' → packet status
    'completed'. Now 'replied' is an ACTIVE state with the SOURCE as
    current_target. Source's bucket=needs_me must include it."""
    client, maker, *_ = api_env
    src_user = "fa_proj_src"
    tgt_user = "fa_proj_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)

    # Source POV — packet should be ACTIVE with source as current target.
    await _login(client, src_user)
    r = await client.get(f"/api/projects/{pid}/flows")
    assert r.status_code == 200, r.text
    packets = [p for p in r.json()["packets"] if p["id"] == f"route:{sid}"]
    assert len(packets) == 1
    p = packets[0]
    assert p["status"] == "active"
    assert p["stage"] == "awaiting_source"
    assert p["current_target_user_ids"] == [src_id]

    # next_actions should carry all four C.1 source-side affordances.
    action_kinds = sorted(a["kind"] for a in p["next_actions"])
    assert action_kinds == [
        "accept",
        "counter_back",
        "custom_followup",
        "escalate_to_gate",
    ]

    # bucket=needs_me from source POV → packet shows up.
    r2 = await client.get(f"/api/projects/{pid}/flows?bucket=needs_me")
    assert r2.status_code == 200
    needs = [p for p in r2.json()["packets"] if p["id"] == f"route:{sid}"]
    assert len(needs) == 1


# ---- compensating rollback (memo §4.2 / §8.2) ---------------------------


@pytest.mark.asyncio
async def test_counter_back_compensates_on_lost_race(api_env, monkeypatch):
    """If two source-side actions race and the conditional update on
    the original loses, the spawned signal is deleted so the caller
    doesn't see a phantom counter packet."""
    from workgraph_persistence import RoutedSignalRepository

    client, maker, *_ = api_env
    src_user = "fa_race_src"
    tgt_user = "fa_race_tgt"
    src_id = await _register(client, src_user)
    tgt_id = await _register(client, tgt_user)
    pid = await _mk_project(maker, owner_id=src_id, member_id=tgt_id)

    await _login(client, src_user)
    sid = await _dispatch_routed_signal(client, pid=pid, target_id=tgt_id)
    await _login(client, tgt_user)
    await _target_replies(client, signal_id=sid)
    await _login(client, src_user)

    # Force the conditional update to return False — simulates the
    # losing side of a concurrent race. update_status_if returns
    # rowcount==1 normally; we patch it to always return False.
    original_method = RoutedSignalRepository.update_status_if

    async def force_false(self, signal_id, *, expect, set_to):
        # Still execute the underlying UPDATE so we don't desync, but
        # report False so the compensating rollback path fires.
        await original_method(self, signal_id, expect=expect, set_to=set_to)
        return False

    monkeypatch.setattr(
        RoutedSignalRepository, "update_status_if", force_false
    )

    r = await client.post(
        f"/api/projects/{pid}/flows/route:{sid}/actions",
        json={"action": "counter_back", "framing": "x"},
    )
    assert r.status_code == 409, r.text
    msg = r.json()["message"]
    assert "not_ready_for_source_action" in msg

    # Compensating rollback: the spawned signal must NOT exist. Only
    # the original signal should remain in routed_signals for this
    # project.
    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(RoutedSignalRow).where(
                        RoutedSignalRow.project_id == pid
                    )
                )
            )
            .scalars()
            .all()
        )
        # Only the original — the spawned counter was deleted as
        # compensation. (Note: the patched update DID run, so the
        # original may have flipped to 'countered' first. The relevant
        # invariant for the user-visible state is "no orphan spawned
        # packet" — which is what we assert.)
        assert len(rows) == 1
        assert rows[0].id == sid
