"""handoff — HandoffRow → packet."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from workgraph_persistence import HandoffRow

from ..contracts import (
    PacketStatus,
    _accepted_scope,
    _empty_evidence,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


async def derive_handoff_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.execute(
                select(HandoffRow)
                .where(HandoffRow.project_id == project_id)
                .order_by(HandoffRow.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [_handoff_packet_from_row(r, owner_ids) for r in rows]


def _handoff_packet_from_row(
    row: HandoffRow, owner_ids: list[str]
) -> dict[str, Any]:
    """Map a HandoffRow to a `handoff` packet.

    Owner gating: per HandoffService.finalize, only project owners
    finalize a handoff. Populate `authority_user_ids` with project
    owners and use them as `current_target_user_ids` while the packet
    is still draft, so owners see the packet in `bucket=needs_me`.
    """
    stage_alive = (row.status or "draft") == "draft"
    packet_status: PacketStatus = "active" if stage_alive else "completed"
    title = (
        f"Handoff: {row.from_display_name or row.from_user_id} "
        f"→ {row.to_display_name or row.to_user_id}"
    )
    if len(title) > 120:
        title = title[:117] + "…"
    timeline = [
        {
            "at": _iso(row.created_at),
            "actor": "system",
            "kind": "handoff_drafted",
            "summary": "Handoff packet drafted — awaiting owner finalization.",
            "refs": [],
        }
    ]
    if row.finalized_at:
        timeline.append(
            {
                "at": _iso(row.finalized_at),
                "actor": "human",
                "kind": "handoff_finalized",
                "summary": "Handoff finalized.",
                "refs": [],
            }
        )
    next_actions: list[dict[str, Any]] = []
    if stage_alive:
        # Handoff finalize lives behind MemberHandoffButton on the
        # /projects/{pid}/skills page (the skill-atlas surface where
        # member cards expose the HandoffDialog). The previous /team
        # link was hollow — landing on the team room when the user
        # wanted to act on a draft handoff. Skills page is the
        # canonical actionable surface.
        next_actions.append(
            {
                "id": "finalize",
                "label": "Open handoff",
                "kind": "open",
                "requires_membrane": False,
                "href": f"/projects/{row.project_id}/skills",
            }
        )
    return {
        "id": f"handoff:{row.id}",
        "project_id": row.project_id,
        "recipe_id": "handoff",
        "stage": "awaiting_owner" if stage_alive else "completed",
        "status": packet_status,
        "source_user_id": row.from_user_id,
        "target_user_ids": [row.to_user_id],
        # Owner finalizes — not the to_user. Owners populate
        # current_target_user_ids while draft so bucket=needs_me hits.
        "current_target_user_ids": list(owner_ids) if stage_alive else [],
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": (row.brief_markdown or "")[:240],
        "intent": "Transfer routines to a successor.",
        "source_refs": [],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "handoff_id": row.id,
        "transition_contract": _transition_contract(
            # T4 — handoff contract. The state pair is
            # `handoff_drafted` → `handoff_finalized`. Authority is
            # the project owners (HandoffService.finalize gates on
            # owner role).
            source_state="handoff_drafted",
            target_state="handoff_finalized",
            review_method="owner_acceptance",
            mutation_service="HandoffService",
            status="awaiting_authority" if stage_alive else "completed",
            required_evidence=[
                _flow_ref("handoff", row.id, label=title),
            ],
            authority_user_ids=list(owner_ids) if stage_alive else [],
            lineage_output=(
                []
                if stage_alive
                else [
                    _flow_ref(
                        "handoff_finalized",
                        row.id,
                        label="finalized",
                        at=_iso(row.finalized_at),
                    )
                ]
            ),
        ),
        # E2 — handoff as a `handoff` epistemic event. status moves
        # draft → review_pending → accepted_for_scope. accepted_scope
        # is project-wide (the project plan absorbs the routine).
        # membrane_policy = "none" because handoff doesn't go through
        # Membrane; HandoffService.finalize is its own owner gate.
        "epistemic_event": _epistemic_event(
            kind="handoff",
            status=(
                "review_pending" if stage_alive else "accepted_for_scope"
            ),
            proposition=title,
            source_actor_id=row.from_user_id,
            target_audience=[row.to_user_id]
            if row.to_user_id
            else [],
            visibility_scope="project",
            accepted_scope=(
                None
                if stage_alive
                else _accepted_scope(
                    scope_type="project",
                    scope_id=row.project_id,
                    accepted_by_user_ids=list(owner_ids),
                    accepted_at=_iso(row.finalized_at),
                )
            ),
            evidence_refs=[
                _flow_ref("handoff", row.id, label=title),
            ],
            preconditions=[],
            authority_required=list(owner_ids) if stage_alive else [],
            # No Membrane gate on handoff — it's owner_acceptance, which
            # the transition_contract already names. Honest "none" here.
            membrane_policy="none",
            update_effects=["handoff_finalized"],
            lineage_output=(
                []
                if stage_alive
                else [
                    _flow_ref(
                        "handoff_finalized",
                        row.id,
                        label="finalized",
                        at=_iso(row.finalized_at),
                    )
                ]
            ),
            supersedes=[],
            expires_at=None,
        ),
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.finalized_at) or _iso(row.created_at),
    }
