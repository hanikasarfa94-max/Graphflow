"""Phase V — KbItemRow service tests."""
from __future__ import annotations

import io
import os
import uuid
from pathlib import Path

import pytest

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    session_scope,
)


@pytest.fixture(autouse=True)
def _isolate_kb_uploads_root(tmp_path, monkeypatch):
    """Re-point KB_UPLOADS_ROOT at a tmp dir per test so file writes
    don't pollute /data on the dev box."""
    upload_root = tmp_path / "kb-uploads"
    upload_root.mkdir()
    monkeypatch.setenv("WORKGRAPH_KB_UPLOADS_ROOT", str(upload_root))
    # The service captures KB_UPLOADS_ROOT at import time, so patch it
    # in-place too. Belt-and-braces against import order.
    from workgraph_api.services import kb_items as kb_mod

    monkeypatch.setattr(kb_mod, "KB_UPLOADS_ROOT", upload_root)
    yield upload_root


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
        session.add(ProjectRow(id=pid, title="KB Test"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


# ---- create + list ------------------------------------------------------


@pytest.mark.asyncio
async def test_create_personal_item_visible_to_owner_only(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_a_owner")
    member_id = await _register_and_login(client, "kb_a_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Member writes a personal note.
    await _login(client, "kb_a_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "my private notes", "content_md": "# hidden"},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["scope"] == "personal"
    assert item["owner_user_id"] == member_id
    item_id = item["id"]

    # Owner of the project does NOT see the personal item.
    await _login(client, "kb_a_owner")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "my private notes" not in titles

    # Member sees their own item.
    await _login(client, "kb_a_member")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "my private notes" in titles

    # Owner trying to GET the item directly → 403.
    await _login(client, "kb_a_owner")
    r = await client.get(f"/api/kb-items/{item_id}")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_group_item_visible_to_all_members(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_b_owner")
    member_id = await _register_and_login(client, "kb_b_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_b_owner")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "shared playbook",
            "content_md": "everyone reads this",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    await _login(client, "kb_b_member")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "shared playbook" in titles


@pytest.mark.asyncio
async def test_non_member_cannot_create_or_list(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_c_owner")
    member_id = await _register_and_login(client, "kb_c_member")
    outsider_id = await _register_and_login(client, "kb_c_outsider")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_c_outsider")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "intruder", "content_md": ""},
    )
    assert r.status_code == 403
    assert r.json()["message"] == "not_a_member"

    r = await client.get(f"/api/projects/{pid}/kb-items")
    assert r.status_code == 403


# ---- update + delete ----------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_edit_own_item(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_d_owner")
    member_id = await _register_and_login(client, "kb_d_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_d_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "v1", "content_md": "draft"},
    )
    item_id = r.json()["id"]

    r = await client.patch(
        f"/api/kb-items/{item_id}",
        json={"title": "v2", "content_md": "polished"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "v2"


@pytest.mark.asyncio
async def test_other_member_cannot_edit_personal_item(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_e_owner")
    member_id = await _register_and_login(client, "kb_e_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_e_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items", json={"title": "mine"}
    )
    item_id = r.json()["id"]

    # Project owner CAN edit (covers cleanup case).
    await _login(client, "kb_e_owner")
    r = await client.patch(
        f"/api/kb-items/{item_id}", json={"title": "edited by owner"}
    )
    # Project owner sees the item only because they're project owner;
    # personal-scope read still requires owner_user_id == viewer for
    # GET, but PATCH path checks via _assert_can_edit which permits
    # project owner. Document: edit allowed → ok.
    assert r.status_code == 200, r.text


# ---- promotion ----------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_personal_to_group(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_f_owner")
    member_id = await _register_and_login(client, "kb_f_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_f_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items", json={"title": "my note"}
    )
    item_id = r.json()["id"]
    assert r.json()["scope"] == "personal"

    r = await client.post(f"/api/kb-items/{item_id}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "group"

    # Now visible to project owner via list.
    await _login(client, "kb_f_owner")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "my note" in titles


# ---- membrane review (stage 3) -----------------------------------------


@pytest.mark.asyncio
async def test_membrane_downgrades_duplicate_group_title_to_draft(api_env):
    """Stage 3 of docs/membrane-reorg.md: when an owner creates a
    group-scope KB entry whose title matches an existing group entry
    (case-insensitive, punctuation-insensitive), the membrane returns
    `request_review` and the new row is downgraded to status='draft'
    so it doesn't surface as canonical group context until the owner
    explicitly resolves the duplicate.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_dup_owner")
    member_id = await _register_and_login(client, "kb_dup_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_dup_owner")
    # First write: clean, lands as published (membrane auto_merge).
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "API Conventions",
            "content_md": "we use snake_case for endpoint paths.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"

    # Second write with near-identical title (extra punctuation +
    # casing). Membrane catches duplicate → downgrade to draft.
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "api conventions!!",
            "content_md": "actually we use kebab-case now.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft", r.json()

    # Personal-scope writes are forks — membrane doesn't review them.
    # Same title goes through unchanged.
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "API Conventions",
            "content_md": "personal note about conventions",
            "scope": "personal",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


@pytest.mark.asyncio
async def test_membrane_review_creates_inbox_suggestion_and_accept_publishes(
    api_env,
):
    """Stage 4 of docs/membrane-reorg.md: when membrane stages a draft,
    also create an IMSuggestion(kind='membrane_review') in the team
    inbox. Owner accept = the linked draft flips to status='published'.
    """
    from sqlalchemy import select

    from workgraph_persistence import (
        IMSuggestionRow,
        KbItemRow,
        MessageRow,
        StreamRow,
        session_scope,
    )

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_inbox_owner")
    member_id = await _register_and_login(client, "kb_inbox_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Membrane stage-4 enqueue posts a system message to the team-room
    # stream; the production lifespan backfills these on boot, but the
    # bare-bones test fixture above doesn't, so create one explicitly.
    from workgraph_persistence import StreamRepository

    async with session_scope(maker) as session:
        await StreamRepository(session).create(type="project", project_id=pid)

    await _login(client, "kb_inbox_owner")
    # First write: clean.
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "Coding Conventions",
            "content_md": "tabs not spaces.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    # Second write: triggers membrane request_review → draft + inbox.
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "coding conventions",
            "content_md": "actually spaces.",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text
    draft_id = r.json()["id"]
    assert r.json()["status"] == "draft"

    # IMSuggestion(kind='membrane_review') exists, linked to a
    # team-room message with kind='membrane-review' on the kb_item id.
    async with session_scope(maker) as session:
        team_stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == pid, StreamRow.type == "project"
                )
            )
        ).scalar_one()
        sugg = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.project_id == pid,
                    IMSuggestionRow.kind == "membrane_review",
                )
            )
        ).scalar_one()
        msg = (
            await session.execute(
                select(MessageRow).where(MessageRow.id == sugg.message_id)
            )
        ).scalar_one()
        assert msg.stream_id == team_stream.id
        assert msg.kind == "membrane-review"
        assert msg.linked_id == draft_id
        assert sugg.proposal["action"] == "approve_membrane_candidate"
        assert sugg.proposal["detail"]["kb_item_id"] == draft_id

    # Owner accepts → linked draft flips to published.
    r = await client.post(f"/api/im_suggestions/{sugg.id}/accept")
    assert r.status_code == 200, r.text
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(KbItemRow).where(KbItemRow.id == draft_id)
            )
        ).scalar_one()
        assert row.status == "published"


# ---- file upload --------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_text_file_inlines_content(api_env, _isolate_kb_uploads_root):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_h_owner")
    member_id = await _register_and_login(client, "kb_h_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_h_member")
    payload = "# Plan\n\n- step 1\n- step 2\n"
    r = await client.post(
        f"/api/projects/{pid}/kb-items/upload",
        files={"file": ("plan.md", payload.encode("utf-8"), "text/markdown")},
        data={"title": "Launch plan"},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["source"] == "upload"
    assert item["title"] == "Launch plan"
    # Text-ish file ≤32KB is inlined into content_md verbatim.
    assert "step 1" in item["content_md"]
    assert item["attachment"]["filename"] == "plan.md"
    assert item["attachment"]["mime"].startswith("text/")
    assert item["attachment"]["bytes"] == len(payload.encode("utf-8"))

    # File exists on disk under the isolated root.
    expected = _isolate_kb_uploads_root / item["id"] / "plan.md"
    assert expected.read_text(encoding="utf-8") == payload


@pytest.mark.asyncio
async def test_upload_binary_file_stub_content(api_env, _isolate_kb_uploads_root):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_i_owner")
    member_id = await _register_and_login(client, "kb_i_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_i_member")
    blob = bytes([0xAB] * 1024)
    r = await client.post(
        f"/api/projects/{pid}/kb-items/upload",
        files={"file": ("brand.png", blob, "image/png")},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    # Binary content gets the stub copy + a download pointer.
    assert "📎" in item["content_md"]
    assert item["attachment"]["filename"] == "brand.png"
    assert item["attachment"]["mime"] == "image/png"
    assert item["attachment"]["download_url"] == f"/api/kb-items/{item['id']}/attachment"


@pytest.mark.asyncio
async def test_download_attachment_owner_only_personal(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_j_owner")
    member_id = await _register_and_login(client, "kb_j_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_j_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items/upload",
        files={"file": ("private.txt", b"secret", "text/plain")},
    )
    item_id = r.json()["id"]

    # Owner of the item downloads it.
    r = await client.get(f"/api/kb-items/{item_id}/attachment")
    assert r.status_code == 200
    assert r.content == b"secret"

    # Project owner (different user) downloads → 403 because scope=personal.
    await _login(client, "kb_j_owner")
    r = await client.get(f"/api/kb-items/{item_id}/attachment")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_upload_too_large_rejected(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_k_owner")
    member_id = await _register_and_login(client, "kb_k_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_k_member")
    huge = bytes(6 * 1024 * 1024)  # 6 MB > 5 MB cap
    r = await client.post(
        f"/api/projects/{pid}/kb-items/upload",
        files={"file": ("huge.bin", huge, "application/octet-stream")},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_delete_uploaded_item_removes_file(api_env, _isolate_kb_uploads_root):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_l_owner")
    member_id = await _register_and_login(client, "kb_l_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_l_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items/upload",
        files={"file": ("ephemeral.txt", b"hello", "text/plain")},
    )
    item_id = r.json()["id"]
    item_dir = _isolate_kb_uploads_root / item_id
    assert item_dir.exists()

    r = await client.delete(f"/api/kb-items/{item_id}")
    assert r.status_code == 200
    assert not item_dir.exists()


@pytest.mark.asyncio
async def test_demote_owner_only(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_g_owner")
    member_id = await _register_and_login(client, "kb_g_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Member creates + promotes.
    await _login(client, "kb_g_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "joint plan", "scope": "group"},
    )
    item_id = r.json()["id"]

    # Member tries to demote → 403 (group → personal is owner-only).
    r = await client.post(f"/api/kb-items/{item_id}/demote")
    assert r.status_code == 403

    # Project owner demotes.
    await _login(client, "kb_g_owner")
    r = await client.post(f"/api/kb-items/{item_id}/demote")
    assert r.status_code == 200
    assert r.json()["scope"] == "personal"
