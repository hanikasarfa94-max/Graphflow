"""Rule-based conflict detectors — Phase 8.

Rules are pure functions over a GraphSnapshot dict. They never mutate state,
never call LLMs, and never persist anything. Output is a list of RuleMatch
records which the ConflictService persists + hands to the explanation agent.

A "fingerprint" identifies a conflict's identity across detection passes.
Fingerprints are deterministic: the same graph state yields the same
fingerprint, so re-running detection is idempotent. The ConflictRepository
uses this to upsert rather than insert — users don't see a new "open"
conflict every time they navigate to the tab.

Keep rules boring and explicit. The LLM does the nuance in the explanation
step; the rules just decide *whether* to involve it at all.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["low", "medium", "high", "critical"]
RuleName = Literal[
    "deadline_vs_scope",
    "dependency_blocking",
    "missing_owner",
    "blocked_downstream",
]


@dataclass(slots=True)
class RuleMatch:
    rule: RuleName
    severity: Severity
    fingerprint: str
    # Entity ids referenced by the match — tasks, deliverables, risks,
    # milestones, constraints. The explanation agent uses these to pull
    # titles/roles for the summary.
    targets: list[str]
    # Raw rule-level detail (counts, thresholds) for debugging + prompt input.
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphSnapshot:
    """Everything the rules need to run. Built by ConflictService from the ORM.

    Task/dep/milestone/risk/constraint entries are plain dicts so rules don't
    import SQLAlchemy. `assignments` maps task_id → list[user_id] (active only).
    """

    project_id: str
    requirement_id: str
    goals: list[dict]
    deliverables: list[dict]
    constraints: list[dict]
    risks: list[dict]
    tasks: list[dict]
    dependencies: list[dict]  # {"from_task_id", "to_task_id"}
    milestones: list[dict]
    assignments: dict[str, list[str]]


# --- thresholds ----------------------------------------------------------
# Tuned to the demo data shape: a typical Phase-6 plan has 8–20 tasks at
# 4–16 hours each. "Overflow" when total estimates approach a single-sprint
# budget, or when a quarter of tasks are missing estimates entirely.

_SPRINT_HOURS = 160  # 1 dev × 1 month
_OVERFLOW_HOURS = 240  # ~1.5 sprints — flag as medium
_CRITICAL_OVERFLOW_HOURS = 360
_MISSING_ESTIMATE_RATIO = 0.25

# A blocker risk is any risk.severity ∈ {high, critical} and status == "open".
_BLOCKER_SEVERITIES = {"high", "critical"}


# --- fingerprint helpers -------------------------------------------------


def _fingerprint(rule: str, *parts: str) -> str:
    """Stable sha256 of rule + sorted parts. 16 hex chars is plenty."""
    body = f"{rule}|" + "|".join(sorted(p for p in parts if p))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# --- rule: deadline_vs_scope --------------------------------------------


def _detect_deadline_vs_scope(snap: GraphSnapshot) -> list[RuleMatch]:
    deadline_constraints = [
        c for c in snap.constraints if c.get("kind") == "deadline"
    ]
    if not deadline_constraints:
        return []

    total_hours = 0
    sized_tasks = 0
    unsized_tasks: list[str] = []
    for t in snap.tasks:
        if t.get("status") == "done":
            continue
        est = t.get("estimate_hours")
        if est is None:
            unsized_tasks.append(t["id"])
        else:
            total_hours += int(est)
            sized_tasks += 1

    open_task_count = sized_tasks + len(unsized_tasks)
    missing_ratio = (
        len(unsized_tasks) / open_task_count if open_task_count else 0.0
    )

    matches: list[RuleMatch] = []
    if total_hours >= _OVERFLOW_HOURS:
        severity: Severity = (
            "critical" if total_hours >= _CRITICAL_OVERFLOW_HOURS else "high"
        )
        matches.append(
            RuleMatch(
                rule="deadline_vs_scope",
                severity=severity,
                fingerprint=_fingerprint(
                    "deadline_vs_scope",
                    "overflow",
                    snap.requirement_id,
                ),
                targets=[c["id"] for c in deadline_constraints]
                + [m["id"] for m in snap.milestones],
                detail={
                    "total_hours": total_hours,
                    "threshold_hours": _OVERFLOW_HOURS,
                    "sprint_hours": _SPRINT_HOURS,
                    "deadline_contents": [
                        c.get("content", "") for c in deadline_constraints
                    ],
                    "unsized_task_count": len(unsized_tasks),
                },
            )
        )

    if open_task_count and missing_ratio >= _MISSING_ESTIMATE_RATIO:
        matches.append(
            RuleMatch(
                rule="deadline_vs_scope",
                severity="medium",
                fingerprint=_fingerprint(
                    "deadline_vs_scope",
                    "unsized",
                    snap.requirement_id,
                ),
                targets=unsized_tasks,
                detail={
                    "unsized_task_count": len(unsized_tasks),
                    "total_open_tasks": open_task_count,
                    "missing_ratio": round(missing_ratio, 2),
                    "deadline_contents": [
                        c.get("content", "") for c in deadline_constraints
                    ],
                },
            )
        )
    return matches


# --- rule: dependency_blocking ------------------------------------------


def _detect_dependency_blocking(snap: GraphSnapshot) -> list[RuleMatch]:
    """Task waits on an upstream that's anchored by an open high-sev risk.

    Without an explicit task.status == "blocked" transition in the current
    schema, we proxy "blocked upstream" with: there's an open blocker-class
    risk, and some upstream task is on the same deliverable as that risk
    OR explicitly mentions the task's deliverable. Downstream consumers of
    that upstream task get flagged.
    """
    blockers = [
        r for r in snap.risks
        if r.get("severity") in _BLOCKER_SEVERITIES
        and r.get("status", "open") == "open"
    ]
    if not blockers or not snap.dependencies:
        return []

    # Build deliverable → {task_ids} index.
    by_deliverable: dict[str, list[str]] = {}
    for t in snap.tasks:
        d_id = t.get("deliverable_id")
        if d_id:
            by_deliverable.setdefault(d_id, []).append(t["id"])

    # Upstream-by-id for dependency walk.
    downstream_of: dict[str, list[str]] = {}
    for d in snap.dependencies:
        downstream_of.setdefault(d["from_task_id"], []).append(d["to_task_id"])

    matches: list[RuleMatch] = []
    seen_fingerprints: set[str] = set()
    for risk in blockers:
        # Any task whose title or deliverable appears in risk.content is a
        # candidate "blocked upstream". For demo-scale data we keep the
        # match local: the risk belongs to a requirement + anchors onto a
        # deliverable if its content mentions the title. Fall back to "all
        # tasks with downstream deps".
        content = (risk.get("content") or "").lower()
        title = (risk.get("title") or "").lower()
        risk_text = f"{title} {content}".strip()

        for upstream_id, downstream in downstream_of.items():
            upstream = next(
                (t for t in snap.tasks if t["id"] == upstream_id), None
            )
            if upstream is None:
                continue
            upstream_title = (upstream.get("title") or "").lower()
            deliverable_id = upstream.get("deliverable_id")
            deliverable_title = ""
            if deliverable_id:
                d_match = next(
                    (d for d in snap.deliverables if d["id"] == deliverable_id),
                    None,
                )
                deliverable_title = (
                    (d_match or {}).get("title", "").lower()
                )
            anchors_on_upstream = (
                upstream_title
                and upstream_title in risk_text
            ) or (
                deliverable_title
                and deliverable_title in risk_text
            )
            if not anchors_on_upstream:
                continue

            chain_len = len(downstream)
            severity: Severity = (
                "high" if chain_len >= 2 else "medium"
            )
            fp = _fingerprint(
                "dependency_blocking",
                risk["id"],
                upstream_id,
            )
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            matches.append(
                RuleMatch(
                    rule="dependency_blocking",
                    severity=severity,
                    fingerprint=fp,
                    targets=[risk["id"], upstream_id, *downstream],
                    detail={
                        "risk_id": risk["id"],
                        "risk_title": risk.get("title"),
                        "risk_severity": risk.get("severity"),
                        "upstream_task_id": upstream_id,
                        "upstream_task_title": upstream.get("title"),
                        "downstream_task_ids": downstream,
                        "chain_length": chain_len,
                    },
                )
            )
    return matches


# --- rule: missing_owner -------------------------------------------------


def _detect_missing_owner(snap: GraphSnapshot) -> list[RuleMatch]:
    """Task with a specific assignee_role but no active human assignment.

    "unknown" role is tolerated (Phase 6 planning may leave this open for the
    intake author to decide). A specific role (frontend/backend/qa/...) with
    no active AssignmentRow is the classic "who's doing this?" case.
    """
    downstream_of: dict[str, list[str]] = {}
    for d in snap.dependencies:
        downstream_of.setdefault(d["from_task_id"], []).append(d["to_task_id"])

    matches: list[RuleMatch] = []
    for t in snap.tasks:
        if t.get("status") == "done":
            continue
        role = t.get("assignee_role") or "unknown"
        if role == "unknown":
            continue
        if snap.assignments.get(t["id"]):
            continue
        has_downstream = bool(downstream_of.get(t["id"]))
        severity: Severity = "high" if has_downstream else "medium"
        matches.append(
            RuleMatch(
                rule="missing_owner",
                severity=severity,
                fingerprint=_fingerprint(
                    "missing_owner",
                    t["id"],
                ),
                targets=[t["id"]],
                detail={
                    "task_id": t["id"],
                    "task_title": t.get("title"),
                    "assignee_role": role,
                    "has_downstream": has_downstream,
                    "downstream_count": len(downstream_of.get(t["id"], [])),
                },
            )
        )
    return matches


# --- rule: blocked_downstream -------------------------------------------


def _detect_blocked_downstream(snap: GraphSnapshot) -> list[RuleMatch]:
    """A single node with many transitive descendants — small hiccup = big delay.

    Walks the dep DAG, counts descendants per task. Any task with >= 3
    descendants whose status is not "done" earns a match. This overlaps
    partially with dependency_blocking (that one also cares about risks),
    but this rule catches *structural* fragility even without a risk yet —
    the PM should know they have a bottleneck task regardless.
    """
    if not snap.dependencies:
        return []

    # Adjacency: from → set(to)
    adj: dict[str, set[str]] = {}
    for d in snap.dependencies:
        adj.setdefault(d["from_task_id"], set()).add(d["to_task_id"])

    def descendants(start: str) -> set[str]:
        seen: set[str] = set()
        stack = list(adj.get(start, set()))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, set()))
        return seen

    tasks_by_id = {t["id"]: t for t in snap.tasks}

    matches: list[RuleMatch] = []
    for task_id in adj:
        task = tasks_by_id.get(task_id)
        if task is None or task.get("status") == "done":
            continue
        descs = descendants(task_id)
        # Drop completed descendants from the impact count.
        live_descs = [
            d for d in descs if tasks_by_id.get(d, {}).get("status") != "done"
        ]
        if len(live_descs) < 3:
            continue
        if len(live_descs) >= 5:
            severity: Severity = "critical"
        else:
            severity = "high"
        matches.append(
            RuleMatch(
                rule="blocked_downstream",
                severity=severity,
                fingerprint=_fingerprint(
                    "blocked_downstream",
                    task_id,
                    str(len(live_descs) >= 5),
                ),
                targets=[task_id, *sorted(live_descs)],
                detail={
                    "task_id": task_id,
                    "task_title": task.get("title"),
                    "descendant_count": len(live_descs),
                    "descendant_task_ids": sorted(live_descs),
                },
            )
        )
    return matches


# --- public entrypoint ---------------------------------------------------


def detect_all(snapshot: GraphSnapshot) -> list[RuleMatch]:
    """Run every rule against the snapshot, return concatenated matches.

    Order matters for the UI: stronger rules first (structural > scope >
    ownership) so when we render severity-tied conflicts the user's eye
    lands on the highest-impact one.
    """
    matches: list[RuleMatch] = []
    matches.extend(_detect_deadline_vs_scope(snapshot))
    matches.extend(_detect_blocked_downstream(snapshot))
    matches.extend(_detect_dependency_blocking(snapshot))
    matches.extend(_detect_missing_owner(snapshot))
    return matches
