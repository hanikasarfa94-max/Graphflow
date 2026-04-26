"""Stage A — decisions through membrane (advisory).

Covers MembraneService._review_decision_crystallize directly + the
3 wired paths (conflict-resolution, IM apply, silent-consensus ratify).
The review is warning-only in v0; flows complete unchanged but the
response carries observations.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_api.services.membrane import MembraneCandidate
from workgraph_persistence import (
    ConflictRow,
    DecisionRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    StreamRow,
    session_scope,
)


# ---- helpers ----------------------------------------------------------


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


async def _mk_project(maker, *, owner_id: str) -> tuple[str, str]:
    pid = str(uuid.uuid4())
    req_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Decision Membrane Test"))
        session.add(StreamRow(id=str(uuid.uuid4()), type="project", project_id=pid))
        session.add(
            RequirementRow(
                id=req_id, project_id=pid, version=1, raw_text="canonical"
            )
        )
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
    return pid, req_id


# ---- review function — direct -----------------------------------------


@pytest.mark.asyncio
async def test_review_decision_crystallize_no_warnings_when_clean(api_env):
    client, maker, *_ = api_env
    membrane = client._transport.app.state.membrane_service  # type: ignore[attr-defined]
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="X"))

    review = await membrane.review(
        MembraneCandidate(
            kind="decision_crystallize",
            project_id=pid,
            proposer_user_id="user-1",
            title="Ship feature X by Friday",
            metadata={"source": "conflict_resolution", "rationale": "team agreed in standup"},
        )
    )
    assert review.action == "auto_merge"
    assert review.warnings == ()


@pytest.mark.asyncio
async def test_review_warns_on_missing_rationale(api_env):
    client, maker, *_ = api_env
    membrane = client._transport.app.state.membrane_service  # type: ignore[attr-defined]
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Y"))

    review = await membrane.review(
        MembraneCandidate(
            kind="decision_crystallize",
            project_id=pid,
            proposer_user_id="user-1",
            title="Ship X",
            metadata={"source": "conflict_resolution", "rationale": ""},
        )
    )
    assert review.action == "auto_merge"
    assert any("rationale" in w.lower() for w in review.warnings)


@pytest.mark.asyncio
async def test_review_skips_rationale_warning_for_gated_proposal_source(api_env):
    """Gated proposals carry rationale on the proposal, not on the
    decision row, so the membrane shouldn't warn about its absence."""
    client, maker, *_ = api_env
    membrane = client._transport.app.state.membrane_service  # type: ignore[attr-defined]
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Z"))

    review = await membrane.review(
        MembraneCandidate(
            kind="decision_crystallize",
            project_id=pid,
            proposer_user_id="user-1",
            title="Approved budget",
            metadata={"source": "gated_proposal", "rationale": ""},
        )
    )
    assert review.action == "auto_merge"
    assert not any("rationale" in w.lower() for w in review.warnings)


@pytest.mark.asyncio
async def test_review_warns_on_duplicate_decision_title(api_env):
    """A prior crystallized decision with the same normalized title
    surfaces as a warning so the proposer can confirm a deliberate
    supersede."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "dec_owner")
    pid, _ = await _mk_project(maker, owner_id=owner_id)
    membrane = client._transport.app.state.membrane_service  # type: ignore[attr-defined]

    # Pre-seed a crystallized decision.
    async with session_scope(maker) as session:
        await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=owner_id,
            option_index=None,
            custom_text="freeze scope after Alpha",
            rationale="agreed in offsite",
            apply_actions=[],
            apply_outcome="advisory",
        )

    review = await membrane.review(
        MembraneCandidate(
            kind="decision_crystallize",
            project_id=pid,
            proposer_user_id=owner_id,
            title="Freeze scope after Alpha",  # normalized → same
            metadata={"source": "im_apply", "rationale": "consensus"},
        )
    )
    assert review.action == "auto_merge"
    assert any("prior decision" in w.lower() for w in review.warnings)


# ---- wired paths surface warnings -------------------------------------


@pytest.mark.asyncio
async def test_conflict_resolve_response_includes_warnings_field(api_env):
    """Conflict resolution flows through the membrane and surfaces
    warnings on the response — even if the warnings list is empty,
    the contract is that the field is present."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "conf_o")
    pid, req_id = await _mk_project(maker, owner_id=owner_id)

    # Pre-seed a conflict to resolve.
    cid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            ConflictRow(
                id=cid,
                project_id=pid,
                requirement_id=req_id,
                rule="missing_owner",
                severity="medium",
                fingerprint=f"missing_owner-{cid}",
                targets=[],
                detail={},
                options=[
                    {"title": "leave it open", "rationale": "no owner needed yet"}
                ],
                status="open",
            )
        )

    await _login(client, "conf_o")
    r = await client.post(
        f"/api/conflicts/{cid}/decision",
        json={"option_index": 0, "rationale": "deferring"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # Warnings field is contractually always present.
    assert "warnings" in body
    assert isinstance(body["warnings"], list)
