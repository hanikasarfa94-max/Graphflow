"""Slice C.1 — FlowActionService.

Thin dispatcher that maps a flow_id + action to the right domain method.
Per `docs/flow-actions-c1-design.md` and CLAUDE.md thin-router invariant,
this service does NOT own domain mutation logic — it parses the flow_id,
validates recipe support, and dispatches to RoutingService.source_*.

C.1 supports `ask_with_context` only; KB review and handoff actions land
in later slices when their action surfaces are designed.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from .routing import RoutingService

_log = logging.getLogger("workgraph.api.flow_actions")


# ---- Error contract -----------------------------------------------------


class FlowActionError(Exception):
    """Single exception class carrying a code + detail. The router maps
    `.code` to an HTTP status via a small dict literal — no business
    logic in the router.
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


# Code → HTTP status mapping. Kept here next to the codes themselves so
# adding a new error code requires touching one place. Memo §3.
ERROR_HTTP_STATUS: dict[str, int] = {
    "flow_not_found": 404,
    "unsupported_flow_recipe": 400,
    "unsupported_action": 400,
    "not_source_user": 403,
    "not_ready_for_source_action": 409,
    "validation_error": 422,
    "domain_error": 400,
}


ActionKind = Literal[
    "accept",
    "counter_back",
    "escalate_to_gate",
    "custom_followup",
]


# ---- Service ------------------------------------------------------------


class FlowActionService:
    """Dispatch table only. Owns no domain logic.

    Adding a recipe (KB review, handoff finalize) is a deliberate
    addition to `_dispatch_route` or a sibling `_dispatch_kb` /
    `_dispatch_handoff` method — emergent behavior is not a feature
    of this service.
    """

    def __init__(self, routing_service: RoutingService) -> None:
        self._routing = routing_service

    async def execute(
        self,
        *,
        flow_id: str,
        viewer_user_id: str,
        action: ActionKind,
        framing: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Resolve flow_id → recipe, dispatch action to the recipe's
        domain service. Raises `FlowActionError` on any failure path
        the spec enumerates; the router catches and maps to HTTP.

        Caller has already done membership + Pydantic validation; this
        layer assumes the inputs are well-shaped. (Pydantic's
        discriminated union catches missing `framing` on counter_back
        / custom_followup at request parse time, returning 422 before
        we get here.)
        """
        kind, source_id = _parse_flow_id(flow_id)
        if kind != "route":
            raise FlowActionError(
                "unsupported_flow_recipe",
                detail=f"recipe={kind} not supported in C.1",
            )
        return await self._dispatch_route(
            signal_id=source_id,
            viewer_user_id=viewer_user_id,
            action=action,
            framing=framing,
            note=note,
        )

    async def _dispatch_route(
        self,
        *,
        signal_id: str,
        viewer_user_id: str,
        action: ActionKind,
        framing: str | None,
        note: str | None,
    ) -> dict[str, Any]:
        """`ask_with_context` recipe — four supported source-side
        actions. Body validation already checked `framing` is present
        when the action requires it; we re-assert here for safety.
        """
        if action == "accept":
            domain = await self._routing.source_accept(
                signal_id=signal_id,
                source_user_id=viewer_user_id,
                note=note,
            )
        elif action == "escalate_to_gate":
            domain = await self._routing.source_escalate(
                signal_id=signal_id,
                source_user_id=viewer_user_id,
                note=note,
            )
        elif action == "counter_back":
            if not framing:
                raise FlowActionError(
                    "validation_error",
                    detail="framing required for counter_back",
                )
            domain = await self._routing.source_counter(
                signal_id=signal_id,
                source_user_id=viewer_user_id,
                framing=framing,
                note=note,
            )
        elif action == "custom_followup":
            if not framing:
                raise FlowActionError(
                    "validation_error",
                    detail="framing required for custom_followup",
                )
            domain = await self._routing.source_followup(
                signal_id=signal_id,
                source_user_id=viewer_user_id,
                framing=framing,
                note=note,
            )
        else:
            # Pydantic discriminator should reject before we arrive,
            # but defense-in-depth: a Literal narrowing slip would
            # otherwise produce a confusing 500.
            raise FlowActionError(
                "unsupported_action", detail=f"action={action}"
            )

        if not domain.get("ok"):
            err = domain.get("error", "domain_error")
            # Domain error codes mapping back to public C.1 codes.
            if err == "signal_not_found":
                raise FlowActionError("flow_not_found", detail=err)
            if err == "not_the_source":
                raise FlowActionError("not_source_user", detail=err)
            if err == "not_ready_for_source_action":
                raise FlowActionError("not_ready_for_source_action", detail=err)
            # `domain_error` and anything unexpected → domain_error
            # with the sub-detail.
            raise FlowActionError(
                "domain_error",
                detail=str(domain.get("detail") or err),
            )

        # Map RoutingService domain success shape → flow action response.
        # The caller (router) wraps in {ok: True, ...}; we return the
        # interesting fields. Original packet stays the original packet
        # id; spawned, if any, is the new packet id.
        flow_id = f"route:{signal_id}"
        spawned_signal_id = domain.get("spawned_signal_id")
        spawned_flow_id = (
            f"route:{spawned_signal_id}" if spawned_signal_id else None
        )
        # Per memo §4.4: custom_followup leaves the original at
        # underlying status 'replied', which projects to packet status
        # 'completed'. Mirror that mapping here so the FE doesn't have
        # to re-derive.
        domain_status = domain.get("status")
        packet_status = "active" if domain_status == "pending" else "completed"
        return {
            "flow_id": flow_id,
            "status": packet_status,
            "spawned_flow_id": spawned_flow_id,
        }


# ---- Helpers ------------------------------------------------------------


def _parse_flow_id(flow_id: str) -> tuple[str, str]:
    """Split `kind:source_id` synthetic id. Returns (kind, source_id).
    Raises FlowActionError(flow_not_found) on malformed input — the
    most likely cause of a missing prefix is a stale caller, which
    looks identical to a missing row from the user's perspective.
    """
    if not flow_id or ":" not in flow_id:
        raise FlowActionError(
            "flow_not_found", detail="flow_id missing recipe prefix"
        )
    kind, _, source_id = flow_id.partition(":")
    if not source_id:
        raise FlowActionError(
            "flow_not_found", detail="flow_id missing source row id"
        )
    return kind, source_id


__all__ = [
    "ActionKind",
    "ERROR_HTTP_STATUS",
    "FlowActionError",
    "FlowActionService",
]
