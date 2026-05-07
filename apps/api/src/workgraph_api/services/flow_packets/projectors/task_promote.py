"""promote_task_to_plan — TaskRow(scope='personal') + IMSuggestion
(kind='membrane_review', proposal.detail.candidate_kind='task_promote').

F.1 — task circulation as a Flow Packet. The BE already accepts
promote requests at POST /api/tasks/{id}/promote → MembraneService
→ IMSuggestion(membrane_review) for the team-room owner inbox.
That row was invisible in Active Flows because the projection
only knew about kb / route / handoff candidates. Now it shows up
as a "promote_task_to_plan" packet, owner-gated like KB review.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from workgraph_persistence import IMSuggestionRow, TaskRow

from ..contracts import (
    _empty_evidence,
    _epistemic_event,
    _flow_ref,
    _iso,
    _transition_contract,
)


async def derive_task_promote_packets(
    session, project_id: str, owner_ids: list[str]
) -> list[dict[str, Any]]:
    # Pending suggestions for THIS project. Same query shape as
    # kb_review.derive — small volume, python-side filter
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
    # T3 — Transition Contract for personal-task promotion. The state
    # pair is `personal_task_draft` → `plan_task_candidate`. Once the
    # owner accepts the suggestion, the task flips scope='plan' and
    # the packet drops from projection (a separate "completed"
    # terminal would require widening the upstream query — skipped
    # this slice; the lineage lives on as a TaskRow row).
    contract_required_evidence = [
        _flow_ref("task", task.id, label=task.title or ""),
        _flow_ref(
            "membrane_suggestion",
            suggestion.id,
            label="task_promote review",
        ),
    ]
    if diff_summary:
        contract_required_evidence.append(
            _flow_ref("diff_summary", suggestion.id, label=diff_summary[:80])
        )
    # M3 conflict refs (when the agent flagged any) travel as
    # required_evidence too; they're already on the suggestion.
    detail = (proposal or {}).get("detail") if proposal else None
    if isinstance(detail, dict):
        for cw in (detail.get("conflict_with") or []):
            if isinstance(cw, str):
                contract_required_evidence.append(
                    _flow_ref("conflict_ref", cw, label="agent flagged")
                )

    transition_contract = _transition_contract(
        source_state="personal_task_draft",
        target_state="plan_task_candidate",
        # Combined: deterministic Membrane review on the suggestion
        # accept gate AND the M3 agent semantic review that ran
        # before the suggestion was created. Both are real today;
        # we name both so the audit can ask "which review?".
        review_method="membrane_review",
        mutation_service="TaskProgressService+MembraneService",
        status="awaiting_authority",
        required_evidence=contract_required_evidence,
        authority_user_ids=list(owner_ids),
        # Lineage is empty while the packet is alive — the canonical
        # `plan_task_canonical` lineage row is `TaskRow.scope='plan'`
        # which only exists post-accept. The packet drops from
        # projection at that point, so the projection-side
        # lineage_output stays empty. Audit consumers wanting the
        # post-accept lineage read TaskRow directly.
        lineage_output=[],
    )

    # E2 — task promote as task_transition. The packet is alive only
    # while the IMSuggestion is pending; once accepted, the task
    # flips scope='plan' and the packet drops from projection. So
    # the only status we see here is review_pending.
    epistemic_event = _epistemic_event(
        kind="task_transition",
        status="review_pending",
        proposition=title,
        source_actor_id=task.owner_user_id,
        target_audience=list(owner_ids),
        visibility_scope="project",
        accepted_scope=None,
        evidence_refs=contract_required_evidence,
        preconditions=[],
        authority_required=list(owner_ids),
        membrane_policy="request_review",
        update_effects=[
            "plan_task_candidate",
            "plan_task_canonical",
        ],
        lineage_output=[],
        supersedes=[],
        expires_at=None,
    )

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
        "transition_contract": transition_contract,
        "epistemic_event": epistemic_event,
        "timeline": timeline,
        "next_actions": next_actions,
        "created_at": _iso(suggestion.created_at),
        "updated_at": _iso(suggestion.resolved_at) or _iso(suggestion.created_at),
    }
