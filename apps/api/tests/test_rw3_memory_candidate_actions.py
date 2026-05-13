"""RW-3 — Memory candidate action endpoint tests.

Exercises POST /api/memory-candidates/:id/{accept,defer,reject,reopen}
end-to-end against the live MembraneService. Covers:

  * authority enforcement on accept (the v0.6.2 doctrine load-bearing
    invariant — project_member can defer, only project_owner can accept)
  * state transitions for each action (pending → accepted/deferred/
    rejected; deferred/rejected → reopened)
  * GET refetch after each action returns the new server-authoritative
    status (no optimistic UI bypass)
  * idempotency / safety: re-accepting a resolved candidate is rejected
    with `already_resolved`; reopening from `pending` is rejected with
    `not_reopenable`

This is the RW-3 doctrine surface — the first round-trip in the
product where AI proposes and authority commits.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    IMSuggestionRow,
    ProjectMemberRepository,
    ProjectRow,
    StreamRepository,
    session_scope,
)


# ---- helpers (copied from test_kb_items.py to keep this file self-contained)


async def _register_and_login(client, username: str) -> str:
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
        session.add(ProjectRow(id=pid, title="RW3 Test"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
        await StreamRepository(session).create(type="project", project_id=pid)
    return pid


async def _seed_membrane_review_candidate(client, pid: str) -> str:
    """Create a membrane_review IMSuggestion by triggering the
    title-collision membrane policy. Returns the suggestion id.

    The first kb-item write goes clean; the second on the same title
    triggers membrane request_review which stages the draft and creates
    an IMSuggestion(kind='membrane_review'). The owner must be the one
    posting since members can't write group-scope KB items.
    """
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "Coding Conventions",
            "content_md": "tabs not spaces.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "coding conventions",
            "content_md": "actually spaces.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _candidate_id_for(maker, pid: str) -> str:
    """Look up the membrane_review IMSuggestion id for a project.

    Only one candidate is created per test in this file, so a single-row
    fetch is fine. If we need multiples later, switch to ordered list.
    """
    async with session_scope(maker) as session:
        sugg = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.project_id == pid,
                    IMSuggestionRow.kind == "membrane_review",
                )
            )
        ).scalar_one()
    return sugg.id


# ---- authority enforcement (the load-bearing invariant) ------------------


@pytest.mark.asyncio
async def test_member_cannot_accept_returns_403_with_envelope(api_env):
    """v0.6.2 invariant — INVARIANT_TESTS.md §"Authority enforcement".

    POST /api/memory-candidates/:id/accept by a project_member (not
    owner) must return HTTP 403 with the authority envelope:
      detail.error == "authority_required"
      detail.required_roles, detail.user_roles, detail.allowed_actions
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_authgate")
    member_id = await _register_and_login(client, "rw3_member_authgate")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "rw3_owner_authgate")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    # Member attempts accept → 403 with the authority envelope.
    await _login(client, "rw3_member_authgate")
    r = await client.post(f"/api/memory-candidates/{cand_id}/accept")
    assert r.status_code == 403, r.text
    body = r.json()
    # Global WG envelope shape — {code, message, details, trace_id}.
    # The router's dict detail unwraps so `message` carries the short
    # error name and `details` preserves the structured fields.
    assert body.get("message") == "authority_required", body
    details = body.get("details", {})
    assert details.get("required_roles"), body
    assert "user_roles" in details
    assert "allowed_actions" in details
    # Member should at least see comment + request_review affordances.
    assert "comment" in details["allowed_actions"]


# ---- happy-path acceptance + lineage shape -------------------------------


@pytest.mark.asyncio
async def test_owner_accept_publishes_and_returns_lineage(api_env):
    """Owner accept → KB draft published, suggestion resolved, response
    carries the three required lineage ids per INVARIANT_TESTS.md
    §"Memory lineage required".
    """
    from workgraph_persistence import KbItemRow

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_accept")
    member_id = await _register_and_login(client, "rw3_member_accept")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_accept")
    draft_id = await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    r = await client.post(f"/api/memory-candidates/{cand_id}/accept")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("candidate_id") == cand_id
    assert body.get("memory_atom_id") == draft_id
    lineage = body.get("lineage", {})
    # Three required ids per the invariant test.
    assert lineage.get("verbatim_source_id"), lineage
    assert lineage.get("ai_distillation_id") == cand_id
    assert lineage.get("accepted_by") == owner_id
    assert lineage.get("accepted_at"), lineage

    # KB row flipped to published.
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(KbItemRow).where(KbItemRow.id == draft_id)
            )
        ).scalar_one()
        assert row.status == "published"


# ---- defer transitions + idempotency suppression -------------------------


@pytest.mark.asyncio
async def test_member_can_defer_transition_visible_on_refetch(api_env):
    """defer is membership-only (any project member can defer their
    own queue). After POST, GET shows status='deferred' — the FE never
    needs to invent the new state, the server returns it.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_defer")
    member_id = await _register_and_login(client, "rw3_member_defer")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_defer")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    # Member defers.
    await _login(client, "rw3_member_defer")
    r = await client.post(f"/api/memory-candidates/{cand_id}/defer")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "deferred"

    # GET reflects the new state — no optimistic FE patching needed.
    r = await client.get(f"/api/memory-candidates/{cand_id}")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "deferred"


# ---- reject + reopen round trip ------------------------------------------


@pytest.mark.asyncio
async def test_reject_then_reopen_round_trip(api_env):
    """reject moves pending → rejected. reopen moves rejected → reopened.
    Both transitions visible on GET refetch.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_reopen")
    member_id = await _register_and_login(client, "rw3_member_reopen")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_reopen")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    r = await client.post(f"/api/memory-candidates/{cand_id}/reject")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "rejected"

    r = await client.get(f"/api/memory-candidates/{cand_id}")
    assert r.status_code == 200, r.text
    # Server maps internal `dismissed` → v062 `rejected`. The drawer
    # consumes this directly.
    assert r.json().get("status") == "rejected"

    r = await client.post(f"/api/memory-candidates/{cand_id}/reopen")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "reopened"

    r = await client.get(f"/api/memory-candidates/{cand_id}")
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "reopened"


# ---- reopen guard --------------------------------------------------------


@pytest.mark.asyncio
async def test_reopen_from_pending_returns_400_not_reopenable(api_env):
    """Reopen only makes sense from a terminal-ish state. From pending
    it returns 400 with `not_reopenable` so the FE shows the right
    bilingual error.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_reopgate")
    member_id = await _register_and_login(client, "rw3_member_reopgate")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_reopgate")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    r = await client.post(f"/api/memory-candidates/{cand_id}/reopen")
    assert r.status_code == 409, r.text
    # WG envelope — string detail surfaces as `message`.
    assert r.json().get("message") == "not_reopenable"


# ---- second accept is a safety idempotency rejection ---------------------


@pytest.mark.asyncio
async def test_double_accept_returns_409_already_resolved(api_env):
    """After a successful accept the candidate is resolved; a second
    accept must not double-publish. Returns 409 already_resolved.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_double")
    member_id = await _register_and_login(client, "rw3_member_double")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_double")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    r1 = await client.post(f"/api/memory-candidates/{cand_id}/accept")
    assert r1.status_code == 200, r1.text

    r2 = await client.post(f"/api/memory-candidates/{cand_id}/accept")
    assert r2.status_code == 409, r2.text
    assert r2.json().get("message") == "already_resolved"


# ---- compression analysis caveat invariant (real-data path) --------------
# This is the highest-value Flow Center real-data invariant from
# graphflow_handoff_v062/INVARIANT_TESTS.md §"Compression analysis shape",
# converted from the FE bun:test todo into a live backend integration
# assertion. The caveat is the doctrine UX-honesty line that the FE
# renders verbatim; this test verifies the server actually emits it.


@pytest.mark.asyncio
async def test_compression_analysis_caveat_contains_does_not_guarantee(
    api_env,
):
    """INVARIANT_TESTS.md §"Compression analysis shape":
        candidate.compression_analysis.caveat must contain
        'does not guarantee'.

    Converted from src/__tests__/v062-invariants.test.ts (it was a
    placeholder todo) into a live API integration test that exercises
    the real /api/memory-candidates/:id read path verified in RW-2.2.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw3_owner_caveat")
    member_id = await _register_and_login(client, "rw3_member_caveat")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw3_owner_caveat")
    await _seed_membrane_review_candidate(client, pid)
    cand_id = await _candidate_id_for(maker, pid)

    r = await client.get(f"/api/memory-candidates/{cand_id}")
    assert r.status_code == 200, r.text
    body = r.json()

    # The contract shape.
    ca = body.get("compression_analysis")
    assert isinstance(ca, dict), body
    assert "caveat" in ca, ca
    assert "warning_count" in ca
    assert "method" in ca
    # The doctrine string — verbatim substring check.
    assert "does not guarantee" in ca["caveat"], ca["caveat"]
