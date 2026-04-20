"""Sprint 3a — cross-project org-graph endpoint tests.

Covers the four promised cases:

  1. Single-project user → empty peers, empty edges. The endpoint must
     return a well-formed payload even when the user has no other
     projects (this is the demo user's default state).
  2. Two-project user with shared membership → peers populated, edge
     count/weight/shared_users correct, per-peer risk + member counts
     reflect the DB.
  3. Center project is excluded from `peers` even when it's obviously
     still a valid project of the caller.
  4. Non-member on `{project_id}` → 403. The landing-page zoom-out
     promise is about *my* org, never a stranger's.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    RiskRow,
    session_scope,
)


async def _register(client, username: str) -> str:
    """Register a user via the auth router, leaving a session cookie
    on the shared AsyncClient. Password length floor is mirrored from
    the auth config so this helper stays future-proof if it bumps.
    """
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": f"{username}-pw-1!"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client, username: str) -> None:
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": f"{username}-pw-1!"},
    )
    assert r.status_code == 200, r.text


async def _logout(client) -> None:
    # Clear the session cookie locally so subsequent calls hit the 401
    # path on require_user. The server-side session row survives;
    # that's fine, we just test the unauth'd client view.
    client.cookies.clear()


async def _make_bare_project(maker, title: str) -> str:
    """Create a ProjectRow without going through /intake/message.

    The full intake path is heavier than we need for these tests —
    it kicks off a requirement parse that produces graph entities +
    a project stream, which bloats the arrange phase. A bare row plus
    explicit ProjectMemberRow writes is enough to exercise the
    membership-based edge logic.
    """
    async with session_scope(maker) as session:
        project = ProjectRow(id=str(uuid.uuid4()), title=title)
        session.add(project)
        await session.flush()
        return project.id


async def _add_member(maker, project_id: str, user_id: str, role: str = "member") -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )


async def _add_risk(maker, project_id: str, *, status: str) -> str:
    """Insert a RiskRow on the given project with the given status.

    The risk needs a requirement_id FK, so we grab an arbitrary
    requirement on the project — or mint a bare one if none exists.
    Tests here never exercise the requirement content, so the dummy
    row is fine.

    sort_order is UNIQUE per (requirement_id, sort_order) so multiple
    risks on the same requirement need bumped sort_orders; we pick
    max+1 to stay legal across repeated calls.
    """
    from sqlalchemy import func as _func

    from workgraph_persistence import RequirementRepository, RequirementRow

    async with session_scope(maker) as session:
        req = await RequirementRepository(session).latest_for_project(project_id)
        if req is None:
            req = RequirementRow(
                id=str(uuid.uuid4()),
                project_id=project_id,
                version=1,
                raw_text="(test stub)",
            )
            session.add(req)
            await session.flush()
        next_sort = (
            await session.execute(
                select(_func.coalesce(_func.max(RiskRow.sort_order), -1)).where(
                    RiskRow.requirement_id == req.id
                )
            )
        ).scalar_one() + 1
        risk = RiskRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            requirement_id=req.id,
            title="stub risk",
            content="",
            severity="medium",
            status=status,
            sort_order=next_sort,
        )
        session.add(risk)
        await session.flush()
        return risk.id


# ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_graph_empty_for_single_project_user(api_env):
    """A user whose only project IS the center project sees an empty
    org graph. This is the baseline solo state — the landing promise
    is that even in this case we render a readable "you are here"
    node with no floating peers.
    """
    client, maker, *_ = api_env
    user_id = await _register(client, "solo")

    project_id = await _make_bare_project(maker, "Solo project")
    await _add_member(maker, project_id, user_id, role="owner")

    r = await client.get(f"/api/projects/{project_id}/org-graph")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["center"]["id"] == project_id
    assert body["center"]["title"] == "Solo project"
    assert body["peers"] == []
    assert body["edges"] == []


@pytest.mark.asyncio
async def test_org_graph_two_projects_peer_and_edge_populated(api_env):
    """User belongs to center + 1 peer, and the two share a member
    (the caller themselves). The payload must show exactly one peer
    and one `shared_member` edge pointing at that peer, with the
    caller's user_id listed in shared_users.
    """
    client, maker, *_ = api_env
    user_id = await _register(client, "twoprojects")

    center_id = await _make_bare_project(maker, "Center")
    peer_id = await _make_bare_project(maker, "Peer A")
    await _add_member(maker, center_id, user_id, role="owner")
    await _add_member(maker, peer_id, user_id, role="member")

    # One open risk on the peer should show up in open_risks; one
    # resolved risk should NOT count.
    await _add_risk(maker, peer_id, status="open")
    await _add_risk(maker, peer_id, status="resolved")

    r = await client.get(f"/api/projects/{center_id}/org-graph")
    assert r.status_code == 200, r.text
    body = r.json()

    # Peer slot
    assert len(body["peers"]) == 1
    peer = body["peers"][0]
    assert peer["id"] == peer_id
    assert peer["title"] == "Peer A"
    assert peer["role"] == "member"
    # Only the caller is on each project, so the member count is 1
    assert peer["member_count"] == 1
    assert peer["open_risks"] == 1

    # Edge slot — exactly one shared_member edge linking center → peer,
    # with the caller's id in shared_users and weight == 1.
    assert len(body["edges"]) == 1
    edge = body["edges"][0]
    assert edge["kind"] == "shared_member"
    assert edge["from_project_id"] == center_id
    assert edge["to_project_id"] == peer_id
    assert edge["weight"] == 1
    assert edge["shared_users"] == [user_id]


@pytest.mark.asyncio
async def test_org_graph_center_project_excluded_from_peers(api_env):
    """Even when the user is in three projects, the center project
    never appears in `peers`. It belongs in `center`. Regression
    guard for the obvious off-by-one.
    """
    client, maker, *_ = api_env
    user_id = await _register(client, "threeprojects")

    center_id = await _make_bare_project(maker, "Center")
    peer_a = await _make_bare_project(maker, "Peer A")
    peer_b = await _make_bare_project(maker, "Peer B")
    for pid in (center_id, peer_a, peer_b):
        await _add_member(maker, pid, user_id, role="member")

    r = await client.get(f"/api/projects/{center_id}/org-graph")
    assert r.status_code == 200, r.text
    body = r.json()

    peer_ids = {p["id"] for p in body["peers"]}
    assert center_id not in peer_ids
    assert peer_ids == {peer_a, peer_b}
    # Two peers → two edges from center, one per peer
    assert len(body["edges"]) == 2
    assert {e["to_project_id"] for e in body["edges"]} == {peer_a, peer_b}


@pytest.mark.asyncio
async def test_org_graph_non_member_gets_403(api_env):
    """Caller is logged in but isn't a member of the center project →
    the endpoint rejects with 403. This mirrors the /graph-at and
    /timeline gating so the attack surface stays uniform.
    """
    client, maker, *_ = api_env

    # Owner sets up the project, then we swap sessions to a stranger.
    owner_id = await _register(client, "ownerx")
    center_id = await _make_bare_project(maker, "Private")
    await _add_member(maker, center_id, owner_id, role="owner")
    await _logout(client)

    # Register + implicitly log in as a different user who is NOT on
    # the project. The register endpoint sets a fresh session cookie.
    await _register(client, "strangerx")

    r = await client.get(f"/api/projects/{center_id}/org-graph")
    assert r.status_code == 403, r.text
