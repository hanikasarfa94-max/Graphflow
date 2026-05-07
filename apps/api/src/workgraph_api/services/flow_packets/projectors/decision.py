"""crystallize_decision — IMSuggestionRow(kind=decision) [pending] +
DecisionRow [recently crystallized].

Decision Flow Packet Projection (DC slice). Closes the doc table's
`partial` row: makes conversation → decision → graph state
inspectable as Active Flows packets without a new mutation
surface.

Two source families:
  * Pending — IMSuggestionRow(kind='decision', status='pending').
    The suggestion's source message lives in some stream
    (DM / room / project). Smallest-relevant-vote: members of
    that stream are the authority. status='awaiting_authority'.
  * Crystallized — DecisionRow rows from the last 14 days. The
    row IS the lineage_output. status='completed'. Visibility
    is project-public for completed decisions (the audit
    surface judges and dogfooders need to inspect).

Gated proposals (GatedProposalRow → DecisionRow with
decision_class set) and conflict-resolution decisions are NOT
projected separately in v1; they show up via the same
DecisionRow row. Future slices can split out their own packets
if the FE needs to surface gate state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRow,
    MessageRepository,
    StreamMemberRepository,
)

from ..contracts import (
    EpistemicVisibilityScope,
    ReviewMethod,
    _accepted_scope,
    _empty_evidence,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


# Map message.kind → (target_kind, label) for the upstream-lineage edge.
# Only kinds that produce decision-relevant lineage are listed; an
# unknown kind on a source message returns None and the projection
# emits no upstream_ref. This is a closed allow-list by design — we'd
# rather omit the edge than misclassify it. Extending requires touching
# this map (a one-line ack of the new lineage shape).
_DECISION_UPSTREAM_KIND_MAP: dict[str, tuple[str, str]] = {
    # RoutingService kinds (services/routing.py call sites).
    "routed-inbound": ("routed_signal", "routed signal (inbound)"),
    "routed-reply": ("routed_signal", "routed reply"),
    "routed-prompt": ("routed_signal", "routed prompt (DM)"),
    "edge-route-proposal": ("routed_signal", "edge route proposal"),
    "edge-reply-frame": ("routed_signal", "source-side reply frame"),
    # KbItemService / Membrane review kinds.
    "membrane-review": ("kb_item", "membrane review (KB)"),
    "kb-archive-request": ("kb_item", "archive request"),
    # TaskProgressService.
    "task-promote": ("task", "task promote review"),
}


def _decision_upstream_ref(message_row: Any) -> dict[str, Any] | None:
    """Return a `{kind, id, label}` FlowRef for the upstream object a
    decision-suggestion's source message points at — or None when the
    message kind has no decision-relevant lineage shape we recognize.

    Read-only: depends only on the existing MessageRow.kind +
    .linked_id columns; no new schema and no agent rerun.
    """
    if not isinstance(message_row.kind, str):
        return None
    if not isinstance(message_row.linked_id, str) or not message_row.linked_id:
        return None
    mapping = _DECISION_UPSTREAM_KIND_MAP.get(message_row.kind)
    if mapping is None:
        return None
    target_kind, label = mapping
    return _flow_ref(target_kind, message_row.linked_id, label=label)


async def derive_decision_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    # Pending — IMSuggestion(kind=decision, status=pending).
    pending_rows = list(
        (
            await session.execute(
                select(IMSuggestionRow)
                .where(IMSuggestionRow.project_id == project_id)
                .where(IMSuggestionRow.kind == "decision")
                .where(IMSuggestionRow.status == "pending")
                .order_by(IMSuggestionRow.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    # Crystallized — last 14 days. Same window the `recent` bucket
    # uses for completed packets. Exclude rejected/skipped outcomes
    # so the projection focuses on actual graph state changes.
    window_start = datetime.now(timezone.utc) - timedelta(days=14)
    crystallized_rows = list(
        (
            await session.execute(
                select(DecisionRow)
                .where(DecisionRow.project_id == project_id)
                .where(DecisionRow.created_at >= window_start)
                .order_by(DecisionRow.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )

    # Resolve scope-stream membership for each pending suggestion's
    # source message. Cache stream → member ids so we don't
    # re-query per packet.
    msg_repo = MessageRepository(session)
    sm_repo = StreamMemberRepository(session)
    stream_members_by_id: dict[str, list[str]] = {}

    async def _stream_members(stream_id: str) -> list[str]:
        if stream_id in stream_members_by_id:
            return stream_members_by_id[stream_id]
        try:
            members = await sm_repo.list_for_stream(stream_id)
        except Exception:
            stream_members_by_id[stream_id] = []
            return []
        ids = [m.user_id for m in members]
        stream_members_by_id[stream_id] = ids
        return ids

    packets: list[dict[str, Any]] = []
    for sug in pending_rows:
        stream_id: str | None = None
        upstream_ref: dict[str, Any] | None = None
        try:
            source_msg = await msg_repo.get(sug.message_id)
            if source_msg is not None:
                stream_id = source_msg.stream_id
                # DC.1 follow-up — surface the upstream object the
                # source message references. `linked_id` is the
                # established way messages point back at the row
                # they were posted about (per RoutingService /
                # KbItemService / TaskProgressService call sites).
                # Map by message kind to the right target_kind so
                # the FlowRef is honest about what the id
                # references.
                upstream_ref = _decision_upstream_ref(source_msg)
        except Exception:
            stream_id = None
        authority_ids: list[str] = []
        if stream_id:
            authority_ids = await _stream_members(stream_id)
        # Owners always part of the authority pool — the
        # crystallization-accept path goes through im._apply_proposal
        # which any project member can hit, but we surface owners
        # specifically so bucket=needs_me works for them.
        for oid in owner_ids:
            if oid not in authority_ids:
                authority_ids.append(oid)
        packets.append(
            _decision_pending_packet_from_suggestion(
                suggestion=sug,
                source_stream_id=stream_id,
                authority_user_ids=authority_ids,
                owner_ids=owner_ids,
                upstream_ref=upstream_ref,
            )
        )

    for d in crystallized_rows:
        packets.append(_decision_crystallized_packet_from_row(d))

    return packets


def _decision_pending_packet_from_suggestion(
    *,
    suggestion: IMSuggestionRow,
    source_stream_id: str | None,
    authority_user_ids: list[str],
    owner_ids: list[str],
    upstream_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map a pending IMSuggestion(kind='decision') to a
    `crystallize_decision` packet in its in-flight phase.

    The suggestion has been classified by IMAssist as decision-shaped
    but no DecisionRow has been written yet — owner / scoped voters
    decide whether to crystallize. Visible to: authority pool +
    project owners, same as task_promote.
    """
    proposal = (
        suggestion.proposal if isinstance(suggestion.proposal, dict) else None
    ) or {}
    summary = (proposal.get("summary") or suggestion.reasoning or "")[:240]
    title = summary or "Decision suggestion"
    if len(title) > 120:
        title = title[:117] + "…"

    timeline = [
        {
            "at": _iso(suggestion.created_at),
            "actor": "im_assist_agent",
            "kind": "decision_suggestion_pending",
            "summary": "IMAssist classified a turn as decision-shaped.",
            "refs": [
                _flow_ref(
                    "im_suggestion", suggestion.id, label="decision suggestion"
                )
            ],
        }
    ]

    next_actions: list[dict[str, Any]] = [
        {
            "id": "review",
            "label": "Open review",
            "kind": "open",
            "requires_membrane": False,
            "href": f"/projects/{suggestion.project_id}/detail/im",
        }
    ]

    required_evidence = [
        _flow_ref(
            "im_suggestion", suggestion.id, label="decision suggestion"
        ),
        _flow_ref(
            "source_message",
            suggestion.message_id,
            label="originating message",
        ),
    ]
    # DC.1 follow-up — upstream lineage. When the source message points
    # at an upstream row (e.g. a routed-reply pointing at the routed
    # signal that produced this discussion), surface it as evidence.
    # Honest-by-design: only known kinds in _DECISION_UPSTREAM_KIND_MAP
    # produce a ref; unknown kinds are silently omitted rather than
    # mis-typed.
    if upstream_ref is not None:
        required_evidence.append(upstream_ref)
    if source_stream_id:
        required_evidence.append(
            _flow_ref(
                "stream",
                source_stream_id,
                label="scope stream (smallest-relevant-vote)",
            )
        )
    # Confidence is not strictly evidence but it shapes the agent's
    # certainty floor. Surface it as a typed ref so audit can read it.
    if isinstance(suggestion.confidence, (int, float)):
        required_evidence.append(
            _flow_ref(
                "confidence",
                None,
                label=f"agent confidence={suggestion.confidence:.2f}",
            )
        )

    transition_contract = _transition_contract(
        source_state="discussion_or_suggestion",
        target_state="canonical_decision",
        # owner_acceptance is the operative method on the
        # IMSuggestion-pending path — a project owner accepts and
        # `_apply_proposal` calls DecisionRepository.create. Vote
        # paths come from gated_proposals / silent_consensus rather
        # than from this row family. Honest naming.
        review_method="owner_acceptance",
        mutation_service="DecisionRepository+IMService+MembraneService",
        status="awaiting_authority",
        required_evidence=required_evidence,
        authority_user_ids=list(authority_user_ids),
        # Lineage is empty while pending — no DecisionRow yet.
        lineage_output=[],
    )

    # E2 — pending decision crystallize as a `decision` epistemic
    # event. Status = review_pending; M4 runs but advisory-only, so
    # membrane_policy = "advisory". target_audience = scope-stream
    # members + owners (the authority pool).
    epistemic_event = _epistemic_event(
        kind="decision",
        status="review_pending",
        proposition=summary,
        source_actor_id=None,
        target_audience=list(authority_user_ids),
        # Visibility scope is the scope-stream when set; we don't
        # have stream type at hand here, so use "project" as the
        # honest default — the scope_stream_id ref is in
        # required_evidence so consumers can resolve.
        visibility_scope="project",
        accepted_scope=None,
        evidence_refs=required_evidence,
        preconditions=[],
        authority_required=list(authority_user_ids),
        membrane_policy="advisory",
        update_effects=["canonical_decision"],
        lineage_output=[],
        supersedes=[],
        expires_at=None,
    )

    return {
        "id": f"decision_pending:{suggestion.id}",
        "project_id": suggestion.project_id,
        "recipe_id": "crystallize_decision",
        "stage": "awaiting_crystallization",
        "status": "active",
        "source_user_id": None,
        "target_user_ids": [],
        "current_target_user_ids": list(authority_user_ids),
        "authority_user_ids": list(authority_user_ids),
        "title": title,
        "summary": summary,
        "intent": (
            "Crystallize a discussion turn into a canonical decision."
        ),
        "source_refs": [
            _flow_ref(
                "im_suggestion", suggestion.id, label="decision suggestion"
            )
        ],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "im_suggestion_id": suggestion.id,
        "decision_id": None,
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(suggestion.created_at),
        "updated_at": _iso(suggestion.created_at),
    }


def _decision_crystallized_packet_from_row(
    row: DecisionRow,
) -> dict[str, Any]:
    """Map a crystallized DecisionRow to a completed
    `crystallize_decision` packet. The row IS the lineage_output —
    consumers can dereference DecisionRow.id for the full audit
    record."""
    headline = (row.custom_text or row.rationale or "Decision")[:200]
    title = headline.splitlines()[0] if headline else "Decision"
    if len(title) > 120:
        title = title[:117] + "…"

    timeline: list[dict[str, Any]] = []
    if row.source_suggestion_id:
        timeline.append(
            {
                "at": _iso(row.created_at),
                "actor": "im_assist_agent",
                "kind": "decision_suggestion_pending",
                "summary": "Decision originated as an IMAssist suggestion.",
                "refs": [
                    _flow_ref(
                        "im_suggestion",
                        row.source_suggestion_id,
                        label="source suggestion",
                    )
                ],
            }
        )
    timeline.append(
        {
            "at": _iso(row.created_at),
            "actor": "human",
            "actor_user_id": row.resolver_id,
            "kind": "decision_crystallized",
            "summary": "Decision crystallized into the graph.",
            "refs": [
                _flow_ref(
                    "decision",
                    row.id,
                    label=row.custom_text or "decision",
                )
            ],
        }
    )

    # review_method discriminates by upstream path. The DecisionRow
    # carries the breadcrumbs:
    #   * gated_via_proposal_id set → gated/vote path
    #   * scope_stream_id set + no gated_via_proposal_id → smallest-
    #     relevant-vote path
    #   * else → owner_acceptance (the IMSuggestion accept gate)
    if row.gated_via_proposal_id:
        review_method: ReviewMethod = "vote"
    elif row.scope_stream_id:
        review_method = "vote"
    else:
        review_method = "owner_acceptance"

    required_evidence: list[dict[str, Any]] = []
    if row.source_suggestion_id:
        required_evidence.append(
            _flow_ref(
                "im_suggestion",
                row.source_suggestion_id,
                label="source suggestion",
            )
        )
    if row.conflict_id:
        required_evidence.append(
            _flow_ref("conflict", row.conflict_id, label="originating conflict")
        )
    if row.gated_via_proposal_id:
        required_evidence.append(
            _flow_ref(
                "gated_proposal",
                row.gated_via_proposal_id,
                label="gated proposal",
            )
        )
    if row.scope_stream_id:
        required_evidence.append(
            _flow_ref(
                "stream", row.scope_stream_id, label="scope stream (vote)"
            )
        )
    # M5.1 Lane B — persisted M4 membrane warnings + supersedes ref
    # live in apply_detail; surface them as evidence so the flow
    # packet records the membrane's verdict honestly. Empty / missing
    # apply_detail keeps the prior shape.
    apply_detail = row.apply_detail if isinstance(row.apply_detail, dict) else {}
    membrane_warnings_persisted: list[str] = [
        w for w in (apply_detail.get("membrane_warnings") or [])
        if isinstance(w, str)
    ]
    for idx, warning in enumerate(membrane_warnings_persisted):
        required_evidence.append(
            _flow_ref(
                "membrane_warning",
                f"{row.id}:{idx}",
                label=warning[:160],
            )
        )
    supersedes_persisted: list[dict[str, Any]] = []
    raw_supersedes = apply_detail.get("supersedes")
    if isinstance(raw_supersedes, str) and raw_supersedes:
        supersedes_persisted.append(
            _flow_ref(
                "decision",
                raw_supersedes,
                label="supersedes prior decision",
            )
        )
    elif isinstance(raw_supersedes, list):
        for ref in raw_supersedes:
            if isinstance(ref, str) and ref:
                supersedes_persisted.append(
                    _flow_ref(
                        "decision", ref, label="supersedes prior decision"
                    )
                )

    lineage_output = [
        _flow_ref(
            "decision",
            row.id,
            label=row.custom_text or "decision",
            apply_outcome=row.apply_outcome,
        )
    ]
    if row.applied_at:
        lineage_output.append(
            _flow_ref(
                "decision_applied",
                row.id,
                label="apply executed",
                at=_iso(row.applied_at),
                apply_outcome=row.apply_outcome,
            )
        )

    transition_contract = _transition_contract(
        source_state="discussion_or_suggestion",
        target_state="canonical_decision",
        review_method=review_method,
        mutation_service="DecisionRepository+IMService+MembraneService",
        status="completed",
        required_evidence=required_evidence,
        authority_user_ids=[],
        lineage_output=lineage_output,
    )

    # E2 — crystallized decision as a `decision` epistemic event,
    # status=accepted_for_scope. The `accepted_scope` block names
    # the smallest-relevant-vote scope (the scope_stream_id when
    # set) or falls back to project. Visibility scope mirrors:
    # `room` when scope_stream_id is set, else `project`.
    ep_visibility: EpistemicVisibilityScope = (
        "room" if row.scope_stream_id else "project"
    )
    ep_accepted_scope = _accepted_scope(
        scope_type=ep_visibility,
        scope_id=row.scope_stream_id or row.project_id,
        accepted_by_user_ids=[row.resolver_id] if row.resolver_id else [],
        accepted_at=_iso(row.applied_at) or _iso(row.created_at),
    )
    epistemic_event = _epistemic_event(
        kind="decision",
        # Use accepted_for_scope rather than canonical: the decision is
        # accepted at the named scope. canonical implies project-wide
        # acceptance regardless of scope, which a room-scoped decision
        # explicitly is NOT.
        status="accepted_for_scope",
        proposition=headline[:200],
        source_actor_id=row.resolver_id,
        target_audience=[],
        visibility_scope=ep_visibility,
        accepted_scope=ep_accepted_scope,
        evidence_refs=required_evidence,
        preconditions=[],
        authority_required=[],
        membrane_policy="advisory",
        update_effects=["canonical_decision"],
        lineage_output=lineage_output,
        # M5.1 Lane B — supersedes ref persisted in apply_detail by
        # IMService at crystallize time, lifted onto the epistemic
        # event so consumers can trace decision-revisions without
        # touching the source suggestion (which has resolved by now).
        supersedes=supersedes_persisted,
        expires_at=None,
    )

    return {
        "id": f"decision:{row.id}",
        "project_id": row.project_id,
        "recipe_id": "crystallize_decision",
        "stage": "completed",
        "status": "completed",
        "source_user_id": row.resolver_id,
        "target_user_ids": [],
        "current_target_user_ids": [],
        "authority_user_ids": [],
        "title": title,
        "summary": headline[:240],
        "intent": (
            "Decision crystallized — canonical graph state."
        ),
        "source_refs": [
            _flow_ref("decision", row.id, label="decision row"),
        ],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "im_suggestion_id": row.source_suggestion_id,
        "decision_id": row.id,
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": [],
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.applied_at) or _iso(row.created_at),
    }
