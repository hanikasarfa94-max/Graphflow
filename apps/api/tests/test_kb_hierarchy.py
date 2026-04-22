"""Phase 3.A hierarchical KB acceptance tests.

Seven required cases (PLAN-v4.md Phase 3.A):

  1. folder_create — full-tier members can create folders; task_scoped
     and non-members get 403. Empty / over-long names 400.
  2. folder_move  — owner can reparent a folder; new parent valid; move
     reflected in the tree.
  3. item_move    — any member can move items; folder_id updates.
  4. cycle_detect — reparenting a folder under its own descendant
     returns 409 'cycle'.
  5. license_inherit_vs_override — absence of override leaves item tier
     undefined in the tree payload; upsert sets the override; null
     clears it. Tier validation rejects garbage.
  6. delete_nonempty — deleting a folder that still has child folders
     OR items returns 409.
  7. tree_structure — /kb/tree returns folders + items with correct
     parent pointers for a 2-level hierarchy + items distributed at
     each level. Consumer can rebuild the nested tree locally.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from workgraph_persistence import (
    KbFolderRepository,
    KbItemLicenseRepository,
    MembraneSignalRepository,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)


# ---- helpers -------------------------------------------------------------


async def _register(client: AsyncClient, username: str) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client: AsyncClient, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _mk_project(maker, title: str = "KbHier") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker,
    pid: str,
    uid: str,
    *,
    role: str = "member",
    license_tier: str = "full",
) -> None:
    async with session_scope(maker) as session:
        row = await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )
        row.license_tier = license_tier
        await session.flush()


async def _seed_item(
    maker, *, project_id: str, summary: str, source_identifier: str
) -> str:
    """Create a MembraneSignalRow directly — cheaper than going through
    the membrane router and doesn't touch the classifier stub."""
    async with session_scope(maker) as session:
        repo = MembraneSignalRepository(session)
        row = await repo.create(
            project_id=project_id,
            source_kind="user-drop",
            source_identifier=source_identifier,
            raw_content=summary,
        )
        await repo.set_classification(
            row.id,
            classification={
                "is_relevant": True,
                "summary": summary,
                "tags": [],
                "confidence": 1.0,
            },
            status="approved",
        )
        return row.id


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_folder_create(api_env):
    """Case 1: full-tier creates; task_scoped rejected; bad names 400."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    # Load the tree once so the root auto-backfill runs. Tree read
    # from a fresh project should produce exactly one folder (root).
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    assert r.status_code == 200, r.text
    body = r.json()
    root_id = body["root_id"]
    assert root_id is not None
    assert len(body["folders"]) == 1

    # Happy path: create under the root.
    r = await client.post(
        f"/api/projects/{pid}/kb/folders",
        json={"name": "design", "parent_folder_id": root_id},
    )
    assert r.status_code == 200, r.text
    design = r.json()["folder"]
    assert design["name"] == "design"
    assert design["parent_folder_id"] == root_id

    # Empty name → 400.
    r = await client.post(
        f"/api/projects/{pid}/kb/folders",
        json={"name": "   ", "parent_folder_id": root_id},
    )
    assert r.status_code == 400

    # Duplicate sibling name → 409.
    r = await client.post(
        f"/api/projects/{pid}/kb/folders",
        json={"name": "design", "parent_folder_id": root_id},
    )
    assert r.status_code == 409

    # Task-scoped member cannot create folders.
    scoped = await _register(client, "kh_scoped")
    await _add_member(
        maker, pid, scoped, role="member", license_tier="task_scoped"
    )
    await _login(client, "kh_scoped")
    r = await client.post(
        f"/api/projects/{pid}/kb/folders",
        json={"name": "docs", "parent_folder_id": root_id},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_folder_move(api_env):
    """Case 2: owner reparents a folder; tree reflects the new edge."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner2")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    # Bootstrap tree + create two sibling folders under root.
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    root_id = r.json()["root_id"]
    a = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "A", "parent_folder_id": root_id},
        )
    ).json()["folder"]
    b = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "B", "parent_folder_id": root_id},
        )
    ).json()["folder"]

    # Move B under A.
    r = await client.patch(
        f"/api/projects/{pid}/kb/folders/{b['id']}/parent",
        json={"new_parent_id": a["id"]},
    )
    assert r.status_code == 200, r.text
    updated = r.json()["folder"]
    assert updated["parent_folder_id"] == a["id"]

    # Tree reflects it.
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    folders = r.json()["folders"]
    b_in_tree = next(f for f in folders if f["id"] == b["id"])
    assert b_in_tree["parent_folder_id"] == a["id"]


@pytest.mark.asyncio
async def test_item_move(api_env):
    """Case 3: any member moves items. folder_id updates."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner3")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    r = await client.get(f"/api/projects/{pid}/kb/tree")
    root_id = r.json()["root_id"]
    f1 = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "engineering", "parent_folder_id": root_id},
        )
    ).json()["folder"]

    # Seed an item; it lands in root via auto-backfill.
    item_id = await _seed_item(
        maker,
        project_id=pid,
        summary="design doc #1",
        source_identifier="https://example.com/design-1",
    )
    # Ensure backfill has placed it.
    await client.get(f"/api/projects/{pid}/kb/tree")

    r = await client.patch(
        f"/api/projects/{pid}/kb/items/{item_id}/folder",
        json={"folder_id": f1["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["folder_id"] == f1["id"]

    # A non-owner member can also move. Register + add as plain member.
    bob = await _register(client, "kh_bob")
    await _add_member(maker, pid, bob, role="member", license_tier="full")
    await _login(client, "kh_bob")
    r = await client.patch(
        f"/api/projects/{pid}/kb/items/{item_id}/folder",
        json={"folder_id": root_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["folder_id"] == root_id


@pytest.mark.asyncio
async def test_cycle_detection(api_env):
    """Case 4: reparenting a folder under its own descendant → 409."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner4")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    r = await client.get(f"/api/projects/{pid}/kb/tree")
    root_id = r.json()["root_id"]
    a = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "A", "parent_folder_id": root_id},
        )
    ).json()["folder"]
    b = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "B", "parent_folder_id": a["id"]},
        )
    ).json()["folder"]
    c = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "C", "parent_folder_id": b["id"]},
        )
    ).json()["folder"]

    # A → C would create a cycle (C is a descendant of A).
    r = await client.patch(
        f"/api/projects/{pid}/kb/folders/{a['id']}/parent",
        json={"new_parent_id": c["id"]},
    )
    assert r.status_code == 409
    # Self-parent is also a cycle.
    r = await client.patch(
        f"/api/projects/{pid}/kb/folders/{a['id']}/parent",
        json={"new_parent_id": a["id"]},
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_license_inherit_vs_override(api_env):
    """Case 5: absence of override = inherit; set override; clear override."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner5")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    item_id = await _seed_item(
        maker,
        project_id=pid,
        summary="secret spec",
        source_identifier="https://example.com/secret",
    )

    # No override yet → tree payload has override=None.
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    items = r.json()["items"]
    target = next(i for i in items if i["id"] == item_id)
    assert target["license_tier_override"] is None

    # Set observer override.
    r = await client.put(
        f"/api/projects/{pid}/kb/items/{item_id}/license",
        json={"license_tier": "observer"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["license_tier"] == "observer"

    # Tree reflects it.
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    target = next(
        i for i in r.json()["items"] if i["id"] == item_id
    )
    assert target["license_tier_override"] == "observer"

    # Invalid tier rejected.
    r = await client.put(
        f"/api/projects/{pid}/kb/items/{item_id}/license",
        json={"license_tier": "superuser"},
    )
    assert r.status_code == 400

    # Clear by passing null.
    r = await client.put(
        f"/api/projects/{pid}/kb/items/{item_id}/license",
        json={"license_tier": None},
    )
    assert r.status_code == 200
    r = await client.get(f"/api/projects/{pid}/kb/tree")
    target = next(
        i for i in r.json()["items"] if i["id"] == item_id
    )
    assert target["license_tier_override"] is None

    # Plain member cannot set license (owner-only).
    alice = await _register(client, "kh_alice5")
    await _add_member(
        maker, pid, alice, role="member", license_tier="full"
    )
    await _login(client, "kh_alice5")
    r = await client.put(
        f"/api/projects/{pid}/kb/items/{item_id}/license",
        json={"license_tier": "observer"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_nonempty(api_env):
    """Case 6: delete on non-empty folder → 409; delete on empty → ok."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner6")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    r = await client.get(f"/api/projects/{pid}/kb/tree")
    root_id = r.json()["root_id"]
    parent = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "parent", "parent_folder_id": root_id},
        )
    ).json()["folder"]
    child = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "child", "parent_folder_id": parent["id"]},
        )
    ).json()["folder"]

    # Non-empty (has child folder) → 409.
    r = await client.delete(
        f"/api/projects/{pid}/kb/folders/{parent['id']}"
    )
    assert r.status_code == 409

    # Seed an item into `child`, then try to delete `child`.
    item_id = await _seed_item(
        maker,
        project_id=pid,
        summary="seedling",
        source_identifier="https://example.com/seed",
    )
    await client.patch(
        f"/api/projects/{pid}/kb/items/{item_id}/folder",
        json={"folder_id": child["id"]},
    )
    r = await client.delete(
        f"/api/projects/{pid}/kb/folders/{child['id']}"
    )
    assert r.status_code == 409

    # Move the item out, then child is empty and delete succeeds.
    await client.patch(
        f"/api/projects/{pid}/kb/items/{item_id}/folder",
        json={"folder_id": root_id},
    )
    r = await client.delete(
        f"/api/projects/{pid}/kb/folders/{child['id']}"
    )
    assert r.status_code == 200, r.text

    # Root cannot be deleted even when empty.
    # Clear parent + item first so only root is left.
    r = await client.delete(
        f"/api/projects/{pid}/kb/folders/{parent['id']}"
    )
    assert r.status_code == 200
    r = await client.delete(
        f"/api/projects/{pid}/kb/folders/{root_id}"
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_tree_structure_two_level(api_env):
    """Case 7: tree endpoint returns a 2-level hierarchy with items at
    each level, and the payload can be rebuilt into the expected tree.
    """
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "kh_owner7")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")

    r = await client.get(f"/api/projects/{pid}/kb/tree")
    root_id = r.json()["root_id"]
    design = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "design", "parent_folder_id": root_id},
        )
    ).json()["folder"]
    engineering = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "engineering", "parent_folder_id": root_id},
        )
    ).json()["folder"]
    mocks = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "mocks", "parent_folder_id": design["id"]},
        )
    ).json()["folder"]
    apis = (
        await client.post(
            f"/api/projects/{pid}/kb/folders",
            json={"name": "apis", "parent_folder_id": engineering["id"]},
        )
    ).json()["folder"]

    # Two items under level-2 folders + one under root.
    a_id = await _seed_item(
        maker,
        project_id=pid,
        summary="hero mock",
        source_identifier="https://example.com/hero",
    )
    b_id = await _seed_item(
        maker,
        project_id=pid,
        summary="openapi spec",
        source_identifier="https://example.com/oas",
    )
    c_id = await _seed_item(
        maker,
        project_id=pid,
        summary="root artefact",
        source_identifier="https://example.com/root",
    )
    # Backfill sweeps them into root; move two of them down.
    await client.get(f"/api/projects/{pid}/kb/tree")
    await client.patch(
        f"/api/projects/{pid}/kb/items/{a_id}/folder",
        json={"folder_id": mocks["id"]},
    )
    await client.patch(
        f"/api/projects/{pid}/kb/items/{b_id}/folder",
        json={"folder_id": apis["id"]},
    )

    r = await client.get(f"/api/projects/{pid}/kb/tree")
    assert r.status_code == 200, r.text
    body = r.json()
    folders = body["folders"]
    items = body["items"]
    assert len(folders) == 5  # root + design + engineering + mocks + apis

    folder_ids = {f["id"] for f in folders}
    assert {
        root_id,
        design["id"],
        engineering["id"],
        mocks["id"],
        apis["id"],
    } == folder_ids

    # Rebuild the tree locally and verify edges.
    children_of: dict[str, list[str]] = {}
    for f in folders:
        children_of.setdefault(f["parent_folder_id"], []).append(f["id"])
    # root has two children (design, engineering)
    assert sorted(children_of[root_id]) == sorted(
        [design["id"], engineering["id"]]
    )
    assert children_of[design["id"]] == [mocks["id"]]
    assert children_of[engineering["id"]] == [apis["id"]]

    # Items mapped to the right folders.
    item_by_id = {i["id"]: i for i in items}
    assert item_by_id[a_id]["folder_id"] == mocks["id"]
    assert item_by_id[b_id]["folder_id"] == apis["id"]
    assert item_by_id[c_id]["folder_id"] == root_id
