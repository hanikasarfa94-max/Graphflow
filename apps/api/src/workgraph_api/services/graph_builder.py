from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import ParsedRequirement
from workgraph_domain import EventBus
from workgraph_persistence import (
    ProjectGraphRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.graph_builder")


class GraphBuilderService:
    """Phase 5 — deterministic projection from ParsedRequirement to graph entities.

    We do NOT call another LLM here. The mapping is pure:
      goal                → 1 GoalRow
      scope_items[i]      → 1 DeliverableRow (kind="feature")
      deadline (if set)   → 1 ConstraintRow (kind="deadline", severity="high")
      risks               → [] (left for later phases that have signal)

    Rationale (decision 1E + prompt-contracts §6.3):
      - The graph IS the stage. Building it is a data transformation, not a
        creative act. A deterministic mapping keeps the Phase 5 eval surface
        small and keeps costs sane.
      - Later phases (planning, QA) can enrich the graph — e.g. planning adds
        Risk rows from dependency analysis — without rebuilding from scratch.

    Idempotency (matches /clarify): if entities already exist for this
    requirement version, the repository returns them unchanged. A v+1
    promotion builds v+1's own entities alongside v1's — old graph stays
    as history.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    async def build_for_requirement(
        self,
        *,
        project_id: str,
        requirement_id: str,
        requirement_version: int,
        parsed: ParsedRequirement | None,
        parse_outcome: str,
        source: str = "intake",
    ) -> dict[str, Any]:
        """Project parsed requirement onto graph rows and emit graph.built.

        No-op if parse_outcome == "manual_review" or parsed is None — the
        graph needs a trustworthy parse to project from. In that case we
        still emit graph.built with outcome=skipped so observers can count
        attempts.
        """
        if parse_outcome == "manual_review" or parsed is None:
            await self._event_bus.emit(
                "graph.built",
                {
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "requirement_version": requirement_version,
                    "outcome": "skipped",
                    "reason": "no-parse",
                    "source": source,
                    "goal_count": 0,
                    "deliverable_count": 0,
                    "constraint_count": 0,
                    "risk_count": 0,
                },
            )
            return {
                "outcome": "skipped",
                "goals": [],
                "deliverables": [],
                "constraints": [],
                "risks": [],
            }

        goals, deliverables, constraints, risks = _project_parsed(parsed)

        async with session_scope(self._sessionmaker) as session:
            repo = ProjectGraphRepository(session)
            created = await repo.append_for_requirement(
                project_id=project_id,
                requirement_id=requirement_id,
                goals=goals,
                deliverables=deliverables,
                constraints=constraints,
                risks=risks,
            )
            snapshot = {
                "goals": [
                    {
                        "id": g.id,
                        "title": g.title,
                        "description": g.description,
                        "success_criteria": g.success_criteria,
                        "status": g.status,
                        "sort_order": g.sort_order,
                    }
                    for g in created["goals"]
                ],
                "deliverables": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "kind": d.kind,
                        "status": d.status,
                        "sort_order": d.sort_order,
                    }
                    for d in created["deliverables"]
                ],
                "constraints": [
                    {
                        "id": c.id,
                        "kind": c.kind,
                        "content": c.content,
                        "severity": c.severity,
                        "status": c.status,
                        "sort_order": c.sort_order,
                    }
                    for c in created["constraints"]
                ],
                "risks": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                        "status": r.status,
                        "sort_order": r.sort_order,
                    }
                    for r in created["risks"]
                ],
            }

        await self._event_bus.emit(
            "graph.built",
            {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "requirement_version": requirement_version,
                "outcome": "ok",
                "source": source,
                "goal_count": len(snapshot["goals"]),
                "deliverable_count": len(snapshot["deliverables"]),
                "constraint_count": len(snapshot["constraints"]),
                "risk_count": len(snapshot["risks"]),
            },
        )

        return {"outcome": "ok", **snapshot}


def _project_parsed(
    parsed: ParsedRequirement,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    goals = [{"title": parsed.goal, "description": "", "success_criteria": None}]
    deliverables = [{"title": item, "kind": "feature"} for item in parsed.scope_items]
    constraints: list[dict] = []
    if parsed.deadline:
        constraints.append(
            {
                "kind": "deadline",
                "content": f"Deadline: {parsed.deadline}",
                "severity": "high",
            }
        )
    risks: list[dict] = []
    return goals, deliverables, constraints, risks
