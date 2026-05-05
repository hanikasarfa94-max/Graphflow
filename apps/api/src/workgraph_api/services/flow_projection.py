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
    session_scope,
)

_log = logging.getLogger("workgraph.api.flow_projection")

RecipeId = Literal[
    "ask_with_context",
    "promote_to_memory",
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
    ) -> list[dict[str, Any]]:
        """Project all derivable packets for `project_id`, filtered as
        requested. Filtering applied AFTER projection — Slice A is small
        enough that fan-out queries + python filter beats per-recipe SQL
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
            packets = [p for p in packets if _matches_bucket(p, viewer_user_id, bucket)]

        packets.sort(key=lambda p: p["updated_at"] or p["created_at"], reverse=True)
        return packets[:limit]

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


def _route_packet_from_row(row: RoutedSignalRow) -> dict[str, Any]:
    """Map a RoutedSignalRow to an `ask_with_context` packet.

    Status mapping:
      pending  → active   (target hasn't replied)
      replied  → completed (target replied)
      *        → completed (declined / expired / accepted — terminal)

    `current_target_user_ids` is [target] while pending; [] once replied.
    `target_user_ids` is participation history — always [target] for v1
    routed signals (single-target). When delegate_up lands in Slice C,
    this list grows; the projection reads from a future
    `participants_json` column, but for now it's just the original target.
    """
    status_alive = (row.status or "pending") == "pending"
    packet_status: PacketStatus = "active" if status_alive else "completed"
    title = (row.framing or "").strip().splitlines()[0] if row.framing else "(no framing)"
    if len(title) > 120:
        title = title[:117] + "…"
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
    next_actions: list[dict[str, Any]] = []
    if status_alive:
        # Target answers from their personal stream / inbox; href deep-
        # links to /inbox where the routed-inbound card renders.
        next_actions.append(
            {
                "id": "reply",
                "label": "Reply",
                "kind": "open",
                "actor_user_id": row.target_user_id,
                "requires_membrane": False,
                "href": "/inbox",
            }
        )
    return {
        "id": f"route:{row.id}",
        "project_id": row.project_id or "",
        "recipe_id": "ask_with_context",
        "stage": "awaiting_target" if status_alive else "completed",
        "status": packet_status,
        "source_user_id": row.source_user_id,
        "target_user_ids": [row.target_user_id],
        "current_target_user_ids": [row.target_user_id] if status_alive else [],
        "authority_user_ids": [],
        "title": title,
        "summary": (row.framing or "")[:240],
        "intent": "Ask another teammate with framed context.",
        "source_refs": [],
        "graph_refs": [],
        "evidence": _empty_evidence(),
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
        # Handoff finalize lives in the team / handoff prep surface;
        # /projects/{pid}/team is the durable entry point for now.
        # Slice B may swap to a deep-link if a dedicated route lands.
        next_actions.append(
            {
                "id": "finalize",
                "label": "Open handoff",
                "kind": "open",
                "requires_membrane": False,
                "href": f"/projects/{row.project_id}/team",
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
    """Slice A renders an empty evidence packet shell. Slice D fills it."""
    return {
        "citations": [],
        "source_messages": [],
        "artifacts": [],
        "agent_runs": [],
        "human_gates": [],
        "uncertainty": [],
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
    return None


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
