"use client";

import "reactflow/dist/style.css";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  type Edge,
  type Node,
  Position,
} from "reactflow";

import type { ProjectState } from "@/lib/api";

// Column layout — each column has its own y-stacker so nodes pack
// tightly from the top down. Previous implementation used a global
// ROW_STEP indexed by array position so sparse columns (e.g. 2 risks)
// ended high up, dense columns (13 deliverables) ran way down — looked
// broken.
const COL_X = {
  goal: 40,
  deliverable: 360,
  task: 740,
  risk: 1120,
};
// ROW_STEP was 72 — too tight once task/risk nodes grew to 2 lines
// (multi-line pushed them into 64px height, leaving 8px gap that
// visually piled). 110 gives 36–46px of breathing room on the tall
// rows and still keeps the graph compact.
const ROW_STEP = 110;
const ROW_START = 40;

const NODE_WIDTH = {
  goal: 240,
  deliverable: 280,
  task: 300,
  risk: 240,
};

const severityTint: Record<string, string> = {
  critical: "#fbd5cb",
  high: "#fbd5cb",
  medium: "#fce7c2",
  low: "#f4f0e6",
};

const severityBorder: Record<string, string> = {
  critical: "#c0471e",
  high: "#c0471e",
  medium: "#c68a00",
  low: "#9a9a95",
};

function trim(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function GraphCanvas({ state }: { state: ProjectState }) {
  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];

    state.graph.goals.forEach((g, i) => {
      nodes.push({
        id: `goal-${g.id}`,
        position: { x: COL_X.goal, y: ROW_START + i * ROW_STEP },
        data: { label: `🎯 ${trim(g.title, 52)}` },
        style: {
          background: "var(--wg-accent-soft, #fdf4ec)",
          border: "2px solid var(--wg-accent)",
          borderRadius: 6,
          fontSize: 13,
          fontWeight: 600,
          color: "var(--wg-ink)",
          padding: 10,
          width: NODE_WIDTH.goal,
        },
        sourcePosition: Position.Right,
      });
    });

    state.graph.deliverables.forEach((d, i) => {
      nodes.push({
        id: `del-${d.id}`,
        position: { x: COL_X.deliverable, y: ROW_START + i * ROW_STEP },
        data: { label: trim(d.title, 62) },
        style: {
          background: "#fff",
          border: "1px solid var(--wg-line)",
          borderRadius: 6,
          fontSize: 12,
          color: "var(--wg-ink)",
          padding: 10,
          width: NODE_WIDTH.deliverable,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
      // Attach every deliverable to the first goal. Multi-goal mapping
      // isn't in the data contract yet (goals don't list deliverables);
      // a single anchor line keeps the graph readable.
      if (state.graph.goals.length > 0) {
        edges.push({
          id: `e-goal-${d.id}`,
          source: `goal-${state.graph.goals[0].id}`,
          target: `del-${d.id}`,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#c0471e" },
        });
      }
    });

    state.plan.tasks.forEach((t, i) => {
      const label = t.assignee_role
        ? `${trim(t.title, 58)}\n· ${t.assignee_role}`
        : trim(t.title, 70);
      nodes.push({
        id: `task-${t.id}`,
        position: { x: COL_X.task, y: ROW_START + i * ROW_STEP },
        data: { label },
        style: {
          background: "var(--wg-surface-raised, #fafaf7)",
          border: "1px solid var(--wg-line)",
          borderRadius: 6,
          fontSize: 12,
          color: "var(--wg-ink)",
          padding: 10,
          width: NODE_WIDTH.task,
          whiteSpace: "pre-wrap",
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
      });
      if (t.deliverable_id) {
        edges.push({
          id: `e-del-task-${t.id}`,
          source: `del-${t.deliverable_id}`,
          target: `task-${t.id}`,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#c0471e" },
        });
      }
    });

    state.plan.dependencies.forEach((d) => {
      edges.push({
        id: `dep-${d.id}`,
        source: `task-${d.from_task_id}`,
        target: `task-${d.to_task_id}`,
        animated: true,
        style: {
          stroke: "var(--wg-ink-soft, #5a5a5a)",
          strokeWidth: 1.2,
          strokeDasharray: "4 3",
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#5a5a5a" },
      });
    });

    state.graph.risks.forEach((r, i) => {
      const sev = (r.severity || "low").toLowerCase();
      nodes.push({
        id: `risk-${r.id}`,
        position: { x: COL_X.risk, y: ROW_START + i * ROW_STEP },
        data: {
          label: `⚠ ${trim(r.title, 48)}\n· ${sev}`,
        },
        style: {
          background: severityTint[sev] ?? severityTint.low,
          border: `1px solid ${severityBorder[sev] ?? severityBorder.low}`,
          borderRadius: 6,
          fontSize: 12,
          color: "var(--wg-ink)",
          padding: 10,
          width: NODE_WIDTH.risk,
          whiteSpace: "pre-wrap",
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
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        nodesDraggable
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          style: { stroke: "var(--wg-accent)" },
        }}
      >
        <Background gap={16} size={1} color="#e6e3db" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>
      <Legend />
    </div>
  );
}

function Legend() {
  const items = [
    { label: "🎯 Goal", bg: "var(--wg-accent-soft, #fdf4ec)", border: "var(--wg-accent)" },
    { label: "Deliverable", bg: "#fff", border: "var(--wg-line)" },
    { label: "Task", bg: "var(--wg-surface-raised, #fafaf7)", border: "var(--wg-line)" },
    { label: "⚠ Risk", bg: severityTint.medium, border: severityBorder.medium },
  ];
  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        left: 12,
        padding: "8px 12px",
        background: "rgba(255,255,255,0.94)",
        border: "1px solid var(--wg-line)",
        borderRadius: 6,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-ink-soft)",
        display: "flex",
        gap: 10,
        alignItems: "center",
        zIndex: 4,
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      {items.map((i) => (
        <span
          key={i.label}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              display: "inline-block",
              background: i.bg,
              border: `1px solid ${i.border}`,
              borderRadius: 2,
            }}
            aria-hidden
          />
          {i.label}
        </span>
      ))}
    </div>
  );
}
