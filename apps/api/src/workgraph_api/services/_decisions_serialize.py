"""Shared decision serializer (C1 decisions-consolidation).

One source of truth for the wire shape of a DecisionRow, replacing the three
hand-maintained copies that had drifted apart (DecisionService._decision_payload,
IMService._decision_payload, license_context's inline decision dict). Each
emitted a different subset of the FE `Decision` type; this helper emits the full
superset so all three paths agree.

Leaf module: imports only stdlib + the DecisionRow type + AsyncSession + UserRow.
No service imports → no cycle (same pattern as services/_users.py).

`render.py`'s lineage payload is intentionally NOT routed through here — it is a
distinct lineage-specific shape (adds `lineage`, drops most base fields), not the
FE `Decision` contract.
"""

from __future__ import annotations

from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workgraph_persistence import DecisionRow
from workgraph_persistence.orm import UserRow


def decision_payload(
    row: DecisionRow,
    *,
    resolver_display_name: str | None = None,
    tally: dict[str, Any] | None = None,
    include_apply_actions: bool = True,
    include_apply_detail: bool = True,
) -> dict[str, Any]:
    """Serialize a DecisionRow to the shared FE `Decision` superset.

    Always emits the base fields + the four FE-live provenance fields
    (scope_stream_id, gated_via_proposal_id, decision_class, and
    resolver_display_name when provided). `tally` is grafted on only when a
    caller passes it (WS/room-timeline enrichment). apply_actions/apply_detail
    can be omitted by callers that historically didn't emit them (license_context
    keeps emitting them now — additive — but the flags keep the helper flexible).
    """
    payload: dict[str, Any] = {
        "id": row.id,
        "conflict_id": row.conflict_id,
        "source_suggestion_id": row.source_suggestion_id,
        "project_id": row.project_id,
        "resolver_id": row.resolver_id,
        "resolver_display_name": resolver_display_name,
        "option_index": row.option_index,
        "custom_text": row.custom_text,
        "rationale": row.rationale,
        "apply_outcome": row.apply_outcome,
        # Provenance fields the FE Decision type declares (DecisionsPanel,
        # RoomStreamTimeline, gated/vote cards consume them).
        "gated_via_proposal_id": row.gated_via_proposal_id,
        "decision_class": row.decision_class,
        "scope_stream_id": row.scope_stream_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }
    if include_apply_actions:
        payload["apply_actions"] = row.apply_actions or []
    if include_apply_detail:
        payload["apply_detail"] = row.apply_detail or {}
    if tally is not None:
        payload["tally"] = tally
    return payload


async def resolve_resolver_names(
    session: AsyncSession, rows: Sequence[DecisionRow]
) -> dict[str, str]:
    """Bulk {resolver_id: display_name||username} for a batch of decisions.

    One SELECT keyed by the distinct resolver_ids — no per-row N+1. Missing
    users (resolver_id SET NULL on delete, or stale id) are simply absent from
    the map; callers fall back to None for those.
    """
    ids = list({r.resolver_id for r in rows if r.resolver_id})
    if not ids:
        return {}
    users = (
        (await session.execute(select(UserRow).where(UserRow.id.in_(ids))))
        .scalars()
        .all()
    )
    return {u.id: (u.display_name or u.username) for u in users}
