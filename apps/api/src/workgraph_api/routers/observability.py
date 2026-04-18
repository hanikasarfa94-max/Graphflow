"""Phase 12 — Observability aggregation endpoints.

Reads `agent_run_logs` and `events` to surface system health without
requiring a DB client. Read-only; no writes.

Routes:
  GET /api/observability/health         — rolling summary: per-agent
    counts, outcome breakdown, latency percentiles, token spend.
  GET /api/observability/agents         — recent runs per agent (limit N).
  GET /api/observability/trace/{id}     — every agent_run_log + event
    tagged with the given trace_id. Great for post-mortem.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser
from workgraph_persistence import (
    AgentRunLogRepository,
    AgentRunLogRow,
    EventRepository,
    session_scope,
)

router = APIRouter(prefix="/api/observability", tags=["observability"])


def _percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((p / 100) * (len(ordered) - 1)))))
    return int(ordered[idx])


def _summarize_agent(rows: list[AgentRunLogRow]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "outcomes": {},
            "latency_ms": {"p50": 0, "p95": 0, "max": 0},
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_read_tokens": 0,
            "last_seen": None,
        }
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r.outcome] = outcomes.get(r.outcome, 0) + 1
    latencies = [r.latency_ms or 0 for r in rows]
    return {
        "count": len(rows),
        "outcomes": outcomes,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "max": max(latencies),
        },
        "prompt_tokens": sum(r.prompt_tokens or 0 for r in rows),
        "completion_tokens": sum(r.completion_tokens or 0 for r in rows),
        "cache_read_tokens": sum(r.cache_read_tokens or 0 for r in rows),
        "last_seen": max(r.created_at for r in rows).isoformat(),
    }


def _row_payload(row: AgentRunLogRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent": row.agent,
        "prompt_version": row.prompt_version,
        "project_id": row.project_id,
        "trace_id": row.trace_id,
        "outcome": row.outcome,
        "attempts": row.attempts,
        "latency_ms": row.latency_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/health")
async def get_health(
    request: Request,
    window_minutes: int = Query(60, ge=1, le=60 * 24 * 7),
    _user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Rolling agent summary over the last `window_minutes`."""
    sessionmaker = request.app.state.sessionmaker
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=window_minutes)

    async with session_scope(sessionmaker) as session:
        rows = await AgentRunLogRepository(session).list_since(
            since=since, limit=5000
        )

    by_agent: dict[str, list[AgentRunLogRow]] = {}
    for r in rows:
        by_agent.setdefault(r.agent, []).append(r)

    agents = {name: _summarize_agent(rs) for name, rs in sorted(by_agent.items())}
    totals = _summarize_agent(rows)
    return {
        "window_minutes": window_minutes,
        "since": since.isoformat(),
        "now": now.isoformat(),
        "totals": totals,
        "agents": agents,
    }


@router.get("/agents")
async def list_agent_runs(
    request: Request,
    agent: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    _user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Recent agent runs. Filter by `agent` or omit for all agents mixed."""
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        rows = await AgentRunLogRepository(session).list_since(
            agent=agent, limit=limit
        )
    return {"agent": agent, "limit": limit, "runs": [_row_payload(r) for r in rows]}


@router.get("/trace/{trace_id}")
async def get_trace(
    trace_id: str,
    request: Request,
    _user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """All agent runs + events for a trace_id."""
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        runs = await AgentRunLogRepository(session).list_for_trace(trace_id)
        events = await EventRepository(session).list_for_trace(trace_id)
    return {
        "trace_id": trace_id,
        "runs": [_row_payload(r) for r in runs],
        "events": [
            {
                "id": e.id,
                "name": e.name,
                "project_id": e.project_id,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
