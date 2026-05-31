"""Composite indexes for hot multi-column query shapes (audit M6).

Revision ID: 0030_composite_indexes
Revises: 0029_stream_name
Create Date: 2026-05-31

Each index backs a confirmed multi-column WHERE in the repository layer
(grounded query shapes, no speculative indexes):

  * conflicts          (project_id, status)                  — conflict lists
  * status_transitions (project_id, changed_at)              — graph-at replay range
  * plan_tasks         (project_id, scope, owner_user_id)    — personal task lists
  * kb_items           (project_id, scope, owner_user_id)    — group + personal KB lists
  * commitments        (project_id, status)                  — commitment lists
  * gated_proposals    (gate_keeper_user_id, status)         — gate-keeper inbox
  * gated_proposals    (project_id, status)                  — project proposal lists
  * routed_signals     (target_user_id, status)              — inbox
  * routed_signals     (source_user_id, status)              — outbox

Index names are byte-identical to the ORM __table_args__ declarations
(packages/persistence/.../orm.py) so create_all (dev/test) and Alembic
(prod) agree and autogenerate stays clean. Additive + reversible; plain
create_index is SQLite- and Postgres-safe for index creation.

Negligible on SQLite-dev; the payoff is on the Postgres target.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0030_composite_indexes"
down_revision: str | Sequence[str] | None = "0029_stream_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (index_name, table, [columns]) — order mirrors the ORM declarations.
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_conflicts_project_status", "conflicts", ["project_id", "status"]),
    (
        "ix_status_transitions_project_changed",
        "status_transitions",
        ["project_id", "changed_at"],
    ),
    (
        "ix_plan_tasks_project_scope_owner",
        "plan_tasks",
        ["project_id", "scope", "owner_user_id"],
    ),
    (
        "ix_kb_items_project_scope_owner",
        "kb_items",
        ["project_id", "scope", "owner_user_id"],
    ),
    ("ix_commitments_project_status", "commitments", ["project_id", "status"]),
    (
        "ix_gated_proposals_gatekeeper_status",
        "gated_proposals",
        ["gate_keeper_user_id", "status"],
    ),
    (
        "ix_gated_proposals_project_status",
        "gated_proposals",
        ["project_id", "status"],
    ),
    (
        "ix_routed_signals_target_status",
        "routed_signals",
        ["target_user_id", "status"],
    ),
    (
        "ix_routed_signals_source_status",
        "routed_signals",
        ["source_user_id", "status"],
    ),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
