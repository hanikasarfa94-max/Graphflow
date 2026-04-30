"""Phase 1.A license system — acceptance tests.

Five required cases:
  1. Observer's sub-agent prompt excludes out-of-view nodes.
  2. Routed reply citing out-of-view nodes triggers lint pause.
  3. Scoped sub-agent triggers leader-escalation.
  4. LicenseAuditRow is written per outcome.
  5. Full-tier internal asks are unaffected (regression).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    AssignmentRepository,
    DecisionRepository,
    LicenseAuditRow,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectMemberRow,
    ProjectRow,
    RequirementRow,
    UserRepository,
    session_scope,
)

from workgraph_api.services.leader_escalation import LeaderEscalationService
from workgraph_api.services.license_context import (
    LicenseContextService,
    tighter_tier,
)
from workgraph_api.services.license_lint import extract_node_ids


# ---- fixtures helpers ---------------------------------------------------


async def _mk_project(maker, title: str = "LP") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _mk_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _add_member(
    maker,
    *,
    project_id: str,
    user_id: str,
    role: str = "member",
    license_tier: str = "full",
) -> None:
    async with session_scope(maker) as session:
        member = await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )
        member.license_tier = license_tier
        await session.flush()


async def _seed_graph_plan(maker, *, project_id: str) -> dict[str, str]:
    """Seed a tiny project with 1 goal, 2 deliverables, 2 tasks.

    Returns a dict of ids keyed by logical name so tests can assert
    visibility without caring about UUIDs.
    """
    async with session_scope(maker) as session:
        req = RequirementRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            version=1,
            raw_text="test",
            parsed_json={},
            parse_outcome="ok",
        )
        session.add(req)
        await session.flush()
        req_id = req.id

    async with session_scope(maker) as session:
        graph = await ProjectGraphRepository(session).append_for_requirement(
            project_id=project_id,
            requirement_id=req_id,
            goals=[{"title": "Ship feature"}],
            deliverables=[
                {"title": "Del A"},
                {"title": "Del B"},
            ],
            constraints=[],
            risks=[],
        )
        ids = {
            "goal_id": graph["goals"][0].id,
            "deliverable_a": graph["deliverables"][0].id,
            "deliverable_b": graph["deliverables"][1].id,
        }
        plan = await PlanRepository(session).append_plan(
            project_id=project_id,
            requirement_id=req_id,
            tasks=[
                {
                    "ref": "task-mine",
                    "title": "Mine",
                    "deliverable_id": ids["deliverable_a"],
                    "assignee_role": "backend",
                },
                {
                    "ref": "task-theirs",
                    "title": "Theirs",
                    "deliverable_id": ids["deliverable_b"],
                    "assignee_role": "backend",
                },
            ],
            dependencies=[{"from_ref": "task-mine", "to_ref": "task-theirs"}],
            milestones=[],
        )
        ids["task_mine"] = plan["tasks"][0].id
        ids["task_theirs"] = plan["tasks"][1].id
    return ids


async def _assign(maker, *, project_id: str, task_id: str, user_id: str):
    async with session_scope(maker) as session:
        await AssignmentRepository(session).set_assignment(
            project_id=project_id, task_id=task_id, user_id=user_id
        )


# ---- 1. observer sub-agent prompt excludes out-of-view nodes ------------


@pytest.mark.asyncio
async def test_observer_slice_excludes_out_of_view_nodes(api_env):
    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    observer_id = await _mk_user(maker, "obs_user")
    teammate_id = await _mk_user(maker, "obs_teammate")
    await _add_member(
        maker,
        project_id=project_id,
        user_id=observer_id,
        license_tier="observer",
    )
    await _add_member(
        maker, project_id=project_id, user_id=teammate_id
    )
    ids = await _seed_graph_plan(maker, project_id=project_id)
    # Observer has no assignments — sees nothing.
    await _assign(
        maker,
        project_id=project_id,
        task_id=ids["task_theirs"],
        user_id=teammate_id,
    )

    svc = LicenseContextService(maker)
    slice_ = await svc.build_slice(
        project_id=project_id,
        viewer_user_id=observer_id,
        audience_user_id=None,
    )
    assert slice_["license_tier"] == "observer"
    assert slice_["plan"]["tasks"] == []
    assert slice_["graph"]["deliverables"] == []
    assert slice_["graph"]["goals"] == []

    visible = svc.collect_visible_node_ids(slice_)
    assert ids["task_theirs"] not in visible
    assert ids["deliverable_a"] not in visible


# ---- 2. routed reply citing out-of-view nodes triggers lint pause -------


@pytest.mark.asyncio
async def test_routed_reply_with_out_of_view_citation_triggers_lint_pause(
    api_env,
):
    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    source_id = await _mk_user(maker, "src_observer")
    target_id = await _mk_user(maker, "tgt_full")
    await _add_member(
        maker,
        project_id=project_id,
        user_id=source_id,
        license_tier="observer",
    )
    await _add_member(
        maker, project_id=project_id, user_id=target_id
    )
    ids = await _seed_graph_plan(maker, project_id=project_id)
    # target has a task, source has nothing — source's view is empty.
    await _assign(
        maker,
        project_id=project_id,
        task_id=ids["task_theirs"],
        user_id=target_id,
    )

    svc = LicenseContextService(maker)
    from workgraph_api.services.license_lint import lint_reply

    # Reply body cites a UUID that exists but falls outside source's view.
    body = f"See the plan in task {ids['task_theirs']} for context."
    result = await lint_reply(
        license_context_service=svc,
        project_id=project_id,
        source_user_id=target_id,  # target drafted the reply
        recipient_user_id=source_id,  # source receives it — observer
        reply_body=body,
    )
    assert result["clean"] is False
    assert ids["task_theirs"] in result["out_of_view"]
    assert result["effective_tier"] == "observer"


@pytest.mark.asyncio
async def test_lint_clean_when_cited_ids_are_in_view(api_env):
    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    source_id = await _mk_user(maker, "lint_src")
    target_id = await _mk_user(maker, "lint_tgt")
    await _add_member(
        maker, project_id=project_id, user_id=source_id
    )
    await _add_member(
        maker, project_id=project_id, user_id=target_id
    )
    ids = await _seed_graph_plan(maker, project_id=project_id)

    svc = LicenseContextService(maker)
    from workgraph_api.services.license_lint import lint_reply

    # No citations → clean lint.
    result = await lint_reply(
        license_context_service=svc,
        project_id=project_id,
        source_user_id=source_id,
        recipient_user_id=target_id,
        reply_body="Acknowledged — proceeding.",
    )
    assert result["clean"] is True
    assert result["out_of_view"] == []


# ---- 3. scoped sub-agent triggers leader-escalation ---------------------


@pytest.mark.asyncio
async def test_leader_escalation_detection_and_dispatch(api_env):
    client, maker, *_ = api_env
    project_id = await _mk_project(maker)
    asker_id = await _mk_user(maker, "esc_asker")
    leader_id = await _mk_user(maker, "esc_leader")
    await _add_member(
        maker,
        project_id=project_id,
        user_id=asker_id,
        role="member",
        license_tier="task_scoped",
    )
    await _add_member(
        maker,
        project_id=project_id,
        user_id=leader_id,
        role="owner",
        license_tier="full",
    )

    from workgraph_api.main import app

    pre_answer_service = app.state.pre_answer_service
    routing_service = app.state.routing_service
    esc = LeaderEscalationService(maker, routing_service, pre_answer_service)

    # Detection heuristic: explicit escalate_to_leader flag.
    flag, reason = esc.should_escalate(
        {"escalate_to_leader": True, "reason": "needs leader context"}
    )
    assert flag is True
    assert "leader" in reason.lower()

    # Confidence heuristic — low conf with out-of-view-context flag.
    flag2, _ = esc.should_escalate(
        {"confidence": 0.2, "out_of_view_context_needed": True}
    )
    assert flag2 is True

    # Confidence alone (without out-of-view flag) does NOT escalate.
    flag3, _ = esc.should_escalate({"confidence": 0.1})
    assert flag3 is False

    # Dispatch creates a routed signal with leader as target.
    result = await esc.escalate(
        project_id=project_id,
        asker_user_id=asker_id,
        question="Which vendor should ship first?",
        reason="decision ownership sits with leadership",
    )
    assert result["ok"] is True
    assert result["leader_user_id"] == leader_id
    assert result["signal"]["target_user_id"] == leader_id
    assert result["signal"]["source_user_id"] == asker_id


# ---- 4. LicenseAuditRow written per outcome -----------------------------


@pytest.mark.asyncio
async def test_license_audit_row_written_per_outcome(api_env):
    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    source_id = await _mk_user(maker, "audit_src")
    target_id = await _mk_user(maker, "audit_tgt")
    await _add_member(
        maker, project_id=project_id, user_id=source_id
    )
    await _add_member(
        maker,
        project_id=project_id,
        user_id=target_id,
        license_tier="observer",
    )

    from workgraph_api.main import app

    routing_service = app.state.routing_service

    # Denied outcome — no reply shipped, audit row persisted.
    await routing_service.resolve_lint_decision(
        project_id=project_id,
        source_user_id=source_id,
        recipient_user_id=target_id,
        reply_body="cite D#99",
        decision="deny",
        referenced_node_ids=["D#99"],
        out_of_view_node_ids=["D#99"],
        effective_tier="observer",
        signal_id=None,
    )
    # Edited outcome
    await routing_service.resolve_lint_decision(
        project_id=project_id,
        source_user_id=source_id,
        recipient_user_id=target_id,
        reply_body="cite D#99",
        decision="edit",
        referenced_node_ids=["D#99"],
        out_of_view_node_ids=["D#99"],
        effective_tier="observer",
        signal_id=None,
    )
    # Clean — no out-of-view
    await routing_service.record_clean_audit(
        project_id=project_id,
        source_user_id=source_id,
        recipient_user_id=target_id,
        referenced_node_ids=[],
        effective_tier="full",
        signal_id=None,
    )

    async with session_scope(maker) as session:
        rows = (
            await session.execute(
                select(LicenseAuditRow).where(
                    LicenseAuditRow.project_id == project_id
                )
            )
        ).scalars().all()

    outcomes = sorted(r.outcome for r in rows)
    assert outcomes == ["clean", "denied", "edited"]
    # Spot-check the denied row carries the out-of-view payload.
    denied = next(r for r in rows if r.outcome == "denied")
    assert denied.out_of_view_node_ids == ["D#99"]
    assert denied.effective_tier == "observer"


# ---- 5. full-tier internal regression -----------------------------------


@pytest.mark.asyncio
async def test_full_tier_slice_is_unfiltered_regression(api_env):
    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    u_full = await _mk_user(maker, "full_viewer")
    u_peer = await _mk_user(maker, "full_peer")
    await _add_member(maker, project_id=project_id, user_id=u_full)
    await _add_member(maker, project_id=project_id, user_id=u_peer)
    ids = await _seed_graph_plan(maker, project_id=project_id)
    await _assign(
        maker,
        project_id=project_id,
        task_id=ids["task_theirs"],
        user_id=u_peer,
    )

    svc = LicenseContextService(maker)
    slice_ = await svc.build_slice(
        project_id=project_id,
        viewer_user_id=u_full,
        audience_user_id=u_full,
    )
    assert slice_["license_tier"] == "full"
    task_ids = {t["id"] for t in slice_["plan"]["tasks"]}
    assert ids["task_mine"] in task_ids
    assert ids["task_theirs"] in task_ids
    del_ids = {d["id"] for d in slice_["graph"]["deliverables"]}
    assert ids["deliverable_a"] in del_ids
    assert ids["deliverable_b"] in del_ids


# ---- misc helpers -------------------------------------------------------


def test_tighter_tier_resolves_correctly():
    assert tighter_tier("full", "observer") == "observer"
    assert tighter_tier("task_scoped", "observer") == "observer"
    assert tighter_tier("full", "task_scoped") == "task_scoped"
    assert tighter_tier("full", "full") == "full"


def test_tighter_tier_unknown_value_fails_closed(caplog):
    """Unknown tier strings (corruption, forward-compat, test injection)
    must collapse to the most-restrictive tier (`observer`), NOT grant
    full-tier access. A warning must be emitted so ops can notice."""
    import logging

    caplog.set_level(logging.WARNING, logger="workgraph.api.license_context")

    # Against a known lower-tightness tier: unknown should win as observer.
    assert tighter_tier("nonexistent_tier", "full") == "observer"
    # Against observer (already most-restrictive): still observer.
    assert tighter_tier("nonexistent_tier", "observer") == "observer"
    # Both unknown: observer.
    assert tighter_tier("bogus_a", "bogus_b") == "observer"
    # None / empty / other falsy values fail closed too.
    assert tighter_tier(None, "full") == "observer"  # type: ignore[arg-type]
    assert tighter_tier("", "task_scoped") == "observer"
    # Case sensitivity — "FULL" is not "full"; fail closed.
    assert tighter_tier("FULL", "full") == "observer"

    # At least one warning was emitted for the unknown value.
    assert any(
        "nonexistent_tier" in rec.getMessage() for rec in caplog.records
    ), "expected a warning log for the unrecognized tier"


@pytest.mark.asyncio
async def test_resolve_effective_tier_unknown_db_value_fails_closed(
    api_env, caplog
):
    """If the DB returns a bogus license_tier value (schema drift, manual
    patch, test-injection), resolve_effective_tier must coerce it to the
    most-restrictive tier rather than granting full access."""
    import logging

    _, maker, *_ = api_env
    project_id = await _mk_project(maker)
    user_id = await _mk_user(maker, "bogus_tier_user")
    # Insert the member with a bogus tier straight into the row.
    async with session_scope(maker) as session:
        member = await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role="member"
        )
        member.license_tier = "nonexistent_tier"
        await session.flush()

    caplog.set_level(logging.WARNING, logger="workgraph.api.license_context")
    svc = LicenseContextService(maker)
    tier = await svc.resolve_effective_tier(
        project_id=project_id,
        viewer_user_id=user_id,
        audience_user_id=None,
    )
    assert tier == "observer", (
        "unknown tier must fail closed to the most-restrictive tier "
        "(observer), not grant full access"
    )
    assert any(
        "nonexistent_tier" in rec.getMessage() for rec in caplog.records
    ), "expected a warning log when the DB returns an unknown tier"

    # And the slice we build for such a user must actually apply the
    # observer filter (not fall through unfiltered).
    ids = await _seed_graph_plan(maker, project_id=project_id)
    slice_ = await svc.build_slice(
        project_id=project_id,
        viewer_user_id=user_id,
        audience_user_id=None,
    )
    assert slice_["license_tier"] == "observer"
    # User has no assignments — observer view is empty.
    assert slice_["plan"]["tasks"] == []
    assert slice_["graph"]["deliverables"] == []
    visible = svc.collect_visible_node_ids(slice_)
    assert ids["task_mine"] not in visible
    assert ids["task_theirs"] not in visible


def test_extract_node_ids_catches_shortcuts_and_uuids():
    body = "See D#12 and T#7 — also refer to task "
    uid = "00000000-0000-0000-0000-000000000042"
    body += uid
    ids = extract_node_ids(body)
    assert "D#12" in ids
    assert "T#7" in ids
    assert uid in ids


def test_extract_node_ids_honors_explicit_citations():
    body = "ignored D#99"
    ids = extract_node_ids(body, explicit_citations=["only-this"])
    assert ids == ["only-this"]


# ---------------------------------------------------------------------------
# Pickup #7 — allowed_scopes (ScopeTierPills consumer).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_scopes_full_tier_intersects_with_pills(api_env):
    """A full-tier member sees whatever pills they toggle on."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_full")
    await _add_member(maker, project_id=pid, user_id=user, license_tier="full")

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=user,
        requested_tiers={
            "personal": True,
            "group": True,
            "department": False,
            "enterprise": False,
        },
    )
    assert out == frozenset({"personal", "group"})


@pytest.mark.asyncio
async def test_allowed_scopes_observer_tier_caps_at_group(api_env):
    """Observer-tier member can only request group, even if all pills on."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_obs")
    await _add_member(
        maker, project_id=pid, user_id=user, license_tier="observer"
    )

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=user,
        requested_tiers={
            "personal": True,
            "group": True,
            "department": True,
            "enterprise": True,
        },
    )
    assert out == frozenset({"group"})


@pytest.mark.asyncio
async def test_allowed_scopes_task_scoped_caps_at_personal_group(api_env):
    """task_scoped tier can request personal + group only."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_ts")
    await _add_member(
        maker, project_id=pid, user_id=user, license_tier="task_scoped"
    )

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=user,
        requested_tiers={
            "personal": True,
            "group": True,
            "department": True,
            "enterprise": True,
        },
    )
    assert out == frozenset({"personal", "group"})


@pytest.mark.asyncio
async def test_allowed_scopes_non_member_returns_empty(api_env):
    """A user who isn't a project member sees nothing — fail closed."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    other = await _mk_user(maker, "as_other")
    # Note: NOT added as project member.

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=other,
        requested_tiers={
            "personal": True,
            "group": True,
            "department": True,
            "enterprise": True,
        },
    )
    assert out == frozenset()


@pytest.mark.asyncio
async def test_allowed_scopes_no_pill_state_returns_full_licensed_set(
    api_env,
):
    """`requested_tiers=None` (legacy callers) preserves slice-5c behavior:
    no pill filter, returns everything the user is licensed for.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_legacy")
    await _add_member(maker, project_id=pid, user_id=user, license_tier="full")

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid, user_id=user, requested_tiers=None
    )
    assert out == frozenset(
        {"personal", "group", "department", "enterprise"}
    )


@pytest.mark.asyncio
async def test_allowed_scopes_all_pills_off_returns_empty(api_env):
    """Every pill toggled off → empty set, even for full-tier."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_silent")
    await _add_member(maker, project_id=pid, user_id=user, license_tier="full")

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=user,
        requested_tiers={
            "personal": False,
            "group": False,
            "department": False,
            "enterprise": False,
        },
    )
    assert out == frozenset()


@pytest.mark.asyncio
async def test_allowed_scopes_unknown_pill_keys_ignored(api_env):
    """Garbage pill keys (frontend bug, schema drift) are dropped."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    user = await _mk_user(maker, "as_unknown")
    await _add_member(maker, project_id=pid, user_id=user, license_tier="full")

    svc = LicenseContextService(maker)
    out = await svc.allowed_scopes(
        project_id=pid,
        user_id=user,
        requested_tiers={
            "group": True,
            "bogus_tier": True,  # ignored
            "DROP TABLE": True,  # ignored — not a registered tier name
        },
    )
    assert out == frozenset({"group"})
