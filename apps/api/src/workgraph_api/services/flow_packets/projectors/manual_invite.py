"""manual_invite — IMSuggestionRow(kind=membrane_review,
candidate_kind=manual_invite) [pending].

M5.1 slice. Closes the Org Graph mutation gap: invites by
non-owners are now stage-then-approve rather than direct mutate.
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


async def derive_manual_invite_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    rows = list(
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
    for sug in rows:
        proposal = (
            sug.proposal if isinstance(sug.proposal, dict) else None
        )
        if not proposal:
            continue
        detail = proposal.get("detail")
        if not isinstance(detail, dict):
            continue
        if detail.get("candidate_kind") != "manual_invite":
            continue
        out.append(
            _manual_invite_packet_from_suggestion(sug, owner_ids)
        )
    return out


def _manual_invite_packet_from_suggestion(
    suggestion: IMSuggestionRow, owner_ids: list[str]
) -> dict[str, Any]:
    """Map a pending IMSuggestion(membrane_review, manual_invite) to a
    `manual_invite` flow packet."""
    proposal = (
        suggestion.proposal if isinstance(suggestion.proposal, dict) else None
    ) or {}
    detail = proposal.get("detail") or {}
    target_username = detail.get("target_username") or ""
    proposer_user_id = detail.get("proposer_user_id")
    diff_summary = detail.get("diff_summary")

    title = f"Invite '{target_username}'" if target_username else "Member invite"

    timeline = [
        {
            "at": _iso(suggestion.created_at),
            "actor": "membrane",
            "actor_user_id": proposer_user_id,
            "kind": "manual_invite_proposed",
            "summary": (
                "Non-owner proposed adding a member — staged for "
                "owner approval."
            ),
            "refs": [
                _flow_ref(
                    "im_suggestion",
                    suggestion.id,
                    label="manual_invite review",
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
            label="manual_invite review",
        ),
    ]
    if diff_summary:
        required_evidence.append(
            _flow_ref(
                "diff_summary", suggestion.id, label=diff_summary[:80]
            )
        )

    transition_contract = _transition_contract(
        source_state="member_invite_proposed",
        target_state="project_member_accepted",
        review_method="membrane_review",
        mutation_service="ProjectService+MembraneService",
        status="awaiting_authority",
        required_evidence=required_evidence,
        authority_user_ids=list(owner_ids),
        lineage_output=[],
    )

    epistemic_event = _epistemic_event(
        kind="proposal",
        status="review_pending",
        proposition=f"invite '{target_username}' to project",
        source_actor_id=proposer_user_id,
        target_audience=list(owner_ids),
        visibility_scope="project",
        accepted_scope=None,
        evidence_refs=required_evidence,
        preconditions=[],
        authority_required=list(owner_ids),
        membrane_policy="request_review",
        update_effects=["project_member_accepted"],
        lineage_output=[],
        supersedes=[],
        expires_at=None,
    )

    return {
        "id": f"manual_invite:{suggestion.id}",
        "project_id": suggestion.project_id,
        "recipe_id": "manual_invite",
        "stage": "awaiting_membrane",
        "status": "active",
        "source_user_id": proposer_user_id,
        "target_user_ids": list(owner_ids),
        "current_target_user_ids": list(owner_ids),
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": diff_summary or "",
        "intent": (
            "Add a project member — owner approval required (member "
            "additions affect Org Graph)."
        ),
        "source_refs": [
            _flow_ref(
                "im_suggestion",
                suggestion.id,
                label="manual_invite review",
            )
        ],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "im_suggestion_id": suggestion.id,
        "manual_invite_proposal": {
            "target_username": target_username,
            "proposer_user_id": proposer_user_id,
        },
        "membrane_candidate": {
            "kind": "manual_invite",
            "action": "request_review",
            "conflict_with": [],
            "warnings": [],
        },
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(suggestion.created_at),
        "updated_at": _iso(suggestion.created_at),
    }
