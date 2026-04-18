"use client";

import "reactflow/dist/style.css";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Edge,
  type Node,
  Position,
} from "reactflow";

import type { ProjectState } from "@/lib/api";

// Four-column layout: goal → deliverables → tasks → risks. Task nodes carry
// a `deliverable_id` edge back to their parent so the dependency graph
// reads left-to-right like the plan flow.
const COL_X = { goal: 40, deliverable: 320, task: 620, risk: 960 };
const ROW_Y = 80;
const ROW_STEP = 90;

export function GraphCanvas({ state }: { state: ProjectState }) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];

    state.graph.goals.forEach((g, i) => {
      nodes.push({
        id: `goal-${g.id}`,
        position: { x: COL_X.goal, y: ROW_Y + i * ROW_STEP },
        data: { label: `🎯 ${g.title}` },
        style: {
          background: "#fff",
          border: "2px solid var(--wg-accent)",
          borderRadius: 6,
          fontSize: 13,
          padding: 8,
          width: 220,
        },
        sourcePosition: Position.Right,
      });
    });

    state.graph.deliverables.forEach((d, i) => {
      nodes.push({
        id: `del-${d.id}`,
        position: { x: COL_X.deliverable, y: ROW_Y + i * ROW_STEP },
        data: { label: d.title },
        style: {
          background: "#fff",
          border: "1px solid var(--wg-line)",
          borderRadius: 6,
          fontSize: 13,
          padding: 8,
          width: 220,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
      // fanout from first goal (if any)
      if (state.graph.goals.length > 0) {
        edges.push({
          id: `e-goal-${d.id}`,
          source: `goal-${state.graph.goals[0].id}`,
          target: `del-${d.id}`,
          animated: true,
          style: { stroke: "var(--wg-accent)" },
        });
      }
    });

    state.plan.tasks.forEach((t, i) => {
      nodes.push({
        id: `task-${t.id}`,
        position: { x: COL_X.task, y: ROW_Y + i * ROW_STEP },
        data: {
          label: `${t.title}${t.assignee_role ? ` · ${t.assignee_role}` : ""}`,
        },
        style: {
          background: "var(--wg-surface)",
          border: "1px solid var(--wg-line)",
          borderRadius: 6,
          fontSize: 12,
          padding: 8,
          width: 240,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
      if (t.deliverable_id) {
        edges.push({
          id: `e-del-task-${t.id}`,
          source: `del-${t.deliverable_id}`,
          target: `task-${t.id}`,
          animated: true,
          style: { stroke: "var(--wg-accent)" },
        });
      }
    });

    state.plan.dependencies.forEach((d) => {
      edges.push({
        id: `dep-${d.id}`,
        source: `task-${d.from_task_id}`,
        target: `task-${d.to_task_id}`,
        animated: true,
        style: { stroke: "var(--wg-accent)", strokeDasharray: "4 3" },
      });
    });

    state.graph.risks.forEach((r, i) => {
      nodes.push({
        id: `risk-${r.id}`,
        position: { x: COL_X.risk, y: ROW_Y + i * ROW_STEP },
        data: { label: `⚠ ${r.title}` },
        style: {
          background: "#fdecec",
          border: "1px solid var(--wg-accent)",
          borderRadius: 6,
          fontSize: 12,
          padding: 8,
          width: 200,
        },
        targetPosition: Position.Left,
      });
    });

    return { nodes, edges };
  }, [state]);

  if (nodes.length === 0) {
    return (
      <div
        style={{
          height: "100%",
          display: "grid",
          placeItems: "center",
          color: "var(--wg-ink-soft)",
          fontSize: 14,
        }}
      >
        graph is empty — intake has not completed yet
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      fitView
      nodesDraggable
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={16} size={1} color="#e6e3db" />
      <Controls position="bottom-right" showInteractive={false} />
    </ReactFlow>
  );
}
