"""ask_with_context — RoutedSignalRow → packet.

Lifecycle (revised in C.1 — see flow-actions-c1-design.md §11):
  pending   → active, target is currently_blocking
  replied   → active, SOURCE is currently_blocking (awaiting
              accept / counter / escalate / followup)
  accepted  → completed, terminal
  countered → completed, terminal (new packet active in its place)
  escalated → completed, terminal (gate fan-out is C.2)
  *         → completed (declined / expired)
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from workgraph_persistence import RoutedSignalRow

from ..contracts import (
    EpistemicStatus,
    PacketStatus,
    ReviewMethod,
    TransitionStatus,
    _accepted_scope,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


_ROUTE_ACTIVE_STATUSES = frozenset({"pending", "replied"})


# Maps source-side action strings (as persisted in
# reply_json["source_action_notes"]) onto the EvidencePacket
# human_gates action vocabulary. custom_followup intentionally has no
# entry — it's a continuation rather than a gate decision; it surfaces
# only in the timeline.
_SOURCE_ACTION_TO_GATE: dict[str, str] = {
    "accept": "accept",
    "counter_back": "counter",
    "escalate_to_gate": "escalate_to_gate",
}

_SOURCE_ACTION_TIMELINE_SUMMARY: dict[str, str] = {
    "accept": "Source accepted the reply.",
    "counter_back": "Source countered the reply.",
    "escalate_to_gate": "Source escalated to a gate.",
    "custom_followup": "Source sent a follow-up.",
}


async def derive_route_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    """`owner_ids` is currently unused for routes — passed for parity
    with other projectors and because future C.2 escalation will need
    owner authority on `escalated` packets.
    """
    rows = list(
        (
            await session.execute(
                select(RoutedSignalRow)
                .where(RoutedSignalRow.project_id == project_id)
                .order_by(RoutedSignalRow.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [_route_packet_from_row(r) for r in rows]


def _route_packet_from_row(row: RoutedSignalRow) -> dict[str, Any]:
    status = row.status or "pending"
    is_pending = status == "pending"
    is_replied = status == "replied"
    status_alive = status in _ROUTE_ACTIVE_STATUSES
    packet_status: PacketStatus = "active" if status_alive else "completed"
    title = (row.framing or "").strip().splitlines()[0] if row.framing else "(no framing)"
    if len(title) > 120:
        title = title[:117] + "…"
    # Timeline — chronological audit of who acted when. Slice D fills
    # source-side action events from reply_json["source_action_notes"]
    # so the evidence block can render the closing event ("Maya
    # accepted at 11:02") in addition to the dispatch + reply.
    timeline = [
        {
            "at": _iso(row.created_at),
            "actor": "edge_agent",
            "actor_user_id": row.source_user_id,
            "kind": "route_dispatched",
            "summary": "Source agent routed the question.",
            "refs": [],
        }
    ]
    reply_json = row.reply_json if isinstance(row.reply_json, dict) else {}
    if row.responded_at:
        timeline.append(
            {
                "at": _iso(row.responded_at),
                "actor": "human",
                "actor_user_id": row.target_user_id,
                "kind": "route_replied",
                "summary": "Target replied.",
                "refs": [],
            }
        )
    source_action_notes = list(reply_json.get("source_action_notes") or [])
    for n in source_action_notes:
        action = n.get("action") or "unknown"
        timeline.append(
            {
                "at": n.get("at"),
                "actor": "human",
                "actor_user_id": row.source_user_id,
                "kind": f"source_{action}",
                "summary": _SOURCE_ACTION_TIMELINE_SUMMARY.get(
                    action, "Source acted on reply."
                ),
                "refs": [],
            }
        )

    next_actions: list[dict[str, Any]] = []
    if is_pending:
        # Target is currently blocking — render the legacy "Reply"
        # affordance. Target reply still flows through
        # RoutingService.reply (target-side surface lifts to the
        # flow endpoint in C.2; for now the action.kind="open" link
        # deep-anchors to the inbound card so the target lands on
        # the answerable surface).
        href = (
            f"/projects/{row.project_id}/team#routing-{row.id}"
            if row.project_id
            else "/inbox"
        )
        next_actions.append(
            {
                "id": "reply",
                "label": "Reply",
                "kind": "open",
                "actor_user_id": row.target_user_id,
                "requires_membrane": False,
                "href": href,
            }
        )
    elif is_replied:
        # Source is currently blocking — emit the four C.1 source-side
        # affordances. FE renders one button per entry; no
        # re-derivation from recipe_id or signal_id needed.
        src_href = (
            f"/projects/{row.project_id}/team#routing-{row.id}"
            if row.project_id
            else "/inbox"
        )
        for action_kind, label in (
            ("accept", "Accept"),
            ("counter_back", "Counter back"),
            ("escalate_to_gate", "Escalate to gate"),
            ("custom_followup", "Send follow-up"),
        ):
            next_actions.append(
                {
                    "id": action_kind,
                    "label": label,
                    "kind": action_kind,
                    "actor_user_id": row.source_user_id,
                    "requires_membrane": False,
                    # All four point at the same surface — the team-room
                    # routing card. The FE will render the button inline
                    # in the flows panel; the href is a fallback for
                    # users who want to act in the original surface.
                    "href": src_href,
                }
            )

    # current_target_user_ids derives from who is currently blocking,
    # not from participation history. Spec §6 / line 276.
    if is_pending:
        current_target = [row.target_user_id]
    elif is_replied:
        current_target = [row.source_user_id]
    else:
        current_target = []

    # `stage` is a display label, not state-of-truth (spec §4). We map
    # to a coarse per-status string the FE can translate.
    if is_pending:
        stage = "awaiting_target"
    elif is_replied:
        stage = "awaiting_source"
    else:
        stage = "completed"

    # Source refs (Slice D): point at the routed signal itself + the
    # source/target stream surfaces. Streams use a new `stream` kind
    # — added to the FE FlowRef.kind union so the typed boundary
    # stays honest.
    source_refs: list[dict[str, Any]] = [
        {
            "kind": "agent_run",
            "id": row.id,
            "label": "Routed signal",
        }
    ]
    if row.source_stream_id:
        source_refs.append(
            {
                "kind": "stream",
                "id": row.source_stream_id,
                "label": "Source stream",
                "href": f"/streams/{row.source_stream_id}",
            }
        )
    if row.target_stream_id:
        source_refs.append(
            {
                "kind": "stream",
                "id": row.target_stream_id,
                "label": "Target stream",
                "href": f"/streams/{row.target_stream_id}",
            }
        )

    # Evidence (Slice D): human_gates from target reply + source-side
    # action notes. Per spec §7.6, evidence must surface before
    # completion; this is the start. custom_followup is intentionally
    # excluded from human_gates because it's a continuation, not a
    # gate decision (the original packet stays open in the audit
    # sense; the new packet has its own gates).
    human_gates: list[dict[str, Any]] = []
    if row.responded_at:
        # Heuristic mapping: option_id picked → 'accept' (target chose
        # one of source's offered options); custom_text → 'counter'
        # (target said something else). Imperfect; will tighten when
        # OptionKind reaches the projection.
        option_id = reply_json.get("option_id") if reply_json else None
        custom_text = reply_json.get("custom_text") if reply_json else None
        gate_action = "counter" if custom_text and not option_id else "accept"
        human_gates.append(
            {
                "user_id": row.target_user_id,
                "action": gate_action,
                "at": _iso(row.responded_at),
                "note": custom_text or None,
            }
        )
    for n in source_action_notes:
        gate_action = _SOURCE_ACTION_TO_GATE.get(n.get("action") or "")
        if gate_action is None:
            continue  # custom_followup or unknown — skip from gates
        human_gates.append(
            {
                "user_id": row.source_user_id,
                "action": gate_action,
                "at": n.get("at") or "",
                "note": n.get("note") or None,
            }
        )

    evidence = {
        "citations": [],
        "source_messages": [],
        "artifacts": [],
        "agent_runs": source_refs[:1],  # the routed signal itself
        "human_gates": human_gates,
        "uncertainty": [],
    }

    # T2 — Transition Contract for routed signal. The state pair
    # describes what the signal is trying to move through, not what
    # row exists. `question_unanswered` → `expert_reply_received` →
    # `reply_accepted` / `reply_countered` / `reply_escalated`.
    #
    # required_evidence travels with the contract: framing is always
    # there, plus any `routing_basis` envelope persisted in
    # background_json by R2 (the server-side suggestion verification),
    # plus the target reply once landed.
    if is_pending:
        contract_source = "question_unanswered"
        contract_target = "expert_reply_received"
        contract_status: TransitionStatus = "awaiting_authority"
    elif is_replied:
        contract_source = "expert_reply_received"
        contract_target = "reply_accepted"
        contract_status = "awaiting_authority"
    else:
        # Pick the terminal state name from the most recent
        # source-side action note (slice D semantics).
        last_action = (
            source_action_notes[-1].get("action")
            if source_action_notes
            else None
        )
        contract_source = "expert_reply_received"
        contract_target = (
            f"reply_{last_action}"
            if last_action in ("accepted", "countered", "escalated")
            else "reply_accepted"
        )
        contract_status = "completed"

    contract_required_evidence: list[dict[str, Any]] = [
        _flow_ref("framing", row.id, label="routed signal framing"),
    ]
    bg = row.background_json if isinstance(row.background_json, list) else []
    for entry in bg:
        if isinstance(entry, dict) and entry.get("source") == "routing_basis":
            basis = entry.get("routing_basis") or {}
            if basis.get("grounded"):
                matched = basis.get("matched_suggestion") or {}
                contract_required_evidence.append(
                    _flow_ref(
                        "routing_basis",
                        matched.get("user_id"),
                        label="server-side routing_suggest match",
                        primary_signal=(
                            matched.get("evidence", {}) or {}
                        ).get("primary_signal"),
                    )
                )
            else:
                contract_required_evidence.append(
                    _flow_ref(
                        "routing_basis",
                        None,
                        label=f"ungrounded ({basis.get('reason') or 'unknown'})",
                    )
                )
            break  # one routing_basis envelope per dispatch

    contract_authority = list(current_target)

    contract_lineage: list[dict[str, Any]] = []
    if row.responded_at:
        contract_lineage.append(
            _flow_ref(
                "routed_reply",
                row.id,
                label="target reply",
                at=_iso(row.responded_at),
            )
        )
    for n in source_action_notes:
        contract_lineage.append(
            _flow_ref(
                f"source_{n.get('action') or 'action'}",
                row.id,
                label=f"source {n.get('action') or 'action'}",
                at=n.get("at"),
            )
        )

    transition_contract = _transition_contract(
        source_state=contract_source,
        target_state=contract_target,
        review_method="routing_reply",
        mutation_service="RoutingService",
        status=contract_status,
        required_evidence=contract_required_evidence,
        authority_user_ids=contract_authority,
        lineage_output=contract_lineage,
    )

    # E2 — Epistemic Event for routed signal: a question whose
    # status moves through proposed → review_pending → accepted_for_
    # scope. `update_effects` enumerates the lifecycle outcomes;
    # the membrane_policy is "none" because routes don't go through
    # Membrane (RoutingService is the gate, not Membrane).
    if is_pending:
        ep_status: EpistemicStatus = "proposed"
        ep_accepted_scope = None
    elif is_replied:
        ep_status = "review_pending"
        ep_accepted_scope = None
    else:
        ep_status = "accepted_for_scope"
        ep_accepted_scope = _accepted_scope(
            # Routes are scoped to the source/target pair within the
            # project; the named scope is the project (we don't track
            # a smaller "DM scope" in v1).
            scope_type="project",
            scope_id=row.project_id,
            accepted_by_user_ids=[row.source_user_id],
            accepted_at=(
                _iso(source_action_notes[-1].get("at"))
                if isinstance(source_action_notes, list)
                and source_action_notes
                else None
            ),
        )
    epistemic_event = _epistemic_event(
        kind="question",
        status=ep_status,
        proposition=(row.framing or "")[:200],
        source_actor_id=row.source_user_id,
        target_audience=[row.target_user_id],
        visibility_scope="project",
        accepted_scope=ep_accepted_scope,
        evidence_refs=contract_required_evidence,
        preconditions=[],
        authority_required=list(current_target),
        membrane_policy="none",
        update_effects=[
            "expert_reply_received",
            "reply_accepted",
            "reply_countered",
            "reply_escalated",
        ],
        lineage_output=contract_lineage,
        supersedes=[],
        expires_at=None,
    )

    return {
        "id": f"route:{row.id}",
        "project_id": row.project_id or "",
        "recipe_id": "ask_with_context",
        "stage": stage,
        "status": packet_status,
        "source_user_id": row.source_user_id,
        "target_user_ids": [row.target_user_id],
        "current_target_user_ids": current_target,
        "authority_user_ids": [],
        "title": title,
        "summary": (row.framing or "")[:240],
        "intent": "Ask another teammate with framed context.",
        "source_refs": source_refs,
        "graph_refs": [],
        "evidence": evidence,
        "routed_signal_id": row.id,
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.responded_at) or _iso(row.created_at),
    }
