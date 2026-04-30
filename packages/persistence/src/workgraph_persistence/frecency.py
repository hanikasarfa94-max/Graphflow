"""§7.4 frecency bump-on-touch helper.

Reads the columns introduced in alembic 0028 / orm `_FrecencyColumnsMixin`
and writes them on the three touch-events identified in PLAN-Next pickup
#3:

  * search hits (skill atlas / kb_search) — every returned KbItem is
    "touched" once per call.
  * citation resolution (decision crystallize, edge-LLM cited claims) —
    the source row that backed a derivation is touched.
  * explicit user navigation (detail-page reads) — the row a user
    actually opened is touched.

Touch is best-effort: a failure here must NEVER break the read or write
that triggered it. The §7.4 ranker is degraded by missing touches, not
broken — `score = log(1 + access_count) × time_decay(now -
last_accessed_at)` falls back gracefully to "everything looks equally
fresh" when no bumps have landed yet.

The helper buckets ids by row type and issues at most one UPDATE per
type per call, so even a 50-item kb_search hit-list stays cheap.
Citation kinds map to row types via `bump_citations`:

  * `kb` / `wiki_page`        → KbItemRow
  * `decision`                → DecisionRow
  * `task`                    → TaskRow
  * `risk`                    → RiskRow
  * `goal` / `deliverable`    → no-op (graph entities, not retrieval
  * `milestone` / `commitment`  targets — see _FrecencyColumnsMixin
                                docstring)

Messages are touched directly via `message_ids=` (no citation kind for
them today; the IM crystallize path supplies the source-message id).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import DecisionRow, KbItemRow, MessageRow, RiskRow, TaskRow

_log = logging.getLogger("workgraph.persistence.frecency")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_KIND_TO_ROW = {
    "kb": KbItemRow,
    "wiki_page": KbItemRow,
    "decision": DecisionRow,
    "task": TaskRow,
    "risk": RiskRow,
}


async def bump_frecency(
    session: AsyncSession,
    *,
    kbitem_ids: Iterable[str] = (),
    message_ids: Iterable[str] = (),
    decision_ids: Iterable[str] = (),
    task_ids: Iterable[str] = (),
    risk_ids: Iterable[str] = (),
) -> dict[str, int]:
    """Bump `last_accessed_at = now` and `access_count += 1` for each id.

    Issues one UPDATE per non-empty bucket. Duplicates within a bucket
    coalesce — the same id touched twice in a single search-hit list
    counts as one bump (which matches user intent: a single skill call
    is one access event, regardless of how often the row appears in
    the result set).

    Returns `{kind: rows_updated}` so tests can assert. On any error,
    logs and returns zero counts for the failing bucket — touch must
    never break the hot path.
    """
    buckets: list[tuple[str, type, set[str]]] = [
        ("kb_item", KbItemRow, _dedupe(kbitem_ids)),
        ("message", MessageRow, _dedupe(message_ids)),
        ("decision", DecisionRow, _dedupe(decision_ids)),
        ("task", TaskRow, _dedupe(task_ids)),
        ("risk", RiskRow, _dedupe(risk_ids)),
    ]
    counts: dict[str, int] = {}
    now = _utcnow()
    for label, row_cls, ids in buckets:
        if not ids:
            counts[label] = 0
            continue
        try:
            stmt = (
                update(row_cls)
                .where(row_cls.id.in_(ids))
                .values(
                    last_accessed_at=now,
                    access_count=row_cls.access_count + 1,
                )
            )
            result = await session.execute(stmt)
            counts[label] = int(result.rowcount or 0)
        except Exception:
            _log.exception(
                "frecency.bump failed", extra={"kind": label, "n_ids": len(ids)}
            )
            counts[label] = 0
    return counts


async def bump_citations(
    session: AsyncSession,
    citations: Iterable[object],
) -> dict[str, int]:
    """Bucket `Citation`-shaped objects (.kind / .node_id) and bump.

    Accepts anything duck-typed with `kind` and `node_id` attributes —
    `workgraph_agents.citations.Citation` is the canonical source, but
    the persistence package stays import-clean of the agents package by
    not naming the type. Unknown kinds are silently skipped (commitments,
    graph entities — see module docstring).
    """
    by_kind: dict[str, set[str]] = {}
    for c in citations:
        kind = getattr(c, "kind", None)
        node_id = getattr(c, "node_id", None)
        if not kind or not node_id:
            continue
        row_cls = _KIND_TO_ROW.get(kind)
        if row_cls is None:
            continue
        by_kind.setdefault(kind, set()).add(node_id)
    return await bump_frecency(
        session,
        kbitem_ids=by_kind.get("kb", set()) | by_kind.get("wiki_page", set()),
        decision_ids=by_kind.get("decision", set()),
        task_ids=by_kind.get("task", set()),
        risk_ids=by_kind.get("risk", set()),
    )


def _dedupe(ids: Iterable[str]) -> set[str]:
    return {i for i in ids if i}


__all__ = ["bump_frecency", "bump_citations"]
