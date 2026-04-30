"""RetrievalService tests (slices 5a + 5b of pickup #4).

Covers the production §7.2 retrieval primitive — BM25 + §7.4
frecency multiplier (slice 5a) plus optional vector retrieval +
RRF (slice 5b) — over real KbItemRow data.

Coverage (slice 5a):
  * frecency_multiplier math: zero / hot / cold / future-ts edge cases.
  * RetrievalService.retrieve_kb_items BM25 path: topical ranking,
    empty-query short-circuit, status filter, group-only vs viewer
    visibility, frecency lift, ingest-row adapter.
  * SkillsService._kb_search wired path returns legacy shape;
    substring fallback when unwired.

Coverage (slice 5b):
  * RetrievalService BM25+vector RRF path: stub embedding client
    returns deterministic vectors; verify mode='bm25+vector' on
    candidates and that the RRF result composes the two rank lists.
  * Cache miss > _INLINE_EMBED_CAP → graceful fallback to BM25-only.
  * Embedding client raising → graceful fallback (no crash).
  * warm_kb_items() pre-populates the cache.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from workgraph_api.services import RetrievalService, SkillsService
from workgraph_api.services._embeddings import EmbeddingClient, content_hash
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


# ---------------------------------------------------------------------------
# Slice 5b — vector retrieval + RRF.
# ---------------------------------------------------------------------------


class _StubEmbeddingClient:
    """Deterministic embedding stub for tests — no network calls.

    Embeds each text into a fixed-dim vector by hashing into 8 floats
    in [0, 1]. Same text → same vector across runs (cache stable).
    Different texts produce different vectors so cosine similarity
    has signal. Texts that share a prefix produce similar vectors,
    which is enough to validate the RRF wiring.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_batch(
        self, texts: Sequence[str]
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            # 8-dim vector, each component a float in [0, 1].
            out.append([digest[i] / 255.0 for i in range(8)])
        return out


class _ExactSemanticEmbeddingClient:
    """Embedding stub where ONLY texts with the same prefix are similar.

    Used by the RRF "vector finds something BM25 missed" test. Maps
    texts that start with `q_prefix` to a fixed direction; everything
    else to an orthogonal direction.
    """

    def __init__(self, q_prefix: str) -> None:
        self._q_prefix = q_prefix

    async def embed_batch(
        self, texts: Sequence[str]
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            if text.lower().startswith(self._q_prefix.lower()):
                out.append([1.0, 0.0, 0.0, 0.0])
            else:
                out.append([0.0, 1.0, 0.0, 0.0])
        return out


def _stub_cache_path(tmp_path: Path) -> Path:
    """Per-test isolated cache file under pytest's tmp_path."""
    return tmp_path / "kb_items.json"


@pytest.mark.asyncio
async def test_retrieve_uses_vector_rrf_when_client_wired(api_env, tmp_path):
    """When embedding client + cache wired, mode='bm25+vector'."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "rrf_owner")
    await _add_member(maker, pid, owner)
    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Postgres pool sizing", content_md="canonical sizing doc",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Inventory rework", content_md="merge stacks proposal",
    )

    svc = RetrievalService(
        maker,
        embedding_client=_StubEmbeddingClient(),
        cache_path=_stub_cache_path(tmp_path),
    )
    out = await svc.retrieve_kb_items(
        project_id=pid, query="postgres pool sizing", k=5
    )
    assert out, "expected at least one hit"
    # Top hit is the topically-relevant doc (BM25 and vector both rank it).
    assert out[0].row.id == hit_id
    # Mode signals the vector layer participated.
    assert out[0].retrieval_mode == "bm25+vector"


@pytest.mark.asyncio
async def test_vector_layer_falls_back_to_bm25_when_cache_too_cold(
    api_env, tmp_path,
):
    """When inline embed would exceed _INLINE_EMBED_CAP docs, fall back."""
    from workgraph_api.services.retrieval import _INLINE_EMBED_CAP

    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "cap_owner")
    await _add_member(maker, pid, owner)

    # Seed more docs than the inline cap so cache misses force BM25-only.
    n_docs = _INLINE_EMBED_CAP + 5
    for i in range(n_docs):
        await _mk_user_kb(
            maker, pid, owner_user_id=owner,
            title=f"alpha {i}", content_md=f"bravo {i}",
        )

    stub = _StubEmbeddingClient()
    svc = RetrievalService(
        maker,
        embedding_client=stub,
        cache_path=_stub_cache_path(tmp_path),
    )
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", k=5
    )
    assert out, "expected hits"
    # Above the inline cap → vector layer skipped.
    assert all(c.retrieval_mode == "bm25" for c in out)
    # Embedding client never called because cache-miss check ran first.
    assert stub.calls == []


@pytest.mark.asyncio
async def test_vector_layer_falls_back_when_client_raises(api_env, tmp_path):
    """A flaky embedding API doesn't break retrieval."""

    class _ExplodingClient:
        async def embed_batch(self, texts):
            raise RuntimeError("simulated SF outage")

    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "boom_owner")
    await _add_member(maker, pid, owner)
    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="alpha", content_md="bravo",
    )

    svc = RetrievalService(
        maker,
        embedding_client=_ExplodingClient(),
        cache_path=_stub_cache_path(tmp_path),
    )
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", k=5
    )
    # Falls back to BM25-only — caller still gets ranked results.
    assert out
    assert out[0].row.id == hit_id
    assert out[0].retrieval_mode == "bm25"


@pytest.mark.asyncio
async def test_vector_recovers_semantic_match_bm25_misses(api_env, tmp_path):
    """RRF surfaces a doc that BM25 ranks low but vector ranks high.

    The query and the target doc share NO surface tokens (BM25 score 0
    for the target). The semantic stub treats the query and target as
    same-direction; everything else as orthogonal. Without RRF the
    target wouldn't appear.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "sem_owner")
    await _add_member(maker, pid, owner)
    # Target shares the embedding prefix with the query but no
    # tokens. BM25 ranks zero; vector ranks first.
    target_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="postgres connection pool sizing",
        content_md="recommended values",
    )
    # Lexical match on the query but semantically unrelated under
    # the stub embedding (different prefix).
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="alpha bravo", content_md="alpha bravo",
    )

    # Embedding stub: anything starting with "postgres" is one
    # semantic cluster; anything else is orthogonal.
    svc = RetrievalService(
        maker,
        embedding_client=_ExactSemanticEmbeddingClient("postgres"),
        cache_path=_stub_cache_path(tmp_path),
    )
    out = await svc.retrieve_kb_items(
        project_id=pid, query="postgres connection management", k=5
    )
    ids = [c.row.id for c in out]
    assert target_id in ids, f"vector layer should surface {target_id}; got {ids}"


@pytest.mark.asyncio
async def test_warm_kb_items_populates_cache(api_env, tmp_path):
    """warm_kb_items eagerly embeds every kb item into the cache."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "warm_owner")
    await _add_member(maker, pid, owner)
    for i in range(3):
        await _mk_user_kb(
            maker, pid, owner_user_id=owner,
            title=f"doc {i}", content_md=f"body {i}",
        )

    stub = _StubEmbeddingClient()
    cache_path = _stub_cache_path(tmp_path)
    svc = RetrievalService(
        maker, embedding_client=stub, cache_path=cache_path
    )
    n_written = await svc.warm_kb_items(project_id=pid)
    assert n_written == 3, "all three docs should be embedded fresh"

    # Second warm is a no-op.
    n_written_again = await svc.warm_kb_items(project_id=pid)
    assert n_written_again == 0

    # Cache file exists on disk and has the three entries.
    assert cache_path.exists()
    import json
    on_disk = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(on_disk) == 3


@pytest.mark.asyncio
async def test_warm_kb_items_no_op_without_embedding_client(api_env, tmp_path):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "warm_no_client")
    await _add_member(maker, pid, owner)
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="doc", content_md="body",
    )
    svc = RetrievalService(
        maker, cache_path=_stub_cache_path(tmp_path)
    )
    assert await svc.warm_kb_items(project_id=pid) == 0


# ---------------------------------------------------------------------------
# Slice 5c — candidate_set + kb_slice in EdgeAgent context.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_set_returns_kb_slice_shape(api_env):
    """RetrievalService.candidate_set returns the kb_slice prompt shape."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "cand_owner")
    await _add_member(maker, pid, owner)
    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Postgres pool sizing",
        content_md="canonical sizing doc with details",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="Inventory rework", content_md="merge stacks proposal",
    )

    svc = RetrievalService(maker)
    out = await svc.candidate_set(
        project_id=pid, query="postgres pool sizing", k=3
    )
    assert out, "expected at least one candidate"
    assert out[0]["id"] == hit_id
    # kb_slice shape (matches edge/v1.md prompt contract).
    assert set(out[0].keys()) == {"id", "source", "excerpt"}
    assert out[0]["source"] in {"kb-note", "kb-personal"}
    assert "Postgres pool sizing" in out[0]["excerpt"]


@pytest.mark.asyncio
async def test_candidate_set_for_ingest_uses_source_kind(api_env):
    """Ingest-source kb items report their source_kind, not 'kb-note'."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    await _mk_ingest_kb(
        maker, pid,
        source_identifier="kb-feishu-1",
        raw_content="canonical reply about Postgres connection pool",
        summary="Postgres pool sizing canonical",
    )
    svc = RetrievalService(maker)
    out = await svc.candidate_set(
        project_id=pid, query="postgres pool", k=3
    )
    assert out
    assert out[0]["source"] == "user-drop"


@pytest.mark.asyncio
async def test_candidate_set_empty_query_returns_empty(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "cand_empty")
    await _add_member(maker, pid, owner)
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="something", content_md="anything",
    )
    svc = RetrievalService(maker)
    assert await svc.candidate_set(project_id=pid, query="", k=5) == []


@pytest.mark.asyncio
async def test_personal_post_pre_fills_kb_slice_in_context(api_env):
    """Slice 5c — _build_respond_context pre-fills kb_slice with
    retrieval candidates for the user's message body.

    Wires a scriptable EdgeAgent stub to capture the context dict it
    receives. Asserts kb_slice carries the topical match.
    """
    from workgraph_agents import EdgeResponse, EdgeResponseOutcome
    from workgraph_agents.llm import LLMResult
    from workgraph_api.main import app
    from workgraph_api.services import PersonalStreamService
    from workgraph_persistence import backfill_streams_from_projects

    client, maker, bus, *_ = api_env

    class _CapturingEdgeAgent:
        def __init__(self):
            self.calls: list[dict] = []

        async def respond(self, *, user_message, context):
            self.calls.append(
                {"user_message": user_message, "context": context}
            )
            return EdgeResponseOutcome(
                response=EdgeResponse(
                    kind="silence", body=None, route_targets=[]
                ),
                result=LLMResult(
                    content="", model="stub",
                    prompt_tokens=0, completion_tokens=0, latency_ms=0,
                ),
                outcome="ok",
                attempts=1,
            )

    stub = _CapturingEdgeAgent()
    retrieval = RetrievalService(maker)
    app.state.personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
        retrieval_service=retrieval,
    )

    # Register caller, intake a project, seed a topical kb item.
    r = await client.post(
        "/api/auth/register",
        json={"username": "kbslice_user", "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/intake/message",
        json={
            "text": (
                "We need to launch an event registration page next week. "
                "It needs invitation code validation, phone number "
                "validation, admin export, and conversion tracking."
            ),
            "source_event_id": "kbslice-1",
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    me = (await client.get("/api/auth/me")).json()["id"]
    await backfill_streams_from_projects(maker)

    hit_id = await _mk_user_kb(
        maker, pid, owner_user_id=me,
        title="Postgres pool sizing", content_md="canonical sizing doc",
    )
    await _mk_user_kb(
        maker, pid, owner_user_id=me,
        title="Inventory rework", content_md="merge stacks proposal",
    )

    r = await client.post(
        f"/api/personal/{pid}/post",
        json={"body": "what's the postgres pool sizing recommendation?"},
    )
    assert r.status_code == 200, r.text
    assert stub.calls, "edge agent should have been called"
    ctx = stub.calls[0]["context"]
    assert "kb_slice" in ctx
    kb_slice = ctx["kb_slice"]
    assert kb_slice, f"expected kb_slice populated; got {kb_slice}"
    assert kb_slice[0]["id"] == hit_id
    assert "Postgres pool sizing" in kb_slice[0]["excerpt"]


@pytest.mark.asyncio
async def test_retrieve_kb_items_allowed_scopes_filter(api_env):
    """`allowed_scopes` drops rows whose scope isn't in the set."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    alice = await _mk_user(maker, "as_alice_filter")
    await _add_member(maker, pid, alice)

    group_id = await _mk_user_kb(
        maker, pid, owner_user_id=alice,
        title="alpha bravo", content_md="group note",
        scope="group",
    )
    personal_id = await _mk_user_kb(
        maker, pid, owner_user_id=alice,
        title="alpha bravo", content_md="alice's personal note",
        scope="personal",
    )

    svc = RetrievalService(maker)
    # Pull both via viewer mode so personal is in the candidate pool.
    no_filter = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", viewer_user_id=alice, k=5
    )
    assert {c.row.id for c in no_filter} == {group_id, personal_id}

    # group-only filter drops the personal item.
    group_only = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", viewer_user_id=alice,
        allowed_scopes=frozenset({"group"}), k=5,
    )
    assert {c.row.id for c in group_only} == {group_id}

    # personal-only filter drops the group item.
    personal_only = await svc.retrieve_kb_items(
        project_id=pid, query="alpha", viewer_user_id=alice,
        allowed_scopes=frozenset({"personal"}), k=5,
    )
    assert {c.row.id for c in personal_only} == {personal_id}


@pytest.mark.asyncio
async def test_retrieve_kb_items_empty_allowed_scopes_returns_empty(api_env):
    """Empty allowed_scopes set is meaningful: drop everything."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user(maker, "as_empty_set")
    await _add_member(maker, pid, owner)
    await _mk_user_kb(
        maker, pid, owner_user_id=owner,
        title="alpha", content_md="bravo",
    )
    svc = RetrievalService(maker)
    out = await svc.retrieve_kb_items(
        project_id=pid, query="alpha",
        allowed_scopes=frozenset(),  # explicitly empty
        k=5,
    )
    assert out == []


@pytest.mark.asyncio
async def test_personal_post_kb_slice_respects_scope_tiers(api_env):
    """End-to-end: ScopeTierPills selection narrows kb_slice.

    Wires a scriptable EdgeAgent stub and asserts kb_slice contains
    only items whose scope intersects the toggled-on pills (taking
    the viewer's licensed tiers into account).
    """
    from workgraph_agents import EdgeResponse, EdgeResponseOutcome
    from workgraph_agents.llm import LLMResult
    from workgraph_api.main import app
    from workgraph_api.services import (
        LicenseContextService,
        PersonalStreamService,
    )
    from workgraph_persistence import (
        ProjectMemberRepository,
        backfill_streams_from_projects,
    )

    client, maker, bus, *_ = api_env

    captured: list[dict] = []

    class _CapturingEdgeAgent:
        async def respond(self, *, user_message, context):
            captured.append({"context": context})
            return EdgeResponseOutcome(
                response=EdgeResponse(
                    kind="silence", body=None, route_targets=[]
                ),
                result=LLMResult(
                    content="", model="stub",
                    prompt_tokens=0, completion_tokens=0, latency_ms=0,
                ),
                outcome="ok",
                attempts=1,
            )

    stub = _CapturingEdgeAgent()
    retrieval = RetrievalService(maker)
    license_ctx = LicenseContextService(maker)
    app.state.personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
        retrieval_service=retrieval,
        license_context_service=license_ctx,
    )

    # Register the caller AFTER the personal_service swap so they're
    # the one whose scope_tiers we'll exercise.
    r = await client.post(
        "/api/auth/register",
        json={"username": "pills_user", "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    me = (await client.get("/api/auth/me")).json()["id"]
    r = await client.post(
        "/api/intake/message",
        json={
            "text": (
                "We need to launch an event registration page next week. "
                "It needs invitation code validation, phone number "
                "validation, admin export, and conversion tracking."
            ),
            "source_event_id": "pills-1",
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    await backfill_streams_from_projects(maker)

    # Pin the caller to full-tier so the pill intersection is the
    # only constraint that matters.
    async with session_scope(maker) as session:
        rows = await ProjectMemberRepository(session).list_for_project(pid)
        for m in rows:
            if m.user_id == me:
                m.license_tier = "full"
        await session.flush()

    group_id = await _mk_user_kb(
        maker, pid, owner_user_id=me,
        title="alpha bravo", content_md="group canon",
        scope="group",
    )
    department_id = await _mk_user_kb(
        maker, pid, owner_user_id=me,
        title="alpha bravo", content_md="dept-wide note",
        scope="department",
    )

    # Pills: group ON, all others OFF. Expected kb_slice = group only.
    r = await client.post(
        f"/api/personal/{pid}/post",
        json={
            "body": "what about alpha bravo?",
            "scope_tiers": {
                "personal": False,
                "group": True,
                "department": False,
                "enterprise": False,
            },
        },
    )
    assert r.status_code == 200, r.text
    assert captured, "edge agent should have been called"
    kb_slice = captured[-1]["context"]["kb_slice"]
    ids = [c["id"] for c in kb_slice]
    assert group_id in ids, f"group item should pass; got {ids}"
    assert department_id not in ids, (
        f"department item should be filtered out by pills; got {ids}"
    )


@pytest.mark.asyncio
async def test_personal_post_kb_slice_empty_when_no_retrieval_service(
    api_env,
):
    """Without retrieval_service wired, kb_slice ships empty (legacy)."""
    from workgraph_agents import EdgeResponse, EdgeResponseOutcome
    from workgraph_agents.llm import LLMResult
    from workgraph_api.main import app
    from workgraph_api.services import PersonalStreamService
    from workgraph_persistence import backfill_streams_from_projects

    client, maker, bus, *_ = api_env

    class _CapturingEdgeAgent:
        def __init__(self):
            self.calls = []

        async def respond(self, *, user_message, context):
            self.calls.append({"context": context})
            return EdgeResponseOutcome(
                response=EdgeResponse(
                    kind="silence", body=None, route_targets=[]
                ),
                result=LLMResult(
                    content="", model="stub",
                    prompt_tokens=0, completion_tokens=0, latency_ms=0,
                ),
                outcome="ok",
                attempts=1,
            )

    stub = _CapturingEdgeAgent()
    app.state.personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
        # NO retrieval_service
    )

    r = await client.post(
        "/api/auth/register",
        json={"username": "noretr_user", "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/intake/message",
        json={
            "text": (
                "We need to launch an event registration page next week. "
                "It needs invitation code validation, phone number "
                "validation, admin export, and conversion tracking."
            ),
            "source_event_id": "noretr-1",
        },
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{pid}/post",
        json={"body": "anything"},
    )
    assert r.status_code == 200, r.text
    ctx = stub.calls[0]["context"]
    # Field is present (uniform shape) but empty since no retrieval.
    assert ctx.get("kb_slice") == []
