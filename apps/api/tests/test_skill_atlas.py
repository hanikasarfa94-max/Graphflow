"""SkillAtlasService tests.

Covers:
  * role skill resolution from role_hints via ROLE_SKILL_BUNDLES
  * profile skill sections: declared / observed / validated
  * visibility: owner sees all members; non-owner sees only self
  * collective aggregate: populated for owner, empty for non-owner
  * unvalidated declarations surface in the owner's gap view
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from workgraph_api.services import SkillAtlasService
from workgraph_persistence import (
    DecisionRepository,
    MessageRepository,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)


def _uid() -> str:
    return str(uuid4())


async def _mk_project(maker) -> str:
    pid = _uid()
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="atlas"))
        await session.flush()
    return pid


async def _mk_user(
    maker,
    username: str,
    *,
    role_hints: list[str] | None = None,
    declared: list[str] | None = None,
) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        if role_hints or declared:
            await UserRepository(session).update_profile(
                user.id,
                role_hints=role_hints,
                declared_abilities=declared,
            )
        return user.id


async def _add_member(
    maker, project_id: str, user_id: str, *, role: str = "member"
) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )


@pytest.mark.asyncio
async def test_owner_sees_all_members(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(
        maker, "atlas_owner", role_hints=["game-director"], declared=["vision"]
    )
    member = await _mk_user(
        maker, "atlas_member", role_hints=["design-lead"], declared=["balance"]
    )
    await _add_member(maker, pid, owner, role="owner")
    await _add_member(maker, pid, member, role="member")

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=owner
    )

    assert atlas["viewer_scope"] == "owner"
    ids = {c["user_id"] for c in atlas["members"]}
    assert ids == {owner, member}
    # Collective aggregate populated for owner.
    assert atlas["collective"]
    # Owner's role_skills from "game-director" bundle are in the
    # collective coverage set.
    assert "scope-decisions" in atlas["collective"]["role_skill_coverage"]
    assert "design-vision" in atlas["collective"]["role_skill_coverage"]


@pytest.mark.asyncio
async def test_non_owner_sees_only_self(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(
        maker, "atlas_owner2", role_hints=["game-director"]
    )
    member = await _mk_user(
        maker, "atlas_member2", role_hints=["qa-lead"]
    )
    await _add_member(maker, pid, owner, role="owner")
    await _add_member(maker, pid, member, role="member")

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=member
    )

    assert atlas["viewer_scope"] == "self"
    assert [c["user_id"] for c in atlas["members"]] == [member]
    # Non-owner: collective stays empty — group-level insights are a
    # project-owner privilege in v1.
    assert atlas["collective"] == {}


@pytest.mark.asyncio
async def test_role_skills_derived_from_role_hints(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker,
        "atlas_role_hints",
        role_hints=["engineering-lead"],
    )
    await _add_member(maker, pid, uid, role="owner")

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=uid
    )
    card = atlas["members"][0]
    # engineering-lead bundle → systems-architecture / performance / eng-coordination
    assert "systems-architecture" in card["role_skills"]
    assert "performance" in card["role_skills"]
    assert "eng-coordination" in card["role_skills"]


@pytest.mark.asyncio
async def test_profile_sections_split_declared_observed(api_env):
    """Declared + observed come from different sources and must render
    separately. Declared is what the user said; observed is what the
    graph saw. Their intersection is `validated`."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker,
        "atlas_split",
        role_hints=["design-lead"],
        declared=["balance", "decision-making"],
    )
    await _add_member(maker, pid, uid, role="owner")

    # Seed observed signals that cross thresholds: 2 decisions resolved
    # gives "decision-making" in observed skills.
    async with session_scope(maker) as session:
        dec_repo = DecisionRepository(session)
        for _ in range(2):
            await dec_repo.create(
                conflict_id=None,
                project_id=pid,
                resolver_id=uid,
                option_index=None,
                custom_text="decision",
                rationale="test",
                apply_actions=[],
                apply_outcome="advisory",
            )

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=uid
    )
    card = atlas["members"][0]
    assert "decision-making" in card["profile_skills_observed"]
    assert "decision-making" in card["profile_skills_validated"]
    # 'balance' was declared but no emission corresponds — not validated.
    assert "balance" in card["profile_skills_declared"]
    assert "balance" not in card["profile_skills_observed"]


@pytest.mark.asyncio
async def test_collective_aggregates_and_flags_unvalidated(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(
        maker,
        "atlas_collective_owner",
        role_hints=["game-director"],
        declared=["vision", "accessibility"],
    )
    member = await _mk_user(
        maker,
        "atlas_collective_member",
        role_hints=["qa-lead"],
        declared=["playtest-coordination"],
    )
    await _add_member(maker, pid, owner, role="owner")
    await _add_member(maker, pid, member, role="member")

    # Seed enough emissions for `communication` observed skill on owner
    # (>= 10 messages in 30d).
    async with session_scope(maker) as session:
        msg_repo = MessageRepository(session)
        for _ in range(12):
            await msg_repo.append(
                project_id=pid,
                author_id=owner,
                body="standup note",
            )

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=owner
    )
    c = atlas["collective"]
    # declared_abilities_combined dedups across members
    assert "vision" in c["declared_abilities_combined"]
    assert "accessibility" in c["declared_abilities_combined"]
    assert "playtest-coordination" in c["declared_abilities_combined"]
    # observed_skills_combined reflects what crossed thresholds
    assert "communication" in c["observed_skills_combined"]
    # accessibility was declared but no emission supports it —
    # surfaces in the gap view as "unvalidated."
    assert "accessibility" in c["unvalidated_declarations"]
    # communication is an observed skill, not a declared one — does
    # NOT appear in unvalidated.
    assert "communication" not in c["unvalidated_declarations"]


@pytest.mark.asyncio
async def test_unknown_role_hint_yields_empty_role_skills(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(
        maker, "atlas_unknown_role", role_hints=["chief-badger"]
    )
    await _add_member(maker, pid, uid, role="owner")

    svc = SkillAtlasService(maker)
    atlas = await svc.atlas_for_project(
        project_id=pid, viewer_user_id=uid
    )
    card = atlas["members"][0]
    # Unknown role → no role skills. No crash.
    assert card["role_skills"] == []
    assert card["role_hints"] == ["chief-badger"]
