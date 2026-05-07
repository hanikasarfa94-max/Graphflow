"""LLM review-packet builders shared between live policies and the
M2 audit (kb_policy.audit_canonical_kb).

Each builder follows `docs/membrane-agent-review-spec.md §5`:

  * §5.2  build_kb_review_packet      — kb_item_group candidate
  * §5.3  build_task_review_packet    — task_promote candidate
  * §5.4  build_decision_review_packet — decision_crystallize candidate

A "packet" is the dict the agent prompt schema expects: candidate
field, policy field, retrieved_context, recent_decisions, etc. Builders
are the only place that opens a session for the pretext queries; they
return a plain dict so callers can then run their own §7 emptiness gate
(skip the LLM round-trip when nothing to review against).

These are pure read-side. They never write to the DB or emit events.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import (
    DecisionRepository,
    KbItemRepository,
    KbItemRow,
    session_scope,
)

from .._kb_visibility import is_canonical_kb_row
from .base import MembraneCandidate, MembraneContext
from .deterministic import _iso_or_none, _topic_tokens


async def build_kb_review_packet(
    *,
    candidate: MembraneCandidate,
    existing: list[KbItemRow],
    context: MembraneContext,
) -> dict[str, Any]:
    """Build the KB review packet per spec §5.2. Picks top-K
    published group KB items by simple title/content token overlap
    with the candidate (no LLM ranking; Slice M2 may upgrade to
    retrieval-service candidate_set if it proves needed).
    """
    candidate_text = f"{candidate.title or ''}\n{candidate.content or ''}"
    candidate_tokens = _topic_tokens(candidate_text)

    scored: list[tuple[int, KbItemRow]] = []
    for row in existing:
        # M1.1 — pretext only sees canonical shared memory. Pre-
        # M1.1 this checked `row.status != "published"`, which
        # excluded approved/routed ingest rows that ARE part of
        # canonical shared context. Now driven by the same
        # whitelist as RetrievalService / SkillsService so
        # "what the agent reviews against" matches "what the agent
        # would later see in retrieval."
        if not is_canonical_kb_row(row):
            continue
        row_tokens = _topic_tokens(
            f"{row.title or ''}\n{row.content_md or ''}"
        )
        score = len(candidate_tokens & row_tokens)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    top_kb = [row for _, row in scored[:8]]

    retrieved_context = [
        {
            "ref": f"kb:{row.id}",
            "title": row.title or "",
            "excerpt": (row.content_md or "")[:240],
            "status": row.status,
            "scope": row.scope,
            "source": row.source,
            "updated_at": _iso_or_none(row.created_at),
            "folder_id": row.folder_id,
        }
        for row in top_kb
    ]

    recent_decisions: list[dict[str, Any]] = []
    async with session_scope(context.sessionmaker) as session:
        decisions = await DecisionRepository(session).list_for_project(
            candidate.project_id, limit=20
        )
    # Filter to decisions whose headline / rationale shares any
    # token with the candidate. Cap at 5 per spec §5.2.
    for d in decisions:
        d_text = f"{d.custom_text or ''}\n{d.rationale or ''}"
        if not _topic_tokens(d_text) & candidate_tokens:
            continue
        recent_decisions.append(
            {
                "ref": f"decision:{d.id}",
                "headline": (d.custom_text or "")[:200],
                "rationale": (d.rationale or "")[:600],
                "apply_outcome": d.apply_outcome,
                "created_at": _iso_or_none(d.created_at),
                "scope_stream_id": d.scope_stream_id,
            }
        )
        if len(recent_decisions) >= 5:
            break

    return {
        "candidate": {
            "kind": "kb_item_group",
            "project_id": candidate.project_id,
            "proposer_user_id": candidate.proposer_user_id,
            "title": candidate.title,
            "content": candidate.content,
            "metadata": dict(candidate.metadata or {}),
        },
        "policy_context": {
            "allowed_actions": [
                "auto_merge",
                "request_review",
                "request_clarification",
                "reject",
            ],
            "write_target": "group_kb",
            "shared_context_impact": (
                "will_be_visible_to_project_agents_if_published"
            ),
        },
        "retrieved_context": retrieved_context,
        "recent_decisions": recent_decisions,
        "warnings_from_fixed_checks": [],
    }


async def build_task_review_packet(
    *,
    candidate: MembraneCandidate,
    existing: list[Any],
    requirement: Any,
    deterministic_warnings: list[str],
    context: MembraneContext,
) -> dict[str, Any]:
    """Build the task review packet per spec §5.3.

    Inputs:
      - candidate title / description / estimate / role
      - active plan tasks topically similar to the candidate
      - done / cancelled tasks topically similar (so the agent can
        reason about reopen-intent)
      - latest requirement context
      - recent decisions topically similar (so the agent can flag
        contradictions / supersession)
    """
    candidate_text = f"{candidate.title or ''}\n{candidate.content or ''}"
    candidate_tokens = _topic_tokens(candidate_text)

    # Topic-overlap-rank existing plan tasks. Cap at 8 like KB.
    scored: list[tuple[int, Any]] = []
    for row in existing:
        row_text = f"{row.title or ''}\n{row.description or ''}"
        row_tokens = _topic_tokens(row_text)
        score = len(candidate_tokens & row_tokens)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    top_tasks = [row for _, row in scored[:8]]

    related_tasks = [
        {
            "ref": f"task:{row.id}",
            "title": row.title or "",
            "description": (row.description or "")[:240],
            "status": row.status,
            "scope": row.scope,
            "assignee_role": row.assignee_role,
            "estimate_hours": row.estimate_hours,
        }
        for row in top_tasks
    ]

    recent_decisions: list[dict[str, Any]] = []
    async with session_scope(context.sessionmaker) as session:
        decisions = await DecisionRepository(session).list_for_project(
            candidate.project_id, limit=20
        )
    for d in decisions:
        d_text = f"{d.custom_text or ''}\n{d.rationale or ''}"
        if not _topic_tokens(d_text) & candidate_tokens:
            continue
        recent_decisions.append(
            {
                "ref": f"decision:{d.id}",
                "headline": (d.custom_text or "")[:200],
                "rationale": (d.rationale or "")[:600],
                "apply_outcome": d.apply_outcome,
                "created_at": _iso_or_none(d.created_at),
                "scope_stream_id": d.scope_stream_id,
            }
        )
        if len(recent_decisions) >= 5:
            break

    # Plan context — budget + current estimate total so the agent
    # can reason about scope creep contextually (the deterministic
    # check already raised a warning; the agent may still want to
    # block if the new task ALSO contradicts a decision, etc.).
    current_estimate_total = sum(
        (t.estimate_hours or 0)
        for t in existing
        if t.status not in ("cancelled",)
    )

    proposed_estimate = candidate.metadata.get("estimate_hours")
    proposed_role = candidate.metadata.get("assignee_role")

    return {
        "candidate": {
            "kind": "task_promote",
            "project_id": candidate.project_id,
            "proposer_user_id": candidate.proposer_user_id,
            "title": candidate.title,
            "description": candidate.content,
            "estimate_hours": proposed_estimate,
            "assignee_role": proposed_role,
            "metadata": dict(candidate.metadata or {}),
        },
        "plan_context": {
            "requirement_id": requirement.id,
            # `text` was the spec's name; the actual column is
            # `raw_text` (RequirementRow). Be defensive about both
            # so a future column rename doesn't take this packet
            # builder down with it.
            "requirement_title": (
                getattr(requirement, "raw_text", None)
                or getattr(requirement, "text", None)
                or ""
            )[:200],
            "budget_hours": getattr(requirement, "budget_hours", None),
            "current_estimate_total": current_estimate_total,
        },
        "policy": {
            "allowed_actions": [
                "auto_merge",
                "request_review",
                "request_clarification",
                "reject",
            ],
            "write_target": "plan_task",
            "shared_context_impact": (
                "will_be_visible_to_project_agents_if_promoted"
            ),
        },
        "related_tasks": related_tasks,
        "recent_decisions": recent_decisions,
        "warnings_from_fixed_checks": list(deterministic_warnings),
    }


async def build_decision_review_packet(
    *,
    candidate: MembraneCandidate,
    deterministic_warnings: list[str],
    context: MembraneContext,
) -> dict[str, Any]:
    """Build the decision review packet per spec §5.4.

    Inputs:
      - candidate title / rationale / source
      - prior decisions filtered by topic-token overlap
      - related KB items by topic
      - tasks/risks touched by proposed apply actions (deferred
        to M4+1 — needs richer apply_actions parsing)
    """
    rationale = ""
    if isinstance(candidate.metadata, dict):
        rationale = (candidate.metadata.get("rationale") or "").strip()
    candidate_text = (
        f"{candidate.title or ''}\n{candidate.content or ''}\n{rationale}"
    )
    candidate_tokens = _topic_tokens(candidate_text)

    prior_decisions: list[dict[str, Any]] = []
    related_kb: list[dict[str, Any]] = []
    async with session_scope(context.sessionmaker) as session:
        decisions = await DecisionRepository(session).list_for_project(
            candidate.project_id, limit=40
        )
        kb_rows = await KbItemRepository(session).list_group_for_project(
            project_id=candidate.project_id, limit=200
        )

    for d in decisions:
        d_text = f"{d.custom_text or ''}\n{d.rationale or ''}"
        if not _topic_tokens(d_text) & candidate_tokens:
            continue
        prior_decisions.append(
            {
                "ref": f"decision:{d.id}",
                "headline": (d.custom_text or "")[:200],
                "rationale": (d.rationale or "")[:600],
                "apply_outcome": d.apply_outcome,
                "created_at": _iso_or_none(d.created_at),
                "scope_stream_id": d.scope_stream_id,
            }
        )
        if len(prior_decisions) >= 8:
            break

    kb_scored: list[tuple[int, Any]] = []
    for row in kb_rows:
        if not is_canonical_kb_row(row):
            continue
        row_tokens = _topic_tokens(
            f"{row.title or ''}\n{row.content_md or ''}"
        )
        score = len(candidate_tokens & row_tokens)
        if score > 0:
            kb_scored.append((score, row))
    kb_scored.sort(key=lambda t: t[0], reverse=True)
    for _, row in kb_scored[:6]:
        related_kb.append(
            {
                "ref": f"kb:{row.id}",
                "title": row.title or "",
                "excerpt": (row.content_md or "")[:240],
                "status": row.status,
                "scope": row.scope,
            }
        )

    source = None
    supersedes = None
    if isinstance(candidate.metadata, dict):
        source = candidate.metadata.get("source")
        supersedes = (
            candidate.metadata.get("supersedes")
            or candidate.metadata.get("supersedes_decision_id")
        )

    return {
        "candidate": {
            "kind": "decision_crystallize",
            "project_id": candidate.project_id,
            "proposer_user_id": candidate.proposer_user_id,
            "title": candidate.title,
            "rationale": rationale,
            "source": source,
            "supersedes": supersedes,
            "metadata": dict(candidate.metadata or {}),
        },
        "policy": {
            "allowed_actions": [
                "auto_merge",
                "request_review",
                "request_clarification",
                "reject",
            ],
            "write_target": "decision",
            "shared_context_impact": (
                "will_be_visible_to_project_agents_once_crystallized"
            ),
        },
        # `prior_decisions` is the M4 section name (mirrors spec
        # §5.4); keep it distinct from `recent_decisions` used by
        # KB / task packets so the agent prompt can disambiguate.
        "prior_decisions": prior_decisions,
        "related_kb": related_kb,
        "warnings_from_fixed_checks": list(deterministic_warnings),
    }


__all__ = [
    "build_decision_review_packet",
    "build_kb_review_packet",
    "build_task_review_packet",
]
