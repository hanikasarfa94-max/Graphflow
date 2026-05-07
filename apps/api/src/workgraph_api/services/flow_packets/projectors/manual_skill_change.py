"""manual_skill_change — IMSuggestionRow(kind=membrane_review,
candidate_kind=manual_skill_change) [pending].

M5.1 slice. Closes the Org Graph mutation gap: skill_tags edits
by non-owners are now stage-then-approve rather than direct
mutate.
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


async def derive_manual_skill_change_packets(
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
        if detail.get("candidate_kind") != "manual_skill_change":
            continue
        out.append(
            _manual_skill_change_packet_from_suggestion(sug, owner_ids)
        )
    return out


def _manual_skill_change_packet_from_suggestion(
    suggestion: IMSuggestionRow, owner_ids: list[str]
) -> dict[str, Any]:
    """Map a pending IMSuggestion(membrane_review, manual_skill_change)
    to a `manual_skill_change` flow packet."""
    proposal = (
        suggestion.proposal if isinstance(suggestion.proposal, dict) else None
    ) or {}
    detail = proposal.get("detail") or {}
    target_user_id = detail.get("target_user_id") or ""
    proposer_user_id = detail.get("proposer_user_id")
    new_skill_tags = list(detail.get("new_skill_tags") or [])
    diff_summary = detail.get("diff_summary")

    title = (
        f"Skill_tags update for member {target_user_id[:8]}…"
        if target_user_id
        else "Skill_tags update"
    )

    timeline = [
        {
            "at": _iso(suggestion.created_at),
            "actor": "membrane",
            "actor_user_id": proposer_user_id,
            "kind": "manual_skill_change_proposed",
            "summary": (
                "Non-owner proposed a skill_tags update — staged for "
                "owner approval (Org Graph governance)."
            ),
            "refs": [
                _flow_ref(
                    "im_suggestion",
                    suggestion.id,
                    label="manual_skill_change review",
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
            label="manual_skill_change review",
        ),
    ]
    if target_user_id:
        required_evidence.append(
            _flow_ref(
                "user", target_user_id, label="target member"
            )
        )
    if diff_summary:
        required_evidence.append(
            _flow_ref(
                "diff_summary", suggestion.id, label=diff_summary[:80]
            )
        )

    transition_contract = _transition_contract(
        source_state="capability_claim_proposed",
        target_state="project_role_capability_accepted",
        review_method="membrane_review",
        mutation_service="ProjectService+MembraneService",
        status="awaiting_authority",
        required_evidence=required_evidence,
        authority_user_ids=list(owner_ids),
        lineage_output=[],
    )

    epistemic_event = _epistemic_event(
        kind="capability_claim",
        status="review_pending",
        proposition=(
            f"set skill_tags={sorted(set(new_skill_tags))} for "
            f"member {target_user_id[:8]}…"
        ),
        source_actor_id=proposer_user_id,
        target_audience=list(owner_ids),
        visibility_scope="project",
        accepted_scope=None,
        evidence_refs=required_evidence,
        preconditions=[],
        authority_required=list(owner_ids),
        membrane_policy="request_review",
        update_effects=["project_role_capability_accepted"],
        lineage_output=[],
        supersedes=[],
        expires_at=None,
    )

    return {
        "id": f"manual_skill_change:{suggestion.id}",
        "project_id": suggestion.project_id,
        "recipe_id": "manual_skill_change",
        "stage": "awaiting_membrane",
        "status": "active",
        "source_user_id": proposer_user_id,
        "target_user_ids": list(owner_ids),
        "current_target_user_ids": list(owner_ids),
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": diff_summary or "",
        "intent": (
            "Update a project member's skill_tags — owner approval "
            "required because skill_tags become role-level capability "
            "evidence in routing."
        ),
        "source_refs": [
            _flow_ref(
                "im_suggestion",
                suggestion.id,
                label="manual_skill_change review",
            )
        ],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "im_suggestion_id": suggestion.id,
        "manual_skill_change_proposal": {
            "target_user_id": target_user_id,
            "proposer_user_id": proposer_user_id,
            "new_skill_tags": new_skill_tags,
        },
        "membrane_candidate": {
            "kind": "manual_skill_change",
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
