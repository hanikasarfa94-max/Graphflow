"""promote_to_memory — KbItemRow(draft/pending-review) + IMSuggestion."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from workgraph_persistence import IMSuggestionRow, KbItemRow

from ..contracts import (
    PacketStatus,
    _accepted_scope,
    _empty_evidence,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


async def derive_kb_review_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    kb_rows = list(
        (
            await session.execute(
                select(KbItemRow)
                .where(KbItemRow.project_id == project_id)
                .where(KbItemRow.status.in_(["draft", "pending-review"]))
                .order_by(KbItemRow.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    if not kb_rows:
        return []
    # Pull the IMSuggestion rows that point at any of these KB items
    # via decision_id is a no — KB items aren't tracked by suggestion
    # decision_id. The link we actually have is on suggestion.proposal
    # (a JSON dict). Fetch broadly, filter in python; the volume here
    # is small (only pending suggestions).
    suggestion_rows = list(
        (
            await session.execute(
                select(IMSuggestionRow)
                .where(IMSuggestionRow.project_id == project_id)
                .where(IMSuggestionRow.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    suggestions_by_kb_id: dict[str, list[IMSuggestionRow]] = {}
    for sug in suggestion_rows:
        kb_id = _suggestion_kb_target_id(sug)
        if kb_id is None:
            continue
        suggestions_by_kb_id.setdefault(kb_id, []).append(sug)
    return [
        _kb_review_packet_from_row(
            r, suggestions_by_kb_id.get(r.id, []), owner_ids
        )
        for r in kb_rows
    ]


def _suggestion_kb_target_id(sug: IMSuggestionRow) -> str | None:
    """Best-effort: extract the kb_item id this IMSuggestion targets.

    The proposal JSON shape varies; we look at the well-known keys we
    emit in `services/membrane.py` for the kb_item_group candidate.
    Returns None if the suggestion isn't KB-targeted.
    """
    proposal = sug.proposal if isinstance(sug.proposal, dict) else None
    if not proposal:
        return None
    for key in ("kb_item_id", "target_kb_id", "kb_id", "row_id"):
        val = proposal.get(key)
        if isinstance(val, str):
            return val
    # Modern suggestions (kb_items.py / membrane.py) carry the id under
    # `proposal.detail.kb_item_id` instead of top-level. Fall through to
    # the nested form so the kb-review derivation doesn't miss new rows.
    detail = proposal.get("detail")
    if isinstance(detail, dict):
        if detail.get("candidate_kind") == "kb_item_group":
            val = detail.get("kb_item_id")
            if isinstance(val, str):
                return val
    return None


def _kb_review_packet_from_row(
    row: KbItemRow,
    suggestions: list[IMSuggestionRow],
    owner_ids: list[str],
) -> dict[str, Any]:
    """Map a draft / pending-review KB item to a `promote_to_memory` packet.

    Owner gating: KB drafts going to team memory require owner approval
    via Membrane. We populate `authority_user_ids` AND
    `current_target_user_ids` with project owners on awaiting-membrane
    packets so `bucket=needs_me` works for owners without the FE having
    to special-case this recipe.
    """
    stage_alive = row.status in ("draft", "pending-review")
    packet_status: PacketStatus = "active" if stage_alive else "completed"
    title = (row.title or row.source_identifier or "Untitled item").strip()
    if len(title) > 120:
        title = title[:117] + "…"
    summary_seed = (
        (row.classification_json or {}).get("summary")
        if isinstance(row.classification_json, dict)
        else None
    )
    summary = (summary_seed or row.title or row.raw_content or "")[:240]
    timeline = [
        {
            "at": _iso(row.created_at),
            "actor": "edge_agent" if row.source == "llm" else "human",
            "actor_user_id": row.ingested_by_user_id or row.owner_user_id,
            "kind": "kb_drafted",
            "summary": "KB draft created — awaiting Membrane review.",
            "refs": [],
        }
    ]
    for sug in suggestions:
        timeline.append(
            {
                "at": _iso(sug.created_at),
                "actor": "membrane",
                "kind": "membrane_suggestion_pending",
                "summary": "Membrane queued an inbox suggestion.",
                "refs": [
                    {
                        "kind": "agent_run",
                        "id": sug.id,
                        "label": "membrane suggestion",
                    }
                ],
            }
        )
    next_actions: list[dict[str, Any]] = []
    if stage_alive:
        # Membrane review surface lives at /projects/{pid}/detail/im.
        # The ChatPane on that page does NOT carry a per-suggestion
        # anchor (verified: no `#kb-{id}` or `?suggestion={id}` pattern
        # exists in the FE). So the best we can do is land the user on
        # the review queue and let them scroll. C.0 stops here for KB;
        # a per-suggestion anchor lands when ChatPane gains one.
        next_actions.append(
            {
                "id": "review",
                "label": "Open review",
                "kind": "open",
                "requires_membrane": True,
                "href": f"/projects/{row.project_id}/detail/im",
            }
        )
    membrane_candidate = (
        {
            "kind": "kb_item_group",
            "action": "request_review",
            "conflict_with": [],
            "warnings": [],
        }
        if stage_alive
        else None
    )
    return {
        "id": f"kb:{row.id}",
        "project_id": row.project_id or "",
        "recipe_id": "promote_to_memory",
        "stage": "awaiting_membrane" if stage_alive else "published",
        "status": packet_status,
        "source_user_id": row.ingested_by_user_id or row.owner_user_id,
        "target_user_ids": [],
        # Owner gate (Membrane): the project owners are who need to act
        # on this packet. Populated while alive so `bucket=needs_me`
        # works for owners; cleared once the row leaves draft state.
        "current_target_user_ids": list(owner_ids) if stage_alive else [],
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": summary,
        "intent": "Promote a draft into team memory via Membrane review.",
        "source_refs": [],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "kb_item_id": row.id,
        "im_suggestion_id": suggestions[0].id if suggestions else None,
        "membrane_candidate": membrane_candidate,
        "transition_contract": _transition_contract(
            # T4 — KB promote contract. Source state names match the
            # `KbItemRow.status` lifecycle: `draft` (user-authored)
            # and `pending-review` (ingest path). Target is canonical
            # World memory once status flips to 'published'.
            source_state=(
                "personal_kb_draft"
                if row.status == "draft"
                else "kb_pending_review"
            ),
            target_state="canonical_world_memory",
            review_method="membrane_review",
            mutation_service="KbItemService+MembraneService",
            status="awaiting_authority" if stage_alive else "completed",
            required_evidence=[
                _flow_ref("kb_item", row.id, label=row.title or ""),
                *[
                    _flow_ref(
                        "membrane_suggestion", s.id, label="KB review"
                    )
                    for s in suggestions
                ],
            ],
            authority_user_ids=list(owner_ids) if stage_alive else [],
            lineage_output=(
                []
                if stage_alive
                else [_flow_ref("kb_item_published", row.id, label=row.title or "")]
            ),
        ),
        # E2 — KB promote as memory transition. status names the
        # KbItemRow.status directly: draft / review_pending / canonical
        # / archived. accepted_scope is filled when canonical (project
        # scope; the team is the audience). membrane_policy reflects
        # the actual gate (request_review while pending, auto_merge
        # post-publish).
        "epistemic_event": _epistemic_event(
            kind="memory",
            status=(
                "draft"
                if row.status == "draft"
                else "review_pending"
                if row.status == "pending-review"
                else "archived"
                if row.status == "archived"
                else "canonical"
            ),
            proposition=title,
            source_actor_id=row.ingested_by_user_id or row.owner_user_id,
            target_audience=list(owner_ids),
            visibility_scope="project",
            accepted_scope=(
                None
                if stage_alive or row.status == "archived"
                else _accepted_scope(
                    scope_type="project",
                    scope_id=row.project_id,
                    accepted_by_user_ids=list(owner_ids),
                    accepted_at=_iso(row.created_at),
                )
            ),
            evidence_refs=[
                _flow_ref("kb_item", row.id, label=row.title or ""),
                *[
                    _flow_ref(
                        "membrane_suggestion", s.id, label="KB review"
                    )
                    for s in suggestions
                ],
            ],
            preconditions=[],
            authority_required=(
                list(owner_ids) if stage_alive else []
            ),
            membrane_policy=(
                "request_review" if stage_alive else "auto_merge"
            ),
            update_effects=["canonical_world_memory"],
            lineage_output=(
                []
                if stage_alive
                else [
                    _flow_ref(
                        "kb_item_published",
                        row.id,
                        label=row.title or "",
                    )
                ]
            ),
            supersedes=[],
            expires_at=None,
        ),
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.created_at),
    }
