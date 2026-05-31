from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _FrecencyColumnsMixin:
    """N-Next §7.4 frecency primitives.

    `last_accessed_at` + `access_count` drive the frecency ranker —
    `score = log(1 + access_count) × time_decay(now - last_accessed_at)`.
    Bump-on-touch writers update both on: search hits (kb_search /
    skill atlas), citation resolution (decision crystallize, edge-LLM
    cited claims), and explicit user navigation (detail-page reads).

    Defaults at INSERT time: `last_accessed_at = _utcnow` (a freshly-
    created row is freshly-accessed by definition); `access_count = 0`.
    Migration 0028 backfills `last_accessed_at` from `created_at` for
    pre-migration rows.

    Applied to the five node-bearing row types: KbItemRow, MessageRow,
    DecisionRow, TaskRow, RiskRow. Not applied to graph entities
    (Goal/Deliverable/Constraint) because those aren't retrieval
    targets — they're structure, not content.
    """

    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    access_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )


class _GraphEntityBase:
    """Shared column shape for Goal/Deliverable/Constraint/Risk rows.

    Every graph entity is:
      - scoped to a project (CASCADE with project)
      - bound to a specific requirement version (CASCADE with requirement)
      - ordered within its kind via sort_order
      - carries a status string (default "open") so later phases (planning,
        QA, delivery) can mutate lifecycle without creating parallel tables

    Per decision 1E: there is no stage column. The presence of these rows
    and their status IS the project stage. See stage.project_stage().
    """

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


