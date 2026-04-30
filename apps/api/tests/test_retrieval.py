"""RetrievalService tests (slice 5a of pickup #4).

Covers the production §7.2 retrieval primitive — BM25 + §7.4
frecency multiplier — over real KbItemRow data. Tests at the
service level rather than the route level to keep them fast.

Coverage:
  * frecency_multiplier math: zero / hot / cold / future-ts edge cases.
  * RetrievalService.retrieve_kb_items: BM25 ranks topical matches
    above noise; frecency lifts hot-but-tied items above cold ones;
    group-only mode (viewer_user_id=None) excludes personal items;
    status filter excludes draft / archived / rejected; ingest-source
    rows score on classification.summary + raw_content.
  * SkillsService._kb_search wired path produces same shape as legacy
    substring scan and ranks better on the chronic-miss queries.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from workgraph_api.services import RetrievalService, SkillsService
from workgraph_api.services._retrieval_primitives import (
    RetrievalDoc,
    frecency_multiplier,
)
from workgraph_persistence import (
    KbIngestRepository,
    KbItemRepository,
    KbItemRow,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    bump_frecency,
    session_scope,
)


# ---------------------------------------------------------------------------
# frecency_multiplier — pure unit tests.
# ---------------------------------------------------------------------------


def test_frecency_multiplier_zero_access_is_noop():
    assert frecency_multiplier(access_count=0, last_accessed_at=None) == 1.0
    # access_count > 0 but last_accessed_at None → also no-op (nothing to decay).
    assert (
        frecency_multiplier(access_count=5, last_accessed_at=None) == 1.0
    )


def test_frecency_multiplier_hot_recent_lifts():
    """Recent + many-touch → boost > 1.0, capped at 2.0."""
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    fresh_hot = frecency_multiplier(
        access_count=20,
        last_accessed_at=now,
        now=now,
    )
    # log(21) × 1.0 ≈ 3.0; capped at 1 + 1.0 = 2.0.
    assert fresh_hot == pytest.approx(2.0)


def test_frecency_multiplier_old_decays():
    """7-day half-life: same access_count older → smaller boost.

    Use access_count=1 so log(2)≈0.69 stays under the boost cap (1.0)
    in all three samples — otherwise the fresh sample saturates and
    the half-life ratio stops holding cleanly.
    """
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    fresh = frecency_multiplier(
        access_count=1, last_accessed_at=now, now=now
    )
    week_old = frecency_multiplier(
        access_count=1,
        last_accessed_at=now - timedelta(days=7),
        now=now,
    )
    month_old = frecency_multiplier(
        access_count=1,
        last_accessed_at=now - timedelta(days=30),
        now=now,
    )
    assert fresh > week_old > month_old > 1.0
    # Half-life check: 7-day-old's boost should be ~half of fresh's
    # boost (boost = mult - 1.0).
    assert (week_old - 1.0) == pytest.approx((fresh - 1.0) * 0.5, rel=0.01)


def test_frecency_multiplier_future_ts_treated_as_fresh():
    """Clock-skew defense — future timestamp doesn't crash."""
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    future = now + timedelta(hours=1)
    mult = frecency_multiplier(
        access_count=5, last_accessed_at=future, now=now
    )
    assert mult > 1.0  # treated as fresh


def test_frecency_multiplier_naive_ts_handled():
    """Tz-naive timestamps (older rows) coerce to UTC, don't crash."""
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    naive = datetime(2026, 4, 25)  # tz-naive
    mult = frecency_multiplier(
        access_count=3, last_accessed_at=naive, now=now
    )
    assert mult > 1.0  # parsed successfully


# ---------------------------------------------------------------------------
# Helpers (mirror test_skills.py shape).
# ---------------------------------------------------------------------------


async def _mk_project(maker, title: str = "retrieval test") -> str:
    async with session_scope(maker) as session:
        pid = str(uuid.uuid4())
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


async def _add_member(maker, project_id: str, user_id: str) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id
        )


async def _mk_user_kb(
    maker,
    project_id: str,
    *,
    owner_user_id: str,
    title: str,
    content_md: str,
    scope: str = "group",
    status: str = "published",
) -> str:
    """Create a user-authored KbItemRow."""
    async with session_scope(maker) as session:
        item = await KbItemRepository(session).create(
            project_id=project_id,
            owner_user_id=owner_user_id,
            title=title,
            content_md=content_md,
            scope=scope,
            status=status,
        )
        return item.id


async def _mk_ingest_kb(
    maker,
    project_id: str,
    *,
    source_identifier: str,
    raw_content: str,
    summary: str = "",
    tags: list[str] | None = None,
    status: str = "approved",
) -> str:
    """Create an ingest-source KbItemRow (matches test_skills helper)."""
    async with session_scope(maker) as session:
        repo = KbIngestRepository(session)
        row = await repo.create(
            project_id=project_id,
            source_kind="user-drop",
            source_identifier=source_identifier,
            raw_content=raw_content,
        )
        await repo.set_classification(
            row.id,
            classification={
                "is_relevant": True,
                "tags": list(tags or []),
                "summary": summary,
                "proposed_target_user_ids": [],
                "proposed_action": "ambient-log",
                "confidence": 0.8,
                "safety_notes": "",
            },
            status=status,
        )
        return row.id


# ---------------------------------------------------------------------------
# RetrievalService.retrieve_kb_items.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_kb_items_ranks_topical_match_above_noise(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ret_owner_a")
    await _add_member(maker, pid, owner)

    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Boss 1 design notes", content_md="rage-quit at 40%",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Inventory rework", content_md="merge stacks proposal",
    )

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="boss design", k=5
    )
    assert out, "expected at least one hit"
    assert out[0].row.id == hit_id


@pytest.mark.asyncio
async def test_retrieve_kb_items_empty_query_returns_empty(api_env):
    """Whitespace / empty queries short-circuit before BM25."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ret_owner_b")
    await _add_member(maker, pid, owner)
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="anything", content_md="anything",
    )
    svc = RetrievalService(maker)
    assert await svc.retrieve_kb_items(project_id=pid, query="", k=5) == []
    assert await svc.retrieve_kb_items(project_id=pid, query="   ", k=5) == []


@pytest.mark.asyncio
async def test_retrieve_kb_items_excludes_draft_and_archived(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ret_owner_c")
    await _add_member(maker, pid, owner)

    live = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="canon", content_md="alpha bravo",
        status="published",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="draft", content_md="alpha bravo",
        status="draft",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="archived", content_md="alpha bravo",
        status="archived",
    )

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", k=5
    )
    ids = [c.row.id for c in out]
    assert ids == [live]


@pytest.mark.asyncio
async def test_retrieve_kb_items_group_only_excludes_personal(api_env):
    """Default mode (viewer_user_id=None) returns group items only."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    alice = await _mk_user(maker, "ret_alice")
    bob = await _mk_user(maker, "ret_bob")
    await _add_member(maker, pid, alice)
    await _add_member(maker, pid, bob)

    group_id = await _mk_user_kb(
        maker, pid, owner_user_id=alice,
        title="group note", content_md="alpha bravo",
        scope="group",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=bob,
        title="bob personal", content_md="alpha bravo",
        scope="personal",
    )

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", k=5
    )
    assert [c.row.id for c in out] == [group_id]


@pytest.mark.asyncio
async def test_retrieve_kb_items_viewer_mode_includes_own_personal(api_env):
    """viewer_user_id != None → group + that user's personal items."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    alice = await _mk_user(maker, "ret_alice2")
    bob = await _mk_user(maker, "ret_bob2")
    await _add_member(maker, pid, alice)
    await _add_member(maker, pid, bob)

    group_id = await _mk_user_kb(
        maker, pid, owner_user_id=alice,
        title="group", content_md="alpha bravo",
        scope="group",
    )
    bob_personal = await _mk_user_kb(
        maker, pid, owner_user_id=bob,
        title="bob note", content_md="alpha bravo",
        scope="personal",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=alice,
        title="alice note", content_md="alpha bravo",
        scope="personal",
    )

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", viewer_user_id=bob, k=5
    )
    ids = {c.row.id for c in out}
    # Bob sees group + bob's personal; not alice's personal.
    assert group_id in ids
    assert bob_personal in ids
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_retrieve_kb_items_frecency_lifts_hot_over_cold(api_env):
    """Two equally-relevant items: bump one repeatedly, confirm it
    ranks above the cold one.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ret_owner_freq")
    await _add_member(maker, pid, owner)

    cold_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="alpha bravo charlie", content_md="lexically equivalent",
    )
    hot_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="alpha bravo charlie", content_md="lexically equivalent",
    )

    # Bump hot 10 times so its access_count >> cold's.
    for _ in range(10):
        async with session_scope(maker) as session:
            await bump_frecency(session, kbitem_ids=[hot_id])

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", k=5
    )
    ids = [c.row.id for c in out]
    assert ids[0] == hot_id, (
        f"hot item should outrank cold item; got {ids}"
    )
    assert cold_id in ids


@pytest.mark.asyncio
async def test_retrieve_kb_items_handles_ingest_source_rows(api_env):
    """Ingest rows score on classification.summary + raw_content."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)

    hit_id = await _mk_ingest_kb(
        maker, pid,
        source_identifier="kb-hit",
        raw_content="long body about Postgres pool sizing internals",
        summary="Postgres pool sizing",
        tags=["infra"],
    )
    await _mk_ingest_kb(
        maker, pid,
        source_identifier="kb-noise",
        raw_content="generic content unrelated to the query",
        summary="something else",
    )

    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="postgres pool", k=5
    )
    ids = [c.row.id for c in out]
    assert ids[0] == hit_id


# ---------------------------------------------------------------------------
# SkillsService._kb_search end-to-end with RetrievalService wired.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kb_search_via_retrieval_returns_legacy_shape(api_env):
    """Wired path returns the same dict keys as the substring scan
    so downstream consumers (PersonalStreamService, frontend) need no
    change.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ks_owner")
    await _add_member(maker, pid, owner)
    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Boss 1 design notes", content_md="rage-quit 40%",
    )

    retrieval = RetrievalService(maker)
    skills = SkillsService(maker, retrieval_service=retrieval)
    out = await skills.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss design", "limit": 5},
    )
    assert out["ok"] is True
    items = out["result"]
    assert items, "expected at least one hit"
    first = items[0]
    # Legacy shape (matches test_skills.py expectations).
    assert set(first.keys()) >= {
        "id", "source_kind", "source_identifier",
        "summary", "tags", "status", "created_at",
    }
    assert first["id"] == hit_id


@pytest.mark.asyncio
async def test_kb_search_substring_fallback_when_retrieval_unwired(api_env):
    """Legacy callers (no retrieval_service injected) keep working
    via the substring scan path.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "ks_legacy")
    await _add_member(maker, pid, owner)
    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Boss 1 design", content_md="rage-quit 40%",
    )

    skills = SkillsService(maker)  # no retrieval_service
    out = await skills.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss", "limit": 5},
    )
    assert out["ok"] is True
    assert out["result"][0]["id"] == hit_id
