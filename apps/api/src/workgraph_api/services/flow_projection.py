"""Slice A — Flow Packet projection read service.

Implements the projection-only model from `docs/flow-packets-spec.md`:
Flow Packets are derived on read from existing graph rows. No new
table; no source-row mutations. Synthetic ids per §11 of the spec.

Recipes covered in Slice A:
  - ask_with_context     : RoutedSignalRow
  - promote_to_memory    : KbItemRow(status='draft' or 'pending-review')
                           with optional IMSuggestionRow evidence
  - handoff              : HandoffRow

Slice C will add the action router (FlowActionService); Slice E adds
the remaining recipes (`review`, `meeting_metabolism`, etc.). This file
is read-only — adding mutation here would violate the §15 invariant
"Flow projection does not mutate source rows."

The §6 packet shape is realized as a plain `dict` keyed exactly as the
TypeScript `FlowPacket` type the frontend will consume in Slice B. We
keep dicts (not Pydantic models) for two reasons:
  1. Dependent rows already serialize as dicts/json.
  2. The shape is meant to be slice-portable — locking it behind a
     pydantic class now would make Slice F's snapshot table awkward
     when the dict turns into a row.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    HandoffRow,
    IMSuggestionRow,
    KbItemRow,
    ProjectMemberRepository,
    RoutedSignalRow,
    TaskRow,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.flow_projection")

RecipeId = Literal[
    "ask_with_context",
    "promote_to_memory",
    "promote_task_to_plan",
    "crystallize_decision",
    "review",
    "handoff",
    "meeting_metabolism",
]

PacketStatus = Literal["active", "blocked", "completed", "rejected", "expired"]
Bucket = Literal[
    "needs_me",
    "waiting_on_others",
    "awaiting_membrane",
    "recent",
]


class FlowProjectionService:
    """Read-only projection. One method per source-row family."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    # ------------------------------------------------------------------
    # Public surface — list / get
    # ------------------------------------------------------------------

    async def list_for_project(
        self,
        *,
        project_id: str,
        viewer_user_id: str,
        status: PacketStatus | None = None,
        bucket: Bucket | None = None,
        recipe: RecipeId | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Project all derivable packets + a participants sidecar.

        Returns `{"packets": [...], "participants": {user_id: {...}}}`.

        The participants sidecar (D.a addition) lets the FE evidence
        block resolve user_id → display_name without N+1 fetches. One
        UserRepository.get_many call per list invocation.

        Filtering applied AFTER projection — Slice A is small enough
        that fan-out queries + python filter beats per-recipe SQL
        filters. Slice F reverses this if a snapshot table lands.

        Two projection-side filters are non-negotiable and apply BEFORE
        the user-facing filters:

        1. Owner enrichment — KB review and handoff packets receive
           `authority_user_ids = project_owner_ids` so `bucket=needs_me`
           works for owners (see flow-packets-spec §7.5 / §9.2).
        2. Viewer visibility — packets carrying personal information
           (route framings between two members) are filtered to
           {source, target, owners}. Project membership alone is not
           enough; that was the leak the v1 endpoint had.
        """
        async with session_scope(self._sessionmaker) as session:
            owner_ids = await _project_owner_ids(session, project_id)
            packets: list[dict[str, Any]] = []
            if recipe in (None, "ask_with_context"):
                packets.extend(await self._derive_route_packets(session, project_id))
            if recipe in (None, "promote_to_memory"):
                packets.extend(
                    await self._derive_kb_review_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "promote_task_to_plan"):
                packets.extend(
                    await self._derive_task_promote_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "handoff"):
                packets.extend(
                    await self._derive_handoff_packets(
                        session, project_id, owner_ids
                    )
                )

            # Visibility filter first — never let a non-participant member
            # read past it via a status / bucket / recipe combination.
            packets = [p for p in packets if _visible_to(p, viewer_user_id, owner_ids)]

            if status is not None:
                packets = [p for p in packets if p["status"] == status]
            if bucket is not None:
                packets = [
                    p for p in packets if _matches_bucket(p, viewer_user_id, bucket)
                ]

            packets.sort(
                key=lambda p: p["updated_at"] or p["created_at"], reverse=True
            )
            packets = packets[:limit]

            participants = await _resolve_participants(session, packets)

        return {"packets": packets, "participants": participants}

    # ------------------------------------------------------------------
    # ask_with_context — RoutedSignalRow
    # ------------------------------------------------------------------

    async def _derive_route_packets(
        self, session, project_id: str
    ) -> list[dict[str, Any]]:
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

    # ------------------------------------------------------------------
    # promote_to_memory — KbItemRow(draft/pending-review) + IMSuggestion
    # ------------------------------------------------------------------

    async def _derive_kb_review_packets(
        self, session, project_id: str, owner_ids: list[str]
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

    # ------------------------------------------------------------------
    # promote_task_to_plan — TaskRow(scope='personal') + IMSuggestion
    #                       (kind='membrane_review',
    #                        proposal.detail.candidate_kind='task_promote')
    #
    # F.1 — task circulation as a Flow Packet. The BE already accepts
    # promote requests at POST /api/tasks/{id}/promote → MembraneService
    # → IMSuggestion(membrane_review) for the team-room owner inbox.
    # That row was invisible in Active Flows because the projection
    # only knew about kb / route / handoff candidates. Now it shows up
    # as a "promote_task_to_plan" packet, owner-gated like KB review.
    # ------------------------------------------------------------------

    async def _derive_task_promote_packets(
        self, session, project_id: str, owner_ids: list[str]
    ) -> list[dict[str, Any]]:
        # Pending suggestions for THIS project. Same query shape as
        # _derive_kb_review_packets — small volume, python-side filter
        # for candidate_kind so we don't have to reach into JSON in SQL.
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
        # Build (suggestion, task_id) pairs filtered to task_promote kind.
        pairs: list[tuple[IMSuggestionRow, str]] = []
        for sug in suggestion_rows:
            task_id = _suggestion_task_promote_target_id(sug)
            if task_id is not None:
                pairs.append((sug, task_id))
        if not pairs:
            return []
        # Hydrate task rows in one query. A pending suggestion may
        # outlive its source row in degenerate cases (manual DB edit /
        # rollback); skip silently — we surface only packets we can
        # render fully.
        task_ids = list({tid for _sug, tid in pairs})
        task_rows = list(
            (
                await session.execute(
                    select(TaskRow).where(TaskRow.id.in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
        tasks_by_id = {t.id: t for t in task_rows}
        packets: list[dict[str, Any]] = []
        for sug, task_id in pairs:
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            packets.append(
                _task_promote_packet_from_rows(task, sug, owner_ids)
            )
        return packets

    # ------------------------------------------------------------------
    # handoff — HandoffRow
    # ------------------------------------------------------------------

    async def _derive_handoff_packets(
        self, session, project_id: str, owner_ids: list[str]
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


# ----------------------------------------------------------------------
# Row → packet conversions
# ----------------------------------------------------------------------


_ROUTE_ACTIVE_STATUSES = frozenset({"pending", "replied"})


def _route_packet_from_row(row: RoutedSignalRow) -> dict[str, Any]:
    """Map a RoutedSignalRow to an `ask_with_context` packet.

    Lifecycle (revised in C.1 — see flow-actions-c1-design.md §11):
      pending   → active, target is currently_blocking
      replied   → active, SOURCE is currently_blocking (awaiting
                  accept / counter / escalate / followup)
      accepted  → completed, terminal
      countered → completed, terminal (new packet active in its place)
      escalated → completed, terminal (gate fan-out is C.2)
      *         → completed (declined / expired)

    `target_user_ids` is participation history — always [target] for
    v1 routed signals (single-target). When delegate_up lands in C.2,
    this list grows; current implementation reads from the row's
    target_user_id field directly.
    """
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
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.responded_at) or _iso(row.created_at),
    }


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
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.created_at),
    }


def _task_promote_packet_from_rows(
    task: TaskRow, suggestion: IMSuggestionRow, owner_ids: list[str]
) -> dict[str, Any]:
    """Map a (TaskRow, IMSuggestionRow) pair to a `promote_task_to_plan`
    packet.

    The packet is alive while the suggestion is pending AND the task is
    still personal-scope. Once a project owner accepts the suggestion,
    `im._apply_proposal` flips the task to scope='plan' and sets the
    suggestion status='accepted'; both conditions failing is the
    "completed" terminal.

    Owner gating: same shape as kb_review — owners go in
    current_target_user_ids while alive so bucket=needs_me works.
    """
    # Only awaiting-membrane packets are projected — the upstream query
    # already filters on suggestion.status='pending'. Mirrors the
    # kb_review behavior: once the suggestion resolves, the packet drops
    # out of the projection (the task lives on as a plan row in
    # /detail/tasks, the suggestion lives on in audit logs).
    title = (task.title or "Untitled task").strip()
    if len(title) > 120:
        title = title[:117] + "…"
    description = (task.description or "")[:240]
    diff_summary = None
    proposal = (
        suggestion.proposal if isinstance(suggestion.proposal, dict) else None
    )
    if proposal:
        detail = proposal.get("detail")
        if isinstance(detail, dict):
            ds = detail.get("diff_summary")
            if isinstance(ds, str):
                diff_summary = ds
    timeline: list[dict[str, Any]] = [
        {
            "at": _iso(suggestion.created_at),
            "actor": "membrane",
            "actor_user_id": task.owner_user_id,
            "kind": "task_promotion_pending",
            "summary": (
                "Membrane staged a personal task for promote review."
            ),
            "refs": [
                {
                    "kind": "agent_run",
                    "id": suggestion.id,
                    "label": "membrane suggestion",
                }
            ],
        }
    ]
    next_actions: list[dict[str, Any]] = [
        {
            "id": "review",
            "label": "Open review",
            "kind": "open",
            "requires_membrane": True,
            "href": f"/projects/{task.project_id}/detail/im",
        }
    ]
    membrane_candidate: dict[str, Any] | None = {
        "kind": "task_promote",
        "action": "request_review",
        "conflict_with": [],
        "warnings": [],
    }
    return {
        # `task_promote:` namespace mirrors `kb:` / `handoff:` — synthetic
        # ids per spec §11. Suggestion id is the stable source key
        # (the task row may flip scope on accept).
        "id": f"task_promote:{suggestion.id}",
        "project_id": task.project_id or "",
        "recipe_id": "promote_task_to_plan",
        "stage": "awaiting_membrane",
        "status": "active",
        "source_user_id": task.owner_user_id,
        "target_user_ids": [],
        # Owners gate the promote — same as kb_review.
        "current_target_user_ids": list(owner_ids),
        "authority_user_ids": list(owner_ids),
        "title": title,
        "summary": diff_summary or description,
        "intent": "Promote a personal task into the team plan via Membrane review.",
        "source_refs": [],
        "graph_refs": [],
        "evidence": _empty_evidence(),
        "task_id": task.id,
        "im_suggestion_id": suggestion.id,
        "membrane_candidate": membrane_candidate,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(suggestion.created_at),
        "updated_at": _iso(suggestion.resolved_at) or _iso(suggestion.created_at),
    }


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
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.finalized_at) or _iso(row.created_at),
    }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _empty_evidence() -> dict[str, Any]:
    """KB review and handoff packets still emit empty shells in Slice
    D. Slice E will fill them when those recipes get their own
    evidence semantics. Route packets fill the shell directly in
    `_route_packet_from_row`."""
    return {
        "citations": [],
        "source_messages": [],
        "artifacts": [],
        "agent_runs": [],
        "human_gates": [],
        "uncertainty": [],
    }


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


async def _resolve_participants(
    session, packets: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Build a `{user_id: {display_name, username}}` sidecar from the
    set of user_ids referenced across all packets. One UserRepository
    query per /flows call; the FE looks up locally without N+1.

    Pulls from: source_user_id, target_user_ids, current_target_user_ids,
    authority_user_ids, evidence.human_gates[*].user_id, and
    timeline[*].actor_user_id.
    """
    ids: set[str] = set()
    for p in packets:
        if p.get("source_user_id"):
            ids.add(str(p["source_user_id"]))
        for uid in p.get("target_user_ids") or []:
            if uid:
                ids.add(str(uid))
        for uid in p.get("current_target_user_ids") or []:
            if uid:
                ids.add(str(uid))
        for uid in p.get("authority_user_ids") or []:
            if uid:
                ids.add(str(uid))
        evidence = p.get("evidence") or {}
        for gate in evidence.get("human_gates") or []:
            uid = gate.get("user_id")
            if uid:
                ids.add(str(uid))
        for ev in p.get("timeline") or []:
            uid = ev.get("actor_user_id")
            if uid:
                ids.add(str(uid))
    if not ids:
        return {}
    rows = await UserRepository(session).get_many(list(ids))
    return {
        row.id: {
            "display_name": row.display_name or row.username,
            "username": row.username,
        }
        for row in rows
    }


async def _project_owner_ids(session, project_id: str) -> list[str]:
    """Fetch project owner user_ids — once per `list_for_project` call.

    Used both for visibility filtering (owners can audit any packet)
    and for populating `authority_user_ids` on owner-gated recipes
    (KB review, handoff finalize). Returns [] when the project has no
    owner row, which prevents authority from leaking to all members
    on a misconfigured project.
    """
    members = await ProjectMemberRepository(session).list_for_project(project_id)
    return [m.user_id for m in members if m.role == "owner"]


def _visible_to(
    packet: dict[str, Any], viewer_user_id: str, owner_ids: list[str]
) -> bool:
    """Per-packet visibility filter.

    Project membership alone is NOT enough — that was Slice A's leak.
    Visibility rules per recipe:

    - ask_with_context: source / current target / participants /
      authority owners. Other members do not see Maya↔Raj routes.
    - promote_to_memory: drafter / current target (the owner pool) /
      authority owners. Casual members do not see drafts moving
      through Membrane review.
    - handoff: from_user / to_user (target_user_ids) / authority
      owners. Other members don't see the routine transfer until it
      finalizes.

    Owners always see — they need audit visibility per §10. The
    drafter / source always sees their own work.
    """
    if viewer_user_id in owner_ids:
        return True
    if packet.get("source_user_id") == viewer_user_id:
        return True
    if viewer_user_id in (packet.get("target_user_ids") or []):
        return True
    if viewer_user_id in (packet.get("current_target_user_ids") or []):
        return True
    if viewer_user_id in (packet.get("authority_user_ids") or []):
        return True
    return False


def _iso(value) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


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


def _suggestion_task_promote_target_id(sug: IMSuggestionRow) -> str | None:
    """Extract the personal task_id a task_promote suggestion targets.

    The proposal shape (per task_progress.py):
        {
          "action": "approve_membrane_candidate",
          "detail": {"candidate_kind": "task_promote", "task_id": "..."},
          ...
        }
    Returns None if the suggestion isn't a task_promote candidate.
    """
    proposal = sug.proposal if isinstance(sug.proposal, dict) else None
    if not proposal:
        return None
    detail = proposal.get("detail")
    if not isinstance(detail, dict):
        return None
    if detail.get("candidate_kind") != "task_promote":
        return None
    val = detail.get("task_id")
    return val if isinstance(val, str) else None


def _matches_bucket(packet: dict[str, Any], viewer_user_id: str, bucket: Bucket) -> bool:
    """Apply a bucket filter to a single packet from `viewer_user_id`'s
    perspective. The bucket model in §10 is:

      needs_me            — viewer is in current_target_user_ids
                            OR is the source on a packet awaiting their
                            accept (e.g. a returned reply).
      waiting_on_others   — viewer is the source and someone else is
                            holding the next action.
      awaiting_membrane   — packet is gated on a Membrane decision.
      recent              — completed within the last 14 days.

    Buckets are deliberately overlap-friendly: a packet that needs me
    can also be awaiting_membrane; the UI groups by primary bucket and
    can re-check the others as badges.
    """
    if bucket == "needs_me":
        if viewer_user_id in (packet.get("current_target_user_ids") or []):
            return True
        # Source-side "your reply is waiting" — when reply has landed
        # but source hasn't accepted yet. Slice C will model this with
        # a richer next_actions; for now route packets in 'completed'
        # status with no source-accept event count.
        return False
    if bucket == "waiting_on_others":
        if packet.get("source_user_id") != viewer_user_id:
            return False
        if packet.get("status") != "active":
            return False
        targets = packet.get("current_target_user_ids") or []
        return bool(targets) and viewer_user_id not in targets
    if bucket == "awaiting_membrane":
        candidate = packet.get("membrane_candidate")
        return candidate is not None and packet.get("status") == "active"
    if bucket == "recent":
        return packet.get("status") == "completed"
    return True
