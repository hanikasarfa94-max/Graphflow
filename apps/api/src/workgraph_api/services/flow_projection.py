"""Slice A — Flow Packet projection read service (facade).

Phase A of the Architecture Organization Pass moved the per-recipe
projector logic, contract factories, and visibility helpers into the
`flow_packets/` package. This module is now a thin orchestration
facade that keeps the existing public import path stable:

    from workgraph_api.services import FlowProjectionService

Pipeline (unchanged from the pre-refactor implementation):

    1. resolve project owners                 — visibility module
    2. fan out to per-recipe projectors       — projectors/*
    3. visibility filter                      — visibility module
    4. status / bucket filter                 — visibility module
    5. sort + limit                           — sorting module
    6. participants sidecar                   — participants module

Implements the projection-only model from `docs/flow-packets-spec.md`:
Flow Packets are derived on read from existing graph rows. No new
table; no source-row mutations. Synthetic ids per §11 of the spec.

This facade is read-only — adding mutation here would violate the
§15 invariant "Flow projection does not mutate source rows."
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import RoutedSignalRow, session_scope

from .flow_packets.contracts import Bucket, PacketStatus, RecipeId
from .flow_packets.participants import _resolve_participants
from .flow_packets.projectors import (
    derive_decision_packets,
    derive_handoff_packets,
    derive_kb_review_packets,
    derive_manual_invite_packets,
    derive_manual_room_packets,
    derive_manual_skill_change_packets,
    derive_route_packets,
    derive_task_promote_packets,
)
from .flow_packets.projectors.route import _route_packet_from_row
from .flow_packets.sorting import sort_and_limit
from .flow_packets.visibility import (
    _matches_bucket,
    _project_owner_ids,
    _visible_to,
)


# ---- singleton get_packet errors -----------------------------------------


class FlowSingletonError(Exception):
    """Base for FlowProjectionService.get_packet errors. Each subclass
    carries a service-level error code that the router maps to an HTTP
    status. The router stays thin per the CLAUDE.md invariant."""

    code: str = "flow_request_error"


class FlowSingletonNotFound(FlowSingletonError):
    code = "flow_request_not_found"


class FlowSingletonKindUnsupported(FlowSingletonError):
    code = "not_supported_yet"

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class FlowSingletonForbidden(FlowSingletonError):
    code = "not_a_scope_member"

_log = logging.getLogger("workgraph.api.flow_projection")


class FlowProjectionService:
    """Read-only projection. Delegates per-recipe derivation to the
    `flow_packets/projectors/` modules; orchestrates visibility,
    filtering, sort, and the participants sidecar."""

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

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
                packets.extend(
                    await derive_route_packets(session, project_id, owner_ids)
                )
            if recipe in (None, "promote_to_memory"):
                packets.extend(
                    await derive_kb_review_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "promote_task_to_plan"):
                packets.extend(
                    await derive_task_promote_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "handoff"):
                packets.extend(
                    await derive_handoff_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "crystallize_decision"):
                packets.extend(
                    await derive_decision_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "manual_create_room"):
                packets.extend(
                    await derive_manual_room_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "manual_skill_change"):
                packets.extend(
                    await derive_manual_skill_change_packets(
                        session, project_id, owner_ids
                    )
                )
            if recipe in (None, "manual_invite"):
                packets.extend(
                    await derive_manual_invite_packets(
                        session, project_id, owner_ids
                    )
                )

            # Visibility filter first — never let a non-participant member
            # read past it via a status / bucket / recipe combination.
            packets = [
                p for p in packets if _visible_to(p, viewer_user_id, owner_ids)
            ]

            if status is not None:
                packets = [p for p in packets if p["status"] == status]
            if bucket is not None:
                packets = [
                    p for p in packets if _matches_bucket(p, viewer_user_id, bucket)
                ]

            packets = sort_and_limit(packets, limit)

            participants = await _resolve_participants(session, packets)

        return {"packets": packets, "participants": participants}

    # ---- singleton (RW-9) ------------------------------------------------

    async def get_packet(
        self,
        *,
        flow_id: str,
        viewer_user_id: str,
    ) -> dict[str, Any]:
        """Singleton read for one flow packet.

        Currently supports `flow_id` of shape `route:<routed_signal_id>`
        (the only packet kind with a real text-response surface on the
        target side — RoutingService.reply). Other kinds raise
        FlowSingletonKindUnsupported, so the router can return a
        machine-readable signal to the FE drawer ("respond is not wired
        for this kind yet").

        Returns the envelope:

            {
                "flow_request": <packet shape from the projector,
                                 enriched with singleton-only fields>,
                "participants": {user_id: {display_name, username}},
                "respondability": {
                    "respondable": bool,
                    "reason": str | None,
                    "response_kind": "direct_response" | None,
                },
            }
        """
        kind, _, ref_id = flow_id.partition(":")
        if not kind or not ref_id:
            raise FlowSingletonNotFound(flow_id)

        async with session_scope(self._sessionmaker) as session:
            if kind != "route":
                # Confirm the kind is known but unwired before raising
                # — gives the FE a stable string to render against.
                _KNOWN_KINDS = {
                    "kb",
                    "handoff",
                    "task_promote",
                    "decision",
                    "manual_room",
                    "manual_skill",
                    "manual_invite",
                }
                if kind not in _KNOWN_KINDS:
                    raise FlowSingletonNotFound(flow_id)
                raise FlowSingletonKindUnsupported(kind)

            row = await session.get(RoutedSignalRow, ref_id)
            if row is None or not row.project_id:
                raise FlowSingletonNotFound(flow_id)

            owner_ids = await _project_owner_ids(session, row.project_id)
            packet = _route_packet_from_row(row)

            # Singleton-only enrichment. The list shape stays lean; the
            # detail page renders the full framing + AI background +
            # judgment options that the list never carried.
            packet["framing_full"] = row.framing or ""
            packet["background"] = list(row.background_json or [])
            packet["options"] = list(row.options_json or [])
            packet["source_stream_id"] = row.source_stream_id
            packet["target_stream_id"] = row.target_stream_id
            # Surface the raw signal status alongside the projected
            # `status` so the FE knows whether respond is even an
            # option in principle (pending vs replied/accepted/...).
            packet["raw_status"] = row.status or "pending"

            if not _visible_to(packet, viewer_user_id, owner_ids):
                raise FlowSingletonForbidden(flow_id)

            respondability = _route_respondability(
                row=row, viewer_user_id=viewer_user_id
            )
            participants = await _resolve_participants(session, [packet])

        return {
            "flow_request": packet,
            "participants": participants,
            "respondability": respondability,
        }


def _route_respondability(
    *,
    row: RoutedSignalRow,
    viewer_user_id: str,
) -> dict[str, Any]:
    """Compute whether `viewer_user_id` can respond to this routed
    signal via the direct-response surface.

    The text response goes through RoutingService.reply, which the
    PersonalStreamService wraps. The two preconditions are:
      1. The signal is still in `pending` status.
      2. The viewer is the signal's target_user_id.

    Any other state returns respondable=false with a stable reason
    string the FE renders bilingually.
    """
    if (row.status or "pending") != "pending":
        return {
            "respondable": False,
            "reason": f"route_status_{row.status or 'unknown'}",
            "response_kind": "direct_response",
        }
    if viewer_user_id != row.target_user_id:
        return {
            "respondable": False,
            "reason": "not_the_target",
            "response_kind": "direct_response",
        }
    return {
        "respondable": True,
        "reason": None,
        "response_kind": "direct_response",
    }
