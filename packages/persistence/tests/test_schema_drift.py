"""Schema-drift guardrail (M11a).

The deploy model is `create_all` + `alembic stamp head` (see docs/migrations.md),
NOT `alembic upgrade head` from empty (the chain is intentionally not
empty-runnable post-membrane_signals-drop). So the meaningful drift check is:
does the schema `Base.metadata.create_all` produces match what the ORM declares?

This mirrors what a CLEAN `alembic check` reports (stamp is just bookkeeping;
the autogenerate diff is ORM-metadata vs the live create_all schema). It catches
the real M11-class regressions — a server_default that doesn't round-trip, a
column type mismatch, a missing index/constraint — without depending on the
broken empty-DB migration chain or on a contaminated DB (the false-positive
source that made earlier drift reports look catastrophic).

A future ORM change that introduces an internal inconsistency fails here.
"""
from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from workgraph_persistence import Base


# Tables the ORM declares. Frozen so an accidental table drop/add is loud.
EXPECTED_TABLE_COUNT = 46


def test_metadata_table_count_stable() -> None:
    """The ORM declares exactly the expected set of tables. A change here is
    intentional only — bump the constant in the same commit that adds/removes
    a table so the delta is reviewable."""
    assert len(Base.metadata.tables) == EXPECTED_TABLE_COUNT


def test_m6_composite_indexes_present() -> None:
    """All 9 M6 composite indexes (commit 67b4569) stay declared on the ORM.
    Guards against a silent regression that would also desync migration 0030."""
    expected = {
        "plan_tasks": {"ix_plan_tasks_project_scope_owner"},
        "kb_items": {"ix_kb_items_project_scope_owner"},
        "status_transitions": {"ix_status_transitions_project_changed"},
        "conflicts": {"ix_conflicts_project_status"},
        "commitments": {"ix_commitments_project_status"},
        "gated_proposals": {
            "ix_gated_proposals_gatekeeper_status",
            "ix_gated_proposals_project_status",
        },
        "routed_signals": {
            "ix_routed_signals_target_status",
            "ix_routed_signals_source_status",
        },
    }
    for table, index_names in expected.items():
        names = {ix.name for ix in Base.metadata.tables[table].indexes}
        missing = index_names - names
        assert not missing, f"{missing} missing from {table}"


def test_create_all_schema_matches_orm() -> None:
    """No autogenerate drift between the ORM metadata and the schema
    `create_all` produces — the guardrail behind docs/migrations.md's
    'alembic check is clean' claim.

    Uses a sync in-memory SQLite engine: build the schema via create_all,
    then compare_metadata(ctx, Base.metadata) — the same comparison alembic
    autogenerate runs. An empty diff means the ORM is self-consistent with the
    schema it emits.
    """
    engine = create_engine("sqlite://")  # sync, in-memory
    try:
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diff = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()

    # `diff` is a list of autogenerate ops; empty == no drift. Surface the
    # offending ops in the assertion message so a failure is actionable.
    assert diff == [], f"unexpected schema drift ({len(diff)} ops): {diff!r}"
