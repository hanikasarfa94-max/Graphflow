"""manual_create_room — IMSuggestionRow(kind=membrane_review,
candidate_kind=manual_room) [pending].

M5 slice. Closes the audit gap: when a non-owner posts to
`POST /projects/{id}/rooms`, MembraneService.review_manual_room
stages an IMSuggestion. Until owner approval, no room exists in
streams; the proposal lives only on the suggestion. Projection
surfaces it so the owner inbox + Active Flows both show the
candidate.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from workgraph_persistence import IMSuggestionRow

from ..contracts import (
    _empty_evidence,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


async def derive_manual_room_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    suggestion_rows = list(
        (
            await session.execute(
                select(IMSuggestionRow)
                .where(IMSuggestionRow.project_id == project_id)
                .where(IMSuggestionRow.kind == "membrane_review")
                .where(IMSuggestionRow.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    out: list[dict[str, Any]] = []
    for sug in suggestion_rows:
        proposal = (
            sug.proposal if isinstance(sug.proposal, dict) else None
        )
        if not proposal:
            continue
        detail = proposal.get("detail")
        if not isinstance(detail, dict):
            continue
        if detail.get("candidate_kind") != "manual_room":
            continue
        out.append(_manual_room_packet_from_suggestion(sug, owner_ids))
    return out


def _manual_room_packet_from_suggestion(
    suggestion: IMSuggestionRow, owner_ids: list[str]
) -> dict[str, Any]:
    """Map a pending IMSuggestion(membrane_review, manual_room) to a
    `manual_create_room` packet. Mirrors the task_promote shape: the
    packet drops out of projection once the suggestion resolves
    (owner accept materializes the StreamRow; owner dismiss drops the
    proposal). The audit lives on the suggestion + StreamRow rows."""
    proposal = (
        suggestion.proposal if isinstance(suggestion.proposal, dict) else None
    ) or {}
    detail = proposal.get("detail") or {}
    name = (detail.get("name") or "").strip() or "(unnamed room)"
    proposer_user_id = detail.get("proposer_user_id")
    requested_member_ids = list(detail.get("member_user_ids") or [])
    diff_summary = detail.get("diff_summary")
    conflict_with = list(detail.get("conflict_with") or [])

    title = f"New room: {name}"
    if len(title) > 120:
        title = title[:117] + "…"

    timeline = [
        {
            "at": _iso(suggestion.created_at),
            "actor": "membrane",
            "actor_user_id": proposer_user_id,
            "kind": "manual_room_proposed",
            "summary": (
                "Non-owner proposed a new room — staged for owner "
                "approval."
            ),
            "refs": [
                _flow_ref(
                    "im_suggestion",
                    suggestion.id,
                    label="manual_room review",
                )
            ],
        }
    ]

    next_actions: list[dict[str, Any]] = [
        {
            "id": "review",
            "label": "Open review",
            "kind": "open",
            "requires_membrane": True,
            "href": f"/projects/{suggestion.project_id}/detail/im",
        }
    ]

    required_evidence: list[dict[str, Any]] = [
        _flow_ref(
            "im_suggestion",
            suggestion.id,
            label="manual_room review",
        ),
    ]
    if diff_summary:
        required_evidence.append(
            _flow_ref(
                "diff_summary",
                suggestion.id,
                label=diff_summary[:80],
            )
        )
    for ref in conflict_with:
        if isinstance(ref, str) and ref:
            required_evidence.append(
                _flow_ref(
                    "stream",
                    ref,
                    label="duplicate room",
                )
            )

    transition_contract = _transition_contract(
        source_state="room_proposed",
        target_state="canonical_room",
        review_method="membrane_review",
        mutation_service="StreamService+MembraneService",
        status="awaiting_authority",
        required_evidence=required_evidence,
        authority_user_ids=list(owner_ids),
        lineage_output=[],
    )

    epistemic_event = _epistemic_event(
        # `room` isn't in the closed EpistemicKind vocabulary; the
        # closest fit is `proposal` (a creation candidate awaiting
        # acceptance). The `recipe_id` distinguishes it from other
        # proposals.
        kind="proposal",
        status="review_pending",
        proposition=name[:200],
        source_actor_id=proposer_user_id,
        target_audience=list(owner_ids),
        visibility_scope="project",
        accepted_scope=None,
        evidence_refs=required_evidence,
        preconditions=[],
        authority_required=list(owner_ids),
        membrane_policy="request_review",
        update_effects=["canonical_room"],
        lineage_output=[],
        supersedes=[],
        expires_at=None,
    )

    return {
        "id": f"manual_room:{suggestion.id}",
        "project_id": suggestion.project_id,
        "recipe_id": "manual_create_room",
        "stage": "awaiting_membrane",
        "status": "active",
        "source_user_id": proposer_user_id,
        "target_user_ids": list(owner_ids),
        "current_target_user_ids": list(owner_ids),
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": diff_summary or f"Member proposed creating room '{name}'.",
        "intent": (
            "Create a new room (non-owner proposer) — owner approval "
            "required before the StreamRow is materialized."
        ),
        "source_refs": [
            _flow_ref(
                "im_suggestion",
                suggestion.id,
                label="manual_room review",
            )
        ],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "im_suggestion_id": suggestion.id,
        "manual_room_proposal": {
            "name": name,
            "proposer_user_id": proposer_user_id,
            "member_user_ids": requested_member_ids,
        },
        "membrane_candidate": {
            "kind": "manual_room",
            "action": "request_review",
            "conflict_with": conflict_with,
            "warnings": [],
        },
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(suggestion.created_at),
        "updated_at": _iso(suggestion.created_at),
    }
