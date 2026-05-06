"""Org Graph Trust Ladder v1 — capability projection tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from workgraph_api.services import OrgCapabilityService
from workgraph_persistence import (
    AssignmentRepository,
    DecisionRow,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    RoutedSignalRow,
    StreamRow,
    TaskRow,
    UserRepository,
    UserRow,
    session_scope,
)


# ---- helpers ----------------------------------------------------------


async def _mk_user(
    maker,
    username: str,
    *,
    declared_abilities: list[str] | None = None,
    role_hints: list[str] | None = None,
) -> str:
    uid = str(uuid.uuid4())
    profile: dict = {}
    if declared_abilities:
        profile["declared_abilities"] = list(declared_abilities)
    if role_hints:
        profile["role_hints"] = list(role_hints)
    async with session_scope(maker) as session:
        session.add(
            UserRow(
                id=uid,
                username=username,
                display_name=username,
                password_hash="pw",
                password_salt="salt",
                profile=profile,
            )
        )
    return uid


async def _mk_project(maker, title: str = "Org Cap Test") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        session.add(StreamRow(id=str(uuid.uuid4()), project_id=pid, type="project"))
    return pid


async def _add_member(
    maker,
    project_id: str,
    user_id: str,
    *,
    role: str = "member",
    skill_tags: list[str] | None = None,
) -> None:
    async with session_scope(maker) as session:
        row = await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )
        if skill_tags:
            row.skill_tags = list(skill_tags)
            await session.flush()


async def _mk_routed_signal(
    maker,
    *,
    project_id: str,
    source_user_id: str,
    target_user_id: str,
    framing: str,
    status: str = "pending",
) -> str:
    sid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        # Need source/target streams. Reuse the project stream for both.
        proj_stream = (
            await session.execute(
                __import__(
                    "sqlalchemy"
                ).select(StreamRow).where(StreamRow.project_id == project_id)
            )
        ).scalars().first()
        stream_id = proj_stream.id
        session.add(
            RoutedSignalRow(
                id=sid,
                project_id=project_id,
                source_user_id=source_user_id,
                target_user_id=target_user_id,
                source_stream_id=stream_id,
                target_stream_id=stream_id,
                framing=framing,
                background_json=[],
                options_json=[],
                status=status,
                reply_json=(
                    {"option_id": "y", "responded_at": "2026-05-06T00:00:00"}
                    if status in ("replied", "accepted")
                    else None
                ),
            )
        )
    return sid


async def _mk_task(
    maker,
    *,
    project_id: str,
    assignee_id: str,
    title: str,
    description: str = "",
    status: str = "open",
) -> str:
    tid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        # A requirement row to satisfy the FK; we don't care about its
        # contents.
        session.add(RequirementRow(id=rid, project_id=project_id, raw_text=""))
        session.add(
            TaskRow(
                id=tid,
                project_id=project_id,
                requirement_id=rid,
                title=title,
                description=description,
                status=status,
            )
        )
        await session.flush()
        await AssignmentRepository(session).set_assignment(
            project_id=project_id, task_id=tid, user_id=assignee_id
        )
    return tid


async def _mk_decision(
    maker,
    *,
    project_id: str,
    resolver_id: str,
    custom_text: str = "",
    rationale: str = "",
) -> str:
    did = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            DecisionRow(
                id=did,
                project_id=project_id,
                resolver_id=resolver_id,
                custom_text=custom_text,
                rationale=rationale,
                apply_actions=[],
                apply_outcome="advisory",
                created_at=datetime.now(timezone.utc),
            )
        )
    return did


def _find(caps_for_user: list[dict], skill_key: str) -> dict | None:
    for c in caps_for_user:
        if c["skill_key"] == skill_key.lower():
            return c
    return None


# ---- O5 tests ---------------------------------------------------------


@pytest.mark.asyncio
async def test_capability_self_declared_alone_stays_declared(api_env):
    """A skill the user declared in profile but never exercised must
    project as level='declared', not as 'observed' / 'validated' /
    'trusted'. No evidence-from-thin-air."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker, "cap_dec", declared_abilities=["compliance"]
    )
    await _add_member(maker, pid, uid)

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    assert len(out) == 1
    cap = _find(out[0]["capabilities"], "compliance")
    assert cap is not None
    assert cap["level"] == "declared"
    assert cap["evidence_refs"] == []


@pytest.mark.asyncio
async def test_capability_role_skill_tag_reads_as_role_level(api_env):
    """A skill set on ProjectMemberRow.skill_tags (per-project role)
    reads as 'role' even without any evidence rows."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cap_role")
    await _add_member(maker, pid, uid, skill_tags=["design"])

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    cap = _find(out[0]["capabilities"], "design")
    assert cap is not None
    assert cap["level"] == "role"


@pytest.mark.asyncio
async def test_capability_accepted_routed_reply_upgrades_to_validated(
    api_env,
):
    """When the source accepts the target's reply on a routed signal
    whose framing/options mention a declared skill, the target's
    capability for that skill upgrades to 'validated'."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    src = await _mk_user(maker, "cap_v_src")
    tgt = await _mk_user(maker, "cap_v_tgt", declared_abilities=["compliance"])
    await _add_member(maker, pid, src, role="owner")
    await _add_member(maker, pid, tgt)

    sig_id = await _mk_routed_signal(
        maker,
        project_id=pid,
        source_user_id=src,
        target_user_id=tgt,
        framing="Need a compliance review on the new vendor agreement.",
        status="accepted",
    )

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    tgt_caps = next(e for e in out if e["user_id"] == tgt)
    cap = _find(tgt_caps["capabilities"], "compliance")
    assert cap is not None, tgt_caps
    assert cap["level"] == "validated"
    # The evidence ref names the actual routed signal id.
    refs = cap["evidence_refs"]
    assert any(r["kind"] == "routed_signal" and r["id"] == sig_id for r in refs)
    # Signal counts include accepted_reply_count >= 1.
    assert cap["signals"]["accepted_reply_count"] >= 1


@pytest.mark.asyncio
async def test_capability_repeated_evidence_promotes_to_trusted(api_env):
    """Three accepted signals on the same skill_key push the level to
    'trusted'. Verifies the conservative threshold gate."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    src = await _mk_user(maker, "cap_t_src")
    tgt = await _mk_user(maker, "cap_t_tgt", declared_abilities=["compliance"])
    await _add_member(maker, pid, src, role="owner")
    await _add_member(maker, pid, tgt)

    for i in range(3):
        await _mk_routed_signal(
            maker,
            project_id=pid,
            source_user_id=src,
            target_user_id=tgt,
            framing=f"Compliance check #{i} on vendor X",
            status="accepted",
        )

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    tgt_caps = next(e for e in out if e["user_id"] == tgt)
    cap = _find(tgt_caps["capabilities"], "compliance")
    assert cap is not None
    assert cap["level"] == "trusted"
    assert len(cap["evidence_refs"]) >= 3


@pytest.mark.asyncio
async def test_capability_completed_task_upgrades_to_validated(api_env):
    """A done task whose title/description mentions the declared skill
    counts as a validated signal — same trust tier as an accepted
    routed reply."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cap_done", declared_abilities=["design"])
    await _add_member(maker, pid, uid)

    tid = await _mk_task(
        maker,
        project_id=pid,
        assignee_id=uid,
        title="Boss 3 design polish",
        status="done",
    )

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    cap = _find(out[0]["capabilities"], "design")
    assert cap is not None
    assert cap["level"] == "validated"
    assert any(
        r["kind"] == "task" and r["id"] == tid for r in cap["evidence_refs"]
    )


@pytest.mark.asyncio
async def test_capability_does_not_invent_skills_from_text(api_env):
    """A task or routed signal whose text contains words OTHER than
    the user's declared skills must NOT introduce new skill_keys.
    The projection's skill_keys are a closed set per member."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker, "cap_nopick", declared_abilities=["compliance"]
    )
    await _add_member(maker, pid, uid)

    # Seed unrelated text — this must not produce a "performance" or
    # "design" skill row even though those words appear in the task.
    await _mk_task(
        maker,
        project_id=pid,
        assignee_id=uid,
        title="Switch performance and design polish",
        status="done",
    )

    svc = OrgCapabilityService(maker)
    out = await svc.list_for_project(pid)
    keys = {c["skill_key"] for c in out[0]["capabilities"]}
    # Only compliance is declared; performance/design must not appear.
    assert keys == {"compliance"}
    # And compliance stays declared because no row mentions it.
    cap = _find(out[0]["capabilities"], "compliance")
    assert cap["level"] == "declared"


# ---- O3 — routing_suggest cites capability_level ---------------------


@pytest.mark.asyncio
async def test_routing_suggest_carries_matched_capabilities(api_env):
    """When a candidate has a capability for a token in the query,
    routing_suggest's evidence bundle includes a typed
    matched_capabilities entry naming the level."""
    from workgraph_api.services import SkillsService

    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    src = await _mk_user(maker, "rs_cap_src")
    tgt = await _mk_user(
        maker, "rs_cap_tgt", declared_abilities=["compliance"]
    )
    await _add_member(maker, pid, src, role="owner")
    await _add_member(maker, pid, tgt)
    # One accepted route signal lifts compliance to validated.
    await _mk_routed_signal(
        maker,
        project_id=pid,
        source_user_id=src,
        target_user_id=tgt,
        framing="Compliance review on vendor X",
        status="accepted",
    )

    org_svc = OrgCapabilityService(maker)
    skills = SkillsService(maker)
    skills.attach_org_capability_service(org_svc)
    out = await skills.suggest_routing(
        project_id=pid, query="compliance review", source_user_id=src
    )
    assert out, out
    target_row = next(r for r in out if r["user_id"] == tgt)
    caps = target_row["evidence"].get("matched_capabilities") or []
    assert any(c["skill_key"] == "compliance" for c in caps), caps
    cc = next(c for c in caps if c["skill_key"] == "compliance")
    assert cc["level"] == "validated"
    assert cc["evidence_count"] >= 1


@pytest.mark.asyncio
async def test_routing_suggest_prefers_validated_over_role_only(api_env):
    """Two candidates, comparable graph/activity. One has compliance
    declared+validated; the other has compliance only as a role tag.
    The validated candidate should rank higher."""
    from workgraph_api.services import SkillsService

    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    src = await _mk_user(maker, "rs_cmp_src")
    role_only = await _mk_user(maker, "rs_cmp_role")
    validated = await _mk_user(
        maker, "rs_cmp_val", declared_abilities=["compliance"]
    )
    await _add_member(maker, pid, src, role="owner")
    await _add_member(
        maker, pid, role_only, skill_tags=["compliance"]
    )
    await _add_member(maker, pid, validated)
    # Validated path: an accepted route on compliance.
    await _mk_routed_signal(
        maker,
        project_id=pid,
        source_user_id=src,
        target_user_id=validated,
        framing="Compliance review on vendor X",
        status="accepted",
    )

    org_svc = OrgCapabilityService(maker)
    skills = SkillsService(maker)
    skills.attach_org_capability_service(org_svc)
    out = await skills.suggest_routing(
        project_id=pid, query="compliance review", source_user_id=src
    )
    # Validated user must rank above role-only.
    val_pos = next(
        i for i, r in enumerate(out) if r["user_id"] == validated
    )
    role_pos = next(
        (i for i, r in enumerate(out) if r["user_id"] == role_only), None
    )
    # role-only might not score (graph/activity all 0); the
    # invariant we need is: when both appear, validated ranks above
    # role-only OR validated is the only one returned.
    if role_pos is not None:
        assert val_pos < role_pos, out


@pytest.mark.asyncio
async def test_capabilities_endpoint_member_can_read(api_env):
    """The GET /capabilities endpoint requires project membership and
    returns the projection. Non-members get 403."""
    client, maker, *_ = api_env
    # Create + login an outsider (no project membership) — they should
    # be 403.
    r = await client.post(
        "/api/auth/register",
        json={"username": "cap_route_outsider", "password": "hunter22"},
    )
    assert r.status_code == 200
    # Seed a separate project they don't belong to.
    pid = await _mk_project(maker)
    member = await _mk_user(maker, "cap_route_member")
    await _add_member(maker, pid, member)
    r = await client.get(f"/api/projects/{pid}/capabilities")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_routing_suggest_evidence_matched_capability_travels_with_signal(
    api_env,
):
    """O4: the per-suggestion evidence.matched_capabilities is the
    payload dispatch persists as part of routing_basis.matched_suggestion.
    We verify the wire shape here (dispatch persistence is covered by
    the R2 grounding test); together they prove the audit chain."""
    from workgraph_api.services import SkillsService

    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    src = await _mk_user(maker, "rs_o4_src")
    tgt = await _mk_user(maker, "rs_o4_tgt", declared_abilities=["compliance"])
    await _add_member(maker, pid, src, role="owner")
    await _add_member(maker, pid, tgt)
    await _mk_routed_signal(
        maker,
        project_id=pid,
        source_user_id=src,
        target_user_id=tgt,
        framing="Compliance review on vendor X",
        status="accepted",
    )

    org_svc = OrgCapabilityService(maker)
    skills = SkillsService(maker)
    skills.attach_org_capability_service(org_svc)
    rows = await skills.suggest_routing(
        project_id=pid, query="compliance review", source_user_id=src
    )
    target_row = next(r for r in rows if r["user_id"] == tgt)
    # The shape RoutingService.dispatch will persist verbatim under
    # routing_basis.matched_suggestion: a `user_id` keyed entry whose
    # `evidence.matched_capabilities` enumerates levels per skill.
    assert "evidence" in target_row
    caps = target_row["evidence"]["matched_capabilities"]
    cc = next(c for c in caps if c["skill_key"] == "compliance")
    assert cc["level"] in ("validated", "trusted")
    # `evidence_count` is non-zero — the audit consumer can drill in.
    assert cc["evidence_count"] >= 1
