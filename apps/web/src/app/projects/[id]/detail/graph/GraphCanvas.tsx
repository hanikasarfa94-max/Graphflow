"use client";

import "reactflow/dist/style.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  useNodesState,
  useEdgesState,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";

import { api, type ProjectState } from "@/lib/api";

// Graph v2 Wave 1 — live, differentiated, searchable.
//
// Wired to the /ws/projects/{id} channel: any frame of a graph-relevant
// type (graph, decision, delivery, conflict) triggers a debounced refetch
// of /api/projects/{id}/state. After refetch we diff node identities
// against the previous snapshot and pulse anything that mutated (status,
// title, severity) so the viewer can see *what* changed without reading
// the whole graph.
//
// Node positions are cached per-project in localStorage under
// `graph-pos:{id}`. On drag end we write; on mount we hydrate. Nodes
// without a cached position fall back to the deterministic column layout
// so first-view spatial memory is stable across sessions.
//
// Wave 2 adds decision nodes (needs backend state extension), dagre
// layout, and the intent strip.

type NodeKind = "goal" | "deliverable" | "decision" | "task" | "risk";

// Intent strip modes — "which slice of the graph do I care about right
// now?" Active mode dims non-members without hiding them, so the viewer
// keeps spatial context.
type IntentMode = "all" | "flow" | "decisions" | "risks";

// Wave 2 adds a decision lane between deliverables and tasks. Each column
// ends 60px before the next one starts so cards breathe at fitView zoom.
//   goal:       40  → 300
//   deliverable 360 → 620
//   decision    680 → 880
//   task        940 → 1220
//   risk        1280 → 1520
const COL_X: Record<NodeKind, number> = {
  goal: 40,
  deliverable: 360,
  decision: 680,
  task: 940,
  risk: 1280,
};
const ROW_STEP = 110;
const ROW_START = 40;

const NODE_WIDTH: Record<NodeKind, number> = {
  goal: 260,
  deliverable: 260,
  decision: 200,
  task: 280,
  risk: 240,
};

// Severity palette — reused for risks.
const SEVERITY_TINT: Record<string, string> = {
  critical: "#fbd5cb",
  high: "#fbd5cb",
  medium: "#fce7c2",
  low: "#f4f0e6",
};
const SEVERITY_BORDER: Record<string, string> = {
  critical: "#c0471e",
  high: "#c0471e",
  medium: "#c68a00",
  low: "#9a9a95",
};

// Left-side bar color per kind. Bar is the primary differentiator at
// a glance — eye reads the stripe before reading the label.
const KIND_BAR: Record<NodeKind, string> = {
  goal: "var(--wg-accent)",
  deliverable: "#4d7a4a",
  decision: "var(--wg-accent)",
  task: "var(--wg-ink-faint)",
  risk: "var(--wg-accent)",
};
const KIND_ICON: Record<NodeKind, string> = {
  goal: "◆",
  deliverable: "▦",
  decision: "⚡",
  task: "▸",
  risk: "▲",
};

const PULSE_MS = 8_000; // node pulses for this long after a change

function trim(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// A change "signature" collapses all the fields we care about into one
// string. If it differs between two snapshots, the node has meaningfully
// mutated and should pulse.
function signature(
  kind: NodeKind,
  entity: Record<string, unknown>,
): string {
  const keys = [
    "title",
    "status",
    "severity",
    "assignee_role",
    "deliverable_id",
    "rationale",
    "custom_text",
    "apply_outcome",
  ];
  const parts: string[] = [kind];
  for (const k of keys) {
    const v = entity[k];
    if (v !== undefined) parts.push(`${k}=${String(v ?? "")}`);
  }
  return parts.join("|");
}

// Pull a short, legible headline from a raw Decision. Prefer custom_text
// (the resolver's own phrasing) over the LLM rationale, which is often a
// full paragraph.
function decisionHeadline(d: {
  custom_text: string | null;
  rationale: string;
}): string {
  const raw = (d.custom_text ?? d.rationale ?? "").trim();
  if (!raw) return "(unlabelled decision)";
  // First sentence, capped.
  const first = raw.split(/[.。!?!?\n]/)[0] ?? raw;
  return first.length > 80 ? first.slice(0, 79) + "…" : first;
}

// ---- Custom node ---------------------------------------------------------

interface NodeData {
  kind: NodeKind;
  title: string;
  subtitle?: string;
  severity?: string;
  dimmed: boolean;
  // Absolute epoch ms at which the pulse animation should stop. 0 = never
  // pulsed. Kept as a scalar (not a boolean) so useMemo doesn't have to
  // re-run every second — WgNode evaluates its own visibility timer.
  pulseExpiresAt: number;
}

function WgNode({ data, selected }: NodeProps<NodeData>) {
  const [pulsing, setPulsing] = useState(
    () => data.pulseExpiresAt > Date.now(),
  );
  useEffect(() => {
    const remaining = data.pulseExpiresAt - Date.now();
    if (remaining <= 0) {
      setPulsing(false);
      return;
    }
    setPulsing(true);
    const id = setTimeout(() => setPulsing(false), remaining);
    return () => clearTimeout(id);
  }, [data.pulseExpiresAt]);
  const bg =
    data.kind === "risk" && data.severity
      ? SEVERITY_TINT[data.severity.toLowerCase()] ?? SEVERITY_TINT.low
      : data.kind === "goal"
        ? "var(--wg-accent-soft)"
        : data.kind === "deliverable"
          ? "var(--wg-surface-raised)"
          : "var(--wg-surface-raised)";
  const barColor =
    data.kind === "risk" && data.severity
      ? SEVERITY_BORDER[data.severity.toLowerCase()] ?? SEVERITY_BORDER.low
      : KIND_BAR[data.kind];

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        padding: "9px 12px 9px 16px",
        background: bg,
        border: `1px solid ${selected ? "var(--wg-accent)" : "var(--wg-line)"}`,
        borderRadius: 6,
        width: NODE_WIDTH[data.kind],
        opacity: data.dimmed ? 0.22 : 1,
        transition:
          "opacity 200ms ease-out, border-color 140ms ease-out, box-shadow 200ms ease-out",
        boxShadow: pulsing
          ? "0 0 0 3px var(--wg-accent-ring), 0 0 16px rgba(192, 71, 30, 0.28)"
          : selected
            ? "0 0 0 2px var(--wg-accent-ring)"
            : undefined,
        animation: pulsing ? "wg-pulse 1.6s ease-out infinite" : undefined,
      }}
    >
      <div
        aria-hidden
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          background: barColor,
          borderRadius: "6px 0 0 6px",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 6,
          right: 10,
          fontSize: 9,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          pointerEvents: "none",
        }}
      >
        {data.kind}
      </div>
      <div
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: "var(--wg-ink)",
          paddingRight: 60,
          lineHeight: 1.35,
        }}
      >
        <span
          aria-hidden
          style={{
            color: barColor,
            marginRight: 6,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {KIND_ICON[data.kind]}
        </span>
        {data.title}
      </div>
      {data.subtitle ? (
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            marginTop: 3,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {data.subtitle}
        </div>
      ) : null}
      <Handle
        type="target"
        position={Position.Left}
        isConnectable={false}
        style={{
          left: -3,
          width: 6,
          height: 6,
          minWidth: 0,
          minHeight: 0,
          background: barColor,
          border: 0,
          borderRadius: "50%",
          opacity: 0.9,
          pointerEvents: "none",
        }}
      />
      <Handle
        type="source"
        position={Position.Right}
        isConnectable={false}
        style={{
          right: -3,
          width: 6,
          height: 6,
          minWidth: 0,
          minHeight: 0,
          background: barColor,
          border: 0,
          borderRadius: "50%",
          opacity: 0.9,
          pointerEvents: "none",
        }}
      />
    </div>
  );
}

// Module-scope: defined ONCE. React Flow warns loudly if this identity
// changes between renders — even though module-scope objects are stable,
// the warning can misfire during dev HMR, so we also freeze it below.
const NODE_TYPES = Object.freeze({ wg: WgNode });

// ---- Canvas --------------------------------------------------------------

type SnapshotIndex = Record<string, string>; // nodeId → change signature

function buildSnapshotIndex(state: ProjectState): SnapshotIndex {
  const idx: SnapshotIndex = {};
  for (const g of state.graph.goals)
    idx[`goal-${g.id}`] = signature("goal", g as Record<string, unknown>);
  for (const d of state.graph.deliverables)
    idx[`del-${d.id}`] = signature("deliverable", d as Record<string, unknown>);
  for (const dec of state.decisions)
    idx[`decision-${dec.id}`] = signature(
      "decision",
      dec as unknown as Record<string, unknown>,
    );
  for (const t of state.plan.tasks)
    idx[`task-${t.id}`] = signature("task", t as Record<string, unknown>);
  for (const r of state.graph.risks)
    idx[`risk-${r.id}`] = signature("risk", r as Record<string, unknown>);
  return idx;
}

type Positions = Record<string, { x: number; y: number }>;

// Bumped for Wave 2: the column X values shifted (decision lane added at
// 620, task moved 740→860, risk moved 1120→1180), so Wave 1 caches produce
// overlapping cards. Any older cache keys for this project are cleared on
// first load so users don't have to Clear Site Data manually.
const POSITIONS_KEY_PREFIX = "graph-pos:v2:";

function loadPositions(projectId: string): Positions {
  try {
    // Clean up any legacy Wave 1 key for this project.
    const legacy = `graph-pos:${projectId}`;
    if (localStorage.getItem(legacy) !== null) {
      localStorage.removeItem(legacy);
    }
    const raw = localStorage.getItem(POSITIONS_KEY_PREFIX + projectId);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Positions;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function savePositions(projectId: string, positions: Positions): void {
  try {
    localStorage.setItem(
      POSITIONS_KEY_PREFIX + projectId,
      JSON.stringify(positions),
    );
  } catch {
    // quota exceeded or unavailable — fine, fall back to defaults
  }
}

export function GraphCanvas({
  projectId,
  state: initialState,
}: {
  projectId: string;
  state: ProjectState;
}) {
  const t = useTranslations("graph");
  const [state, setState] = useState<ProjectState>(initialState);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [pulses, setPulses] = useState<Record<string, number>>({}); // id → expiresAt
  const [positions, setPositions] = useState<Positions>({});
  const [search, setSearch] = useState<string | null>(null);
  const [mode, setMode] = useState<IntentMode>("all");
  const [hovered, setHovered] = useState<{
    id: string;
    x: number;
    y: number;
  } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const prevSnapshotRef = useRef<SnapshotIndex>(buildSnapshotIndex(initialState));
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate localStorage positions once per project.
  useEffect(() => {
    setPositions(loadPositions(projectId));
  }, [projectId]);

  // WS listener — debounced refetch on any graph-touching frame.
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/projects/${projectId}`,
    );
    setWsState("connecting");
    ws.onopen = () => setWsState("open");
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("closed");
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as { type?: string };
        const type = typeof frame.type === "string" ? frame.type : "";
        if (
          type === "graph" ||
          type === "decision" ||
          type === "delivery" ||
          type === "conflict" ||
          type === "conflicts"
        ) {
          if (refetchTimer.current) clearTimeout(refetchTimer.current);
          refetchTimer.current = setTimeout(() => {
            api<ProjectState>(`/api/projects/${projectId}/state`)
              .then((next) => {
                // Diff: any node whose signature changed, or is newly
                // present, gets pulsed.
                const prevIdx = prevSnapshotRef.current;
                const nextIdx = buildSnapshotIndex(next);
                const expiresAt = Date.now() + PULSE_MS;
                const changed: Record<string, number> = {};
                for (const [id, sig] of Object.entries(nextIdx)) {
                  if (prevIdx[id] !== sig) changed[id] = expiresAt;
                }
                prevSnapshotRef.current = nextIdx;
                if (Object.keys(changed).length > 0) {
                  setPulses((p) => ({ ...p, ...changed }));
                }
                setState(next);
              })
              .catch(() => {
                // Keep stale state; user will see "Offline" indicator
                // until socket reconnects.
              });
          }, 350);
        }
      } catch {
        // ignore malformed frame
      }
    };
    return () => {
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
      ws.close();
    };
  }, [projectId]);


  // `/` hotkey to open search, Esc to close.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const tag =
        ev.target instanceof HTMLElement ? ev.target.tagName : "";
      const inInput = tag === "INPUT" || tag === "TEXTAREA";
      if (ev.key === "/" && search === null && !inInput) {
        ev.preventDefault();
        setSearch("");
      } else if (ev.key === "Escape") {
        if (search !== null) setSearch(null);
        else if (selected) setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [search, selected]);

  // Build nodes + edges from state. Positions: cached wins, else columnar
  // default. Pulse / dim flags come from state vars.
  //
  // Decisions are rendered in a lane between deliverables and tasks. Their
  // outbound edges come from `state.conflicts[decision.conflict_id].targets`
  // — a list of entity IDs that the resolved conflict referenced. We match
  // each target against every rendered kind and emit an edge if we find it;
  // unrendered kinds (milestones, constraints) are silently skipped.
  //
  // Intent modes dim nodes that aren't on the currently selected slice.
  // Dims only, never hide — so the viewer keeps spatial context.
  const rawQuery = search?.toLowerCase().trim() ?? "";
  const { rawNodes, rawEdges } = useMemo(() => {
    const rawNodes: Node<NodeData>[] = [];
    const rawEdges: Edge[] = [];

    const posOr = (id: string, fallback: { x: number; y: number }) =>
      positions[id] ?? fallback;

    const pulseAt = (id: string) => pulses[id] ?? 0;

    // Build a target-id lookup across every rendered kind so decisions
    // can resolve targets without scanning each list repeatedly.
    const entityToNode = new Map<string, string>(); // entity id → RF node id
    for (const g of state.graph.goals) entityToNode.set(g.id, `goal-${g.id}`);
    for (const d of state.graph.deliverables)
      entityToNode.set(d.id, `del-${d.id}`);
    for (const t of state.plan.tasks) entityToNode.set(t.id, `task-${t.id}`);
    for (const r of state.graph.risks) entityToNode.set(r.id, `risk-${r.id}`);

    // Conflict-id → targets lookup.
    const conflictTargets = new Map<string, string[]>();
    for (const c of state.conflicts) conflictTargets.set(c.id, c.targets);

    // Intent-mode highlight set. Members are dimmed=false; non-members
    // dimmed=true (when mode !== "all"). Built upfront so all node/edge
    // computations consult the same set.
    const inMode = new Set<string>();
    if (mode === "flow") {
      for (const g of state.graph.goals) inMode.add(`goal-${g.id}`);
      for (const d of state.graph.deliverables) inMode.add(`del-${d.id}`);
      for (const t of state.plan.tasks) inMode.add(`task-${t.id}`);
    } else if (mode === "decisions") {
      for (const dec of state.decisions) {
        inMode.add(`decision-${dec.id}`);
        const targets = dec.conflict_id
          ? conflictTargets.get(dec.conflict_id) ?? []
          : [];
        for (const tid of targets) {
          const nid = entityToNode.get(tid);
          if (nid) inMode.add(nid);
        }
      }
    } else if (mode === "risks") {
      for (const r of state.graph.risks) inMode.add(`risk-${r.id}`);
      // Pull in any task whose conflict targets mention this risk —
      // it's the closest thing we have to a risk→task edge today.
      const riskIds = new Set(state.graph.risks.map((r) => r.id));
      for (const c of state.conflicts) {
        if (c.targets.some((t) => riskIds.has(t))) {
          for (const t of c.targets) {
            const nid = entityToNode.get(t);
            if (nid && nid.startsWith("task-")) inMode.add(nid);
          }
        }
      }
    }

    // Returns true if a node should render dimmed under the current
    // combination of search + intent mode. Either one is sufficient.
    const matchSearch = (title: string, subtitle?: string) => {
      if (!rawQuery) return true;
      return (
        title.toLowerCase().includes(rawQuery) ||
        (subtitle ?? "").toLowerCase().includes(rawQuery)
      );
    };
    const dimFor = (id: string, title: string, subtitle?: string) => {
      if (rawQuery.length > 0 && !matchSearch(title, subtitle)) return true;
      if (mode !== "all" && !inMode.has(id)) return true;
      return false;
    };

    state.graph.goals.forEach((g, i) => {
      const id = `goal-${g.id}`;
      const title = trim(g.title, 64);
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.goal,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "goal",
          title,
          dimmed: dimFor(id, title),
          pulseExpiresAt: pulseAt(id),
        },
      });
    });

    state.graph.deliverables.forEach((d, i) => {
      const id = `del-${d.id}`;
      const title = trim(d.title, 72);
      const status = typeof d.status === "string" ? d.status : undefined;
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.deliverable,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "deliverable",
          title,
          subtitle: status,
          dimmed: dimFor(id, title, status),
          pulseExpiresAt: pulseAt(id),
        },
      });
      if (state.graph.goals.length > 0) {
        const anchor = state.graph.goals[0].id;
        rawEdges.push({
          id: `e-goal-${d.id}`,
          source: `goal-${anchor}`,
          target: id,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#c0471e" },
        });
      }
    });

    // Decisions — one node per state.decisions entry.
    state.decisions.forEach((dec, i) => {
      const id = `decision-${dec.id}`;
      const title = trim(decisionHeadline(dec), 58);
      const applyOutcome = dec.apply_outcome; // pending | ok | partial | failed | advisory
      const subtitle = applyOutcome && applyOutcome !== "ok"
        ? applyOutcome
        : undefined;
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.decision,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "decision",
          title,
          subtitle,
          dimmed: dimFor(id, title, subtitle),
          pulseExpiresAt: pulseAt(id),
        },
      });
      // Edges from decision to each resolvable target.
      const targets = dec.conflict_id
        ? conflictTargets.get(dec.conflict_id) ?? []
        : [];
      for (const tid of targets) {
        const nid = entityToNode.get(tid);
        if (!nid) continue;
        // Style varies by target kind — task/deliverable get a solid
        // accent, risk gets a dashed line so it reads as a "touches"
        // rather than a hard dependency.
        const dashed = nid.startsWith("risk-");
        rawEdges.push({
          id: `dec-${dec.id}->${tid}`,
          source: id,
          target: nid,
          style: {
            stroke: "var(--wg-accent)",
            strokeWidth: 1.1,
            strokeDasharray: dashed ? "3 3" : undefined,
            opacity: 0.7,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: "#c0471e",
          },
        });
      }
    });

    state.plan.tasks.forEach((tk, i) => {
      const id = `task-${tk.id}`;
      const title = trim(tk.title, 70);
      const subtitle = [tk.assignee_role, tk.status]
        .filter(Boolean)
        .join(" · ");
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.task,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "task",
          title,
          subtitle: subtitle || undefined,
          dimmed: dimFor(id, title, subtitle),
          pulseExpiresAt: pulseAt(id),
        },
      });
      if (tk.deliverable_id) {
        rawEdges.push({
          id: `e-del-task-${tk.id}`,
          source: `del-${tk.deliverable_id}`,
          target: id,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#c0471e" },
        });
      }
    });

    state.plan.dependencies.forEach((dep) => {
      rawEdges.push({
        id: `dep-${dep.id}`,
        source: `task-${dep.from_task_id}`,
        target: `task-${dep.to_task_id}`,
        animated: true,
        style: {
          stroke: "var(--wg-ink-soft)",
          strokeWidth: 1.2,
          strokeDasharray: "4 3",
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#5a5a5a" },
      });
    });

    state.graph.risks.forEach((r, i) => {
      const id = `risk-${r.id}`;
      const title = trim(r.title, 58);
      const sev = (r.severity || "low").toLowerCase();
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.risk,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "risk",
          title,
          subtitle: sev,
          severity: sev,
          dimmed: dimFor(id, title, sev),
          pulseExpiresAt: pulseAt(id),
        },
      });
    });

    return { rawNodes, rawEdges };
  }, [state, positions, pulses, rawQuery, mode]);

  // React Flow needs controlled state for dragging to persist. Sync our
  // computed nodes/edges into RF state whenever the computation changes.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(rawNodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(rawEdges);

  useEffect(() => {
    setRfNodes(rawNodes);
  }, [rawNodes, setRfNodes]);
  useEffect(() => {
    setRfEdges(rawEdges);
  }, [rawEdges, setRfEdges]);

  // Persist positions on drag stop.
  const onNodeDragStop = useCallback(
    (_: unknown, node: Node) => {
      setPositions((prev) => {
        const next: Positions = { ...prev, [node.id]: { ...node.position } };
        savePositions(projectId, next);
        return next;
      });
    },
    [projectId],
  );

  const onNodeMouseEnter = useCallback(
    (ev: React.MouseEvent, node: Node) => {
      setHovered({ id: node.id, x: ev.clientX, y: ev.clientY });
    },
    [],
  );
  const onNodeMouseLeave = useCallback(() => setHovered(null), []);
  const onNodeClick = useCallback(
    (_: unknown, node: Node) => setSelected(node.id),
    [],
  );

  if (rfNodes.length === 0) {
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
        {t("empty")}
      </div>
    );
  }

  const hoveredNode = hovered
    ? rfNodes.find((n) => n.id === hovered.id) ?? null
    : null;

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={onNodeDragStop}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onNodeClick={onNodeClick}
        onPaneClick={() => setSelected(null)}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        nodesDraggable
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="#e6e3db" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>

      <Legend
        labels={{
          goal: t("legend.goal"),
          deliverable: t("legend.deliverable"),
          decision: t("legend.decision"),
          task: t("legend.task"),
          risk: t("legend.risk"),
        }}
        searchHint={t("search.hint")}
      />
      <IntentStrip
        mode={mode}
        onChange={setMode}
        labels={{
          all: t("intent.all"),
          flow: t("intent.flow"),
          decisions: t("intent.decisions"),
          risks: t("intent.risks"),
        }}
      />
      <WsBadge state={wsState} labels={t} />

      {search !== null ? (
        <SearchBar
          value={search}
          onChange={setSearch}
          onClose={() => setSearch(null)}
          placeholder={t("search.placeholder")}
          count={rfNodes.filter((n) => !n.data.dimmed).length}
          noMatches={t("search.noMatches")}
        />
      ) : null}

      {hovered && hoveredNode ? (
        <HoverTooltip
          node={hoveredNode}
          x={hovered.x}
          y={hovered.y}
          labels={{
            status: t("tooltip.status"),
            severity: t("tooltip.severity"),
            owner: t("tooltip.owner"),
          }}
        />
      ) : null}

      {selected ? (
        <NodeDrawer
          nodeId={selected}
          state={state}
          projectId={projectId}
          onClose={() => setSelected(null)}
          labels={{
            close: t("drawer.close"),
            openFull: t("drawer.openFull"),
            description: t("drawer.description"),
            dependencies: t("drawer.dependencies"),
            dependedBy: t("drawer.dependedBy"),
            noDetail: t("drawer.noDetail"),
            belongsTo: t("drawer.belongsTo"),
            acceptance: t("drawer.acceptance"),
            content: t("drawer.content"),
          }}
        />
      ) : null}
    </div>
  );
}

// ---- Legend --------------------------------------------------------------

function Legend({
  labels,
  searchHint,
}: {
  labels: Record<NodeKind, string>;
  searchHint: string;
}) {
  const items: { kind: NodeKind }[] = [
    { kind: "goal" },
    { kind: "deliverable" },
    { kind: "decision" },
    { kind: "task" },
    { kind: "risk" },
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
      {items.map((it) => (
        <span
          key={it.kind}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          <span
            aria-hidden
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              background: KIND_BAR[it.kind],
              borderRadius: 2,
            }}
          />
          {labels[it.kind]}
        </span>
      ))}
      <span
        style={{
          marginLeft: 8,
          paddingLeft: 10,
          borderLeft: "1px solid var(--wg-line)",
          color: "var(--wg-ink-faint)",
        }}
      >
        {searchHint}
      </span>
    </div>
  );
}

// ---- Intent strip --------------------------------------------------------

function IntentStrip({
  mode,
  onChange,
  labels,
}: {
  mode: IntentMode;
  onChange: (m: IntentMode) => void;
  labels: Record<IntentMode, string>;
}) {
  const options: IntentMode[] = ["all", "flow", "decisions", "risks"];
  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        left: "50%",
        transform: "translateX(-50%)",
        display: "inline-flex",
        gap: 0,
        padding: 2,
        background: "rgba(255,255,255,0.96)",
        border: "1px solid var(--wg-line)",
        borderRadius: 8,
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
        zIndex: 4,
        fontSize: 12,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      {options.map((opt) => {
        const active = mode === opt;
        return (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            style={{
              padding: "5px 12px",
              background: active ? "var(--wg-accent)" : "transparent",
              color: active ? "#fff" : "var(--wg-ink-soft)",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: "inherit",
              letterSpacing: "0.02em",
              transition: "background 140ms ease-out, color 140ms ease-out",
            }}
          >
            {labels[opt]}
          </button>
        );
      })}
    </div>
  );
}

// ---- WS status -----------------------------------------------------------

function WsBadge({
  state,
  labels,
}: {
  state: "connecting" | "open" | "closed";
  labels: (k: string) => string;
}) {
  const color =
    state === "open"
      ? "#4d7a4a"
      : state === "connecting"
        ? "#c7a44a"
        : "var(--wg-ink-soft)";
  const label =
    state === "open"
      ? labels("ws.open")
      : state === "connecting"
        ? labels("ws.connecting")
        : labels("ws.closed");
  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        padding: "4px 10px",
        background: "rgba(255,255,255,0.94)",
        border: "1px solid var(--wg-line)",
        borderRadius: 12,
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-ink-soft)",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        zIndex: 4,
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          background: color,
          animation: state === "open" ? "wg-pulse 2.4s ease-out infinite" : undefined,
        }}
      />
      {label}
    </div>
  );
}

// ---- Search --------------------------------------------------------------

function SearchBar({
  value,
  onChange,
  onClose,
  placeholder,
  count,
  noMatches,
}: {
  value: string;
  onChange: (v: string) => void;
  onClose: () => void;
  placeholder: string;
  count: number;
  noMatches: string;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top: 54,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 6,
        width: "min(480px, calc(100% - 24px))",
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: 6,
        boxShadow: "0 6px 20px rgba(0,0,0,0.08)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
        }}
      >
        <span
          aria-hidden
          style={{
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          /
        </span>
        <input
          autoFocus
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
          }}
          placeholder={placeholder}
          style={{
            flex: 1,
            border: "none",
            outline: "none",
            fontSize: 13,
            fontFamily: "var(--wg-font-sans)",
            background: "transparent",
            color: "var(--wg-ink)",
            padding: "6px 0",
          }}
        />
        {value.length > 0 ? (
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: count === 0 ? "var(--wg-accent)" : "var(--wg-ink-faint)",
            }}
          >
            {count === 0 ? noMatches : count}
          </span>
        ) : null}
      </div>
    </div>
  );
}

// ---- Hover tooltip -------------------------------------------------------

function HoverTooltip({
  node,
  x,
  y,
  labels,
}: {
  node: Node<NodeData>;
  x: number;
  y: number;
  labels: { status: string; severity: string; owner: string };
}) {
  const rows: { k: string; v: string }[] = [];
  const sub = node.data.subtitle;
  if (node.data.kind === "risk" && node.data.severity) {
    rows.push({ k: labels.severity, v: node.data.severity });
  } else if (sub) {
    // subtitle pattern for task is "role · status"
    const parts = sub.split("·").map((s) => s.trim()).filter(Boolean);
    if (node.data.kind === "task") {
      if (parts.length >= 1) rows.push({ k: labels.owner, v: parts[0] });
      if (parts.length >= 2) rows.push({ k: labels.status, v: parts[1] });
    } else {
      rows.push({ k: labels.status, v: sub });
    }
  }
  return (
    <div
      style={{
        position: "fixed",
        left: Math.min(x + 14, window.innerWidth - 280),
        top: Math.min(y + 14, window.innerHeight - 120),
        padding: "8px 10px",
        background: "var(--wg-ink)",
        color: "#fff",
        borderRadius: 4,
        fontSize: 12,
        fontFamily: "var(--wg-font-sans)",
        maxWidth: 260,
        zIndex: 30,
        pointerEvents: "none",
        boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: rows.length > 0 ? 4 : 0 }}>
        {node.data.title}
      </div>
      {rows.map((r) => (
        <div
          key={r.k}
          style={{
            display: "flex",
            gap: 8,
            fontSize: 11,
            color: "#d4d1cc",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          <span style={{ opacity: 0.7 }}>{r.k}</span>
          <span>{r.v}</span>
        </div>
      ))}
    </div>
  );
}

// ---- Side drawer ---------------------------------------------------------

interface DrawerLabels {
  close: string;
  openFull: string;
  description: string;
  dependencies: string;
  dependedBy: string;
  noDetail: string;
  belongsTo: string;
  acceptance: string;
  content: string;
}

function NodeDrawer({
  nodeId,
  state,
  projectId,
  onClose,
  labels,
}: {
  nodeId: string;
  state: ProjectState;
  projectId: string;
  onClose: () => void;
  labels: DrawerLabels;
}) {
  const entity = resolveEntity(nodeId, state);
  if (!entity) return null;
  const { kind, detail } = entity;

  // Dependency rendering for tasks.
  const taskDeps: { depends_on: string[]; blocks: string[] } = {
    depends_on: [],
    blocks: [],
  };
  if (kind === "task") {
    const taskId = nodeId.slice("task-".length);
    for (const d of state.plan.dependencies) {
      if (d.to_task_id === taskId) taskDeps.depends_on.push(d.from_task_id);
      if (d.from_task_id === taskId) taskDeps.blocks.push(d.to_task_id);
    }
  }

  const taskTitle = (id: string) =>
    state.plan.tasks.find((t) => t.id === id)?.title ?? id.slice(0, 8);

  const kindColor = KIND_BAR[kind];

  return (
    <aside
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        width: "min(380px, 90%)",
        background: "var(--wg-surface-raised)",
        borderLeft: "1px solid var(--wg-line)",
        boxShadow: "-4px 0 12px rgba(0,0,0,0.06)",
        zIndex: 10,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          padding: "16px 18px",
          borderBottom: "1px solid var(--wg-line)",
          gap: 12,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: kindColor,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 6,
            }}
          >
            {kind}
          </div>
          <h3
            style={{
              margin: 0,
              fontSize: 16,
              lineHeight: 1.35,
              color: "var(--wg-ink)",
              wordBreak: "break-word",
            }}
          >
            {detail.title}
          </h3>
        </div>
        <button
          onClick={onClose}
          aria-label={labels.close}
          style={{
            background: "transparent",
            border: "none",
            fontSize: 18,
            color: "var(--wg-ink-soft)",
            cursor: "pointer",
            padding: "2px 6px",
            lineHeight: 1,
          }}
        >
          ✕
        </button>
      </header>

      <div style={{ flex: 1, overflowY: "auto", padding: "14px 18px" }}>
        {detail.status ? (
          <Row k="Status" v={detail.status} mono />
        ) : null}
        {detail.severity ? (
          <Row k="Severity" v={detail.severity} mono />
        ) : null}
        {detail.assignee_role ? (
          <Row k="Owner" v={detail.assignee_role} mono />
        ) : null}
        {detail.estimate_hours != null ? (
          <Row k="Estimate" v={`${detail.estimate_hours}h`} mono />
        ) : null}
        {detail.deliverable_id ? (
          <Row
            k={labels.belongsTo}
            v={
              state.graph.deliverables.find(
                (d) => d.id === detail.deliverable_id,
              )?.title ?? detail.deliverable_id
            }
            mono
          />
        ) : null}

        {detail.description ? (
          <Section title={labels.description}>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                lineHeight: 1.55,
                color: "var(--wg-ink)",
                whiteSpace: "pre-wrap",
              }}
            >
              {detail.description}
            </p>
          </Section>
        ) : null}

        {detail.content ? (
          <Section title={labels.content}>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                lineHeight: 1.55,
                color: "var(--wg-ink)",
                whiteSpace: "pre-wrap",
              }}
            >
              {detail.content}
            </p>
          </Section>
        ) : null}

        {detail.acceptance_criteria && detail.acceptance_criteria.length > 0 ? (
          <Section title={labels.acceptance}>
            <ul
              style={{
                margin: 0,
                padding: 0,
                listStyle: "none",
                fontSize: 13,
                lineHeight: 1.55,
              }}
            >
              {detail.acceptance_criteria.map((c, i) => (
                <li
                  key={i}
                  style={{
                    display: "flex",
                    gap: 8,
                    marginBottom: 4,
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      color: "var(--wg-accent)",
                      fontFamily: "var(--wg-font-mono)",
                      flexShrink: 0,
                    }}
                  >
                    ·
                  </span>
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </Section>
        ) : null}

        {kind === "task" && taskDeps.depends_on.length > 0 ? (
          <Section title={labels.dependencies}>
            <DepList ids={taskDeps.depends_on} render={taskTitle} />
          </Section>
        ) : null}

        {kind === "task" && taskDeps.blocks.length > 0 ? (
          <Section title={labels.dependedBy}>
            <DepList ids={taskDeps.blocks} render={taskTitle} />
          </Section>
        ) : null}

        {!detail.description &&
        !detail.content &&
        !detail.acceptance_criteria?.length &&
        taskDeps.depends_on.length === 0 &&
        taskDeps.blocks.length === 0 ? (
          <p
            style={{
              margin: "16px 0 0",
              fontSize: 13,
              color: "var(--wg-ink-faint)",
              fontStyle: "italic",
            }}
          >
            {labels.noDetail}
          </p>
        ) : null}
      </div>

      {entity.deepLinkId ? (
        <footer
          style={{
            padding: "12px 18px",
            borderTop: "1px solid var(--wg-line)",
            background: "var(--wg-surface-sunk)",
          }}
        >
          <Link
            href={`/projects/${projectId}/nodes/${entity.deepLinkId}`}
            style={{
              fontSize: 13,
              color: "var(--wg-accent)",
              fontFamily: "var(--wg-font-mono)",
              textDecoration: "none",
            }}
          >
            {labels.openFull}
          </Link>
        </footer>
      ) : null}
    </aside>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        fontSize: 12,
        marginBottom: 6,
        gap: 10,
        fontFamily: mono ? "var(--wg-font-mono)" : undefined,
      }}
    >
      <span
        style={{
          color: "var(--wg-ink-faint)",
          minWidth: 70,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          fontSize: 10,
        }}
      >
        {k}
      </span>
      <span style={{ color: "var(--wg-ink)" }}>{v}</span>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginTop: 14 }}>
      <h4
        style={{
          margin: "0 0 6px",
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {title}
      </h4>
      {children}
    </section>
  );
}

function DepList({
  ids,
  render,
}: {
  ids: string[];
  render: (id: string) => string;
}) {
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {ids.map((id) => (
        <li
          key={id}
          style={{
            fontSize: 13,
            padding: "4px 0",
            color: "var(--wg-ink)",
            borderBottom: "1px solid var(--wg-line-soft)",
          }}
        >
          {render(id)}
        </li>
      ))}
    </ul>
  );
}

// Resolve a React Flow node id into the underlying ProjectState entity.
// Returns undefined if the id doesn't map (stale node, shouldn't happen).
function resolveEntity(
  nodeId: string,
  state: ProjectState,
):
  | {
      kind: NodeKind;
      detail: {
        title: string;
        status?: string;
        severity?: string;
        description?: string;
        content?: string;
        assignee_role?: string;
        estimate_hours?: number;
        deliverable_id?: string | null;
        acceptance_criteria?: string[];
      };
      deepLinkId?: string;
    }
  | undefined {
  if (nodeId.startsWith("goal-")) {
    const id = nodeId.slice("goal-".length);
    const g = state.graph.goals.find((x) => x.id === id);
    if (!g) return undefined;
    return {
      kind: "goal",
      detail: {
        title: g.title,
        description:
          typeof g.description === "string" ? g.description : undefined,
        status: typeof g.status === "string" ? g.status : undefined,
      },
    };
  }
  if (nodeId.startsWith("del-")) {
    const id = nodeId.slice("del-".length);
    const d = state.graph.deliverables.find((x) => x.id === id);
    if (!d) return undefined;
    return {
      kind: "deliverable",
      detail: {
        title: d.title,
        status: typeof d.status === "string" ? d.status : undefined,
      },
    };
  }
  if (nodeId.startsWith("task-")) {
    const id = nodeId.slice("task-".length);
    const tk = state.plan.tasks.find((x) => x.id === id);
    if (!tk) return undefined;
    return {
      kind: "task",
      detail: {
        title: tk.title,
        description: tk.description,
        status: tk.status,
        assignee_role: tk.assignee_role ?? undefined,
        estimate_hours: tk.estimate_hours ?? undefined,
        deliverable_id: tk.deliverable_id,
        acceptance_criteria: tk.acceptance_criteria,
      },
      deepLinkId: id,
    };
  }
  if (nodeId.startsWith("risk-")) {
    const id = nodeId.slice("risk-".length);
    const r = state.graph.risks.find((x) => x.id === id);
    if (!r) return undefined;
    return {
      kind: "risk",
      detail: {
        title: r.title,
        content: r.content,
        severity: r.severity,
        status: r.status,
      },
    };
  }
  if (nodeId.startsWith("decision-")) {
    const id = nodeId.slice("decision-".length);
    const dec = state.decisions.find((x) => x.id === id);
    if (!dec) return undefined;
    return {
      kind: "decision",
      detail: {
        title: decisionHeadline(dec),
        description:
          dec.custom_text && dec.custom_text !== dec.rationale
            ? dec.rationale
            : undefined,
        status: dec.apply_outcome,
      },
    };
  }
  return undefined;
}
