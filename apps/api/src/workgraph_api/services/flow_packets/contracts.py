"""Flow Packet contract factories + type literals.

Centralized so every recipe's packet builder produces the same shape,
and so the test suite can assert on a single key structure. Hard rules
from the spec are enforced INSIDE these factories — see the docstrings
for `_transition_contract` and `_epistemic_event`.

This module is intentionally side-effect-free: no DB access, no row
types, no I/O. Anything that needs SQLAlchemy belongs in a projector.
"""
from __future__ import annotations

from typing import Any, Literal

# ----------------------------------------------------------------------
# Recipe / status / bucket literals
# ----------------------------------------------------------------------

RecipeId = Literal[
    "ask_with_context",
    "promote_to_memory",
    "promote_task_to_plan",
    "crystallize_decision",
    "manual_create_room",
    "manual_skill_change",
    "manual_invite",
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


# ----------------------------------------------------------------------
# Transition Contract types (T1) — see
# `docs/north-star-graph-system.md §Transition Contracts`. The contract
# is a per-packet read-only field that names the state transition the
# packet governs. The vocabulary is small, machine-readable, and
# stable across recipes so an audit / FE / agent can ask "what
# boundary does this signal cross?" without parsing prose.
# ----------------------------------------------------------------------

ReviewMethod = Literal[
    "none",
    "routing_reply",
    "membrane_review",
    "vote",
    "owner_acceptance",
    "agent_semantic_review",
]

TransitionStatus = Literal[
    "satisfied",
    "awaiting_evidence",
    "awaiting_authority",
    "blocked",
    "completed",
]


def _flow_ref(kind: str, id_: str | None, **extra: Any) -> dict[str, Any]:
    """Tiny factory for the `{kind, id, ...}` ref shape used in
    transition_contract.required_evidence / lineage_output. `id` is
    allowed to be None for refs that name a class of evidence
    without a single row id (e.g. `{"kind": "framing"}`)."""
    out: dict[str, Any] = {"kind": kind}
    if id_ is not None:
        out["id"] = id_
    out.update(extra)
    return out


def _transition_contract(
    *,
    source_state: str,
    target_state: str,
    review_method: ReviewMethod,
    mutation_service: str,
    status: TransitionStatus,
    required_evidence: list[dict[str, Any]] | None = None,
    authority_user_ids: list[str] | None = None,
    lineage_output: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a TransitionContract envelope for a flow packet.

    Centralized so every recipe's packet builder produces the same
    shape, and so the test suite can assert on a single key
    structure. Empty lists default to [] (not None) — the FE / audit
    code treats absence as "not yet known", which is different from
    "no evidence required".
    """
    return {
        "source_state": source_state,
        "target_state": target_state,
        "required_evidence": list(required_evidence or []),
        "authority_user_ids": list(authority_user_ids or []),
        "review_method": review_method,
        "mutation_service": mutation_service,
        "lineage_output": list(lineage_output or []),
        "status": status,
    }


# ----------------------------------------------------------------------
# Epistemic Event Contract types (E1) — see
# `docs/north-star-graph-system.md §Modal Logic / Public Announcement
# Logic / Dynamic Epistemic Logic Inspiration`. The contract is a
# read-only envelope per packet that names the epistemic state
# transition the packet governs.
#
# Hard rules enforced here (and in tests):
#   * `kind` and `status` are SEPARATE fields. `kind` is the type of
#     epistemic content (a question / claim / memory / decision …);
#     `status` is the lifecycle state (proposed / review_pending /
#     accepted_for_scope / canonical …). Conflating them was the
#     pre-E1 mistake we explicitly avoid.
#   * No `common_knowledge` boolean. PAL / DEL define common
#     knowledge as the infinite intersection "everyone knows that
#     everyone knows that…"; we cannot verify it and refuse to ship
#     it. The shipped primitive is `accepted_for_scope`.
#   * `accepted_for_scope` status MUST come with an `accepted_scope`
#     block naming which scope and which users accepted.
#   * `review_pending` status MUST carry non-empty
#     `authority_required` unless the packet is system-only — known
#     gates with unknown actors is a worse failure mode than no
#     contract at all.
# ----------------------------------------------------------------------

EpistemicKind = Literal[
    "question",
    "claim",
    "proposal",
    "decision",
    "memory",
    "task_transition",
    "capability_claim",
    "handoff",
    "risk",
    "constraint",
]

EpistemicStatus = Literal[
    "private",
    "draft",
    "hypothesis",
    "proposed",
    "review_pending",
    "accepted_for_scope",
    "canonical",
    "validated",
    "superseded",
    "rejected",
    "archived",
]

EpistemicVisibilityScope = Literal[
    "personal",
    "room",
    "project",
    "department",
    "enterprise",
]

EpistemicMembranePolicy = Literal[
    "none",
    "auto_merge",
    "request_review",
    "request_clarification",
    "reject",
    "advisory",
]


def _accepted_scope(
    *,
    scope_type: EpistemicVisibilityScope,
    scope_id: str | None,
    accepted_by_user_ids: list[str] | None = None,
    accepted_at: str | None = None,
) -> dict[str, Any]:
    """Factory for the `accepted_scope` sub-envelope. Required
    whenever `epistemic_event.status == 'accepted_for_scope'`."""
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "accepted_by_user_ids": list(accepted_by_user_ids or []),
        "accepted_at": accepted_at,
    }


def _epistemic_event(
    *,
    kind: EpistemicKind,
    status: EpistemicStatus,
    proposition: str,
    source_actor_id: str | None,
    target_audience: list[str] | None = None,
    visibility_scope: EpistemicVisibilityScope = "project",
    accepted_scope: dict[str, Any] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    preconditions: list[str] | None = None,
    authority_required: list[str] | None = None,
    membrane_policy: EpistemicMembranePolicy = "none",
    update_effects: list[str] | None = None,
    lineage_output: list[dict[str, Any]] | None = None,
    supersedes: list[dict[str, Any]] | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Build an EpistemicEvent envelope for a flow packet.

    Centralized so every recipe's packet builder produces the same
    shape and so the test suite can assert on a single key structure.
    The hard rules from the spec are enforced INSIDE this factory:

      * `accepted_for_scope` status requires `accepted_scope` to be
        non-None — the factory raises ValueError otherwise.
      * No `common_knowledge` field is added. The factory simply
        does not accept that name; tests confirm the response shape
        carries no such key.

    Empty list defaults are [] not None — the FE / audit code reads
    absence as "not yet known", which differs from "no evidence
    required".
    """
    if status == "accepted_for_scope" and accepted_scope is None:
        raise ValueError(
            "epistemic_event(status='accepted_for_scope') requires "
            "an accepted_scope block; passing None breaks the contract"
        )
    return {
        "kind": kind,
        "status": status,
        "proposition": proposition,
        "source_actor_id": source_actor_id,
        "target_audience": list(target_audience or []),
        "visibility_scope": visibility_scope,
        "accepted_scope": accepted_scope,
        "evidence_refs": list(evidence_refs or []),
        "preconditions": list(preconditions or []),
        "authority_required": list(authority_required or []),
        "membrane_policy": membrane_policy,
        "update_effects": list(update_effects or []),
        "lineage_output": list(lineage_output or []),
        "supersedes": list(supersedes or []),
        "expires_at": expires_at,
    }


# ----------------------------------------------------------------------
# Shared helpers — used by every projector
# ----------------------------------------------------------------------


def _empty_evidence() -> dict[str, Any]:
    """KB review and handoff packets still emit empty shells in Slice
    D. Slice E will fill them when those recipes get their own
    evidence semantics. Route packets fill the shell directly in
    `route._route_packet_from_row`."""
    return {
        "citations": [],
        "source_messages": [],
        "artifacts": [],
        "agent_runs": [],
        "human_gates": [],
        "uncertainty": [],
    }


def _iso(value) -> str | None:
    if value is None:
        return None
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)
