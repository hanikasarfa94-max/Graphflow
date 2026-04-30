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

import {
  api,
  fetchGraphAt,
  fetchTimeline,
  simulateDropTask,
  type ProjectState,
  type SimulationResult,
  type TimelineResponse,
} from "@/lib/api";

import { CommitModal } from "./CommitModal";
import { OrgView } from "./OrgView";
import { TimelineStrip } from "./TimelineStrip";

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

type NodeKind =
  | "goal"
  | "commitment"
  | "deliverable"
  | "decision"
  | "task"
  | "risk";

// Intent strip modes — "which slice of the graph do I care about right
// now?" Active mode dims non-members without hiding them, so the viewer
// keeps spatial context.
type IntentMode = "all" | "flow" | "decisions" | "risks" | "commitments";

// Sprint 2a adds a commitment lane between goals and deliverables.
// Commitments are promises of future state (distinct from decisions,
// which pick between options). They sit close to goals because they
// usually frame the project's target. Every column ends ≥40px before
// the next one starts so cards breathe at fitView zoom.
//   goal:        40   → 300
//   commitment:  340  → 540
//   deliverable: 580  → 840
//   decision:    880  → 1080
//   task:        1120 → 1400
//   risk:        1440 → 1680
const COL_X: Record<NodeKind, number> = {
  goal: 40,
  commitment: 340,
  deliverable: 580,
  decision: 880,
  task: 1120,
  risk: 1440,
};
const ROW_STEP = 110;
const ROW_START = 40;

const NODE_WIDTH: Record<NodeKind, number> = {
  goal: 260,
  commitment: 200,
  deliverable: 260,
  decision: 200,
  task: 280,
  risk: 240,
};

// Severity palette — reused for risks. v2 (blue/white): critical/high
// flip to danger-red because in v1 the brand-accent doubled as a danger
// signal (terracotta has danger vibes); v2 separates them — blue is
// brand, red is danger. Medium amber stays amber-class. Low neutral
// stays neutral.
const SEVERITY_TINT: Record<string, string> = {
  critical: "#fee2e2",
  high: "#fee2e2",
  medium: "#fef3c7",
  low: "#eef3fb",
};
const SEVERITY_BORDER: Record<string, string> = {
  critical: "#dc2626",
  high: "#dc2626",
  medium: "#d97706",
  low: "#9aa8bd",
};

// Left-side bar color per kind. Bar is the primary differentiator at
// a glance — eye reads the stripe before reading the label.
// v2 note: risk uses --wg-danger (not --wg-accent) because in v1
// terracotta-as-accent had a danger-tint built in; v2 brand blue
// doesn't, so we explicitly route risks to the danger color. Goal/
// decision keep --wg-accent because they ARE the primary affordance.
const KIND_BAR: Record<NodeKind, string> = {
  goal: "var(--wg-accent)",
  commitment: "#d97706",
  deliverable: "#16a34a",
  decision: "var(--wg-accent)",
  task: "var(--wg-ink-faint)",
  risk: "var(--wg-danger)",
};
const KIND_ICON: Record<NodeKind, string> = {
  goal: "◆",
  commitment: "◎",
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

// Short, humanized "due in 4h" / "overdue 2d" badge for a commitment
// node's subtitle. Returns null when the commitment has no SLA window
// or no target_date (can't measure), when it's already resolved, or
// when it's in the safe band (more than sla_window before target).
// Intentionally mirrors SlaService's band logic so the client can
// render honestly without another round-trip. If server and client
// ever diverge the server's signal remains the source of truth — the
// badge is the visual shortcut.
function computeSlaBadge(
  status: string,
  targetDateIso: string | null,
  slaWindowSeconds: number | null,
): string | null {
  if (status !== "open") return null;
  if (!targetDateIso || !slaWindowSeconds) return null;
  const target = new Date(targetDateIso).valueOf();
  if (Number.isNaN(target)) return null;
  const now = Date.now();
  const remainingMs = target - now;
  const remainingSec = Math.round(remainingMs / 1000);
  if (remainingSec < 0) {
    return `overdue ${humanizeDuration(-remainingSec)}`;
  }
  if (remainingSec <= slaWindowSeconds) {
    return `due ${humanizeDuration(remainingSec)}`;
  }
  return null;
}

function humanizeDuration(totalSeconds: number): string {
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(totalSeconds / 3600);
  if (hours < 48) return `${hours}h`;
  const days = Math.round(totalSeconds / 86400);
  return `${days}d`;
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
  // Counterfactual simulation overlay role. When non-null, the node
  // renders with a colored ring + chip describing its role in the
  // hypothetical scenario. Only set when sim mode is active.
  simRole?: "dropped" | "orphan" | "exposed" | "at_risk" | null;
}

// Visual tuning per simulation role. Dropped is loud (accent/red);
// orphan / exposed / at_risk share an amber warning band; null = live view.
const SIM_ROLE_STYLE: Record<
  "dropped" | "orphan" | "exposed" | "at_risk",
  { ring: string; chipBg: string; chipFg: string; label: string }
> = {
  dropped: {
    ring: "var(--wg-accent)",
    chipBg: "var(--wg-accent)",
    chipFg: "#fff",
    label: "DROPPED",
  },
  orphan: {
    ring: "var(--wg-amber)",
    chipBg: "var(--wg-amber)",
    chipFg: "#fff",
    label: "ORPHAN",
  },
  exposed: {
    ring: "var(--wg-amber)",
    chipBg: "var(--wg-amber)",
    chipFg: "#fff",
    label: "EXPOSED",
  },
  at_risk: {
    ring: "var(--wg-amber)",
    chipBg: "var(--wg-amber-soft)",
    chipFg: "var(--wg-amber)",
    label: "AT RISK",
  },
};

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

  const simStyle = data.simRole ? SIM_ROLE_STYLE[data.simRole] : null;
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        padding: "9px 12px 9px 16px",
        background: bg,
        border: `1px solid ${
          simStyle
            ? simStyle.ring
            : selected
              ? "var(--wg-accent)"
              : "var(--wg-line)"
        }`,
        borderRadius: 6,
        width: NODE_WIDTH[data.kind],
        opacity: data.dimmed ? 0.22 : 1,
        transition:
          "opacity 200ms ease-out, border-color 140ms ease-out, box-shadow 200ms ease-out",
        boxShadow: simStyle
          ? `0 0 0 2px ${simStyle.ring}`
          : pulsing
            ? "0 0 0 3px var(--wg-accent-ring), 0 0 16px rgba(37, 99, 235, 0.28)"
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
      {simStyle ? (
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: -9,
            left: 10,
            padding: "2px 6px",
            background: simStyle.chipBg,
            color: simStyle.chipFg,
            fontSize: 9,
            fontFamily: "var(--wg-font-mono)",
            letterSpacing: "0.08em",
            borderRadius: 3,
            boxShadow: "0 1px 2px rgba(0,0,0,0.1)",
          }}
        >
          {simStyle.label}
        </div>
      ) : null}
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
  for (const cm of state.commitments ?? [])
    idx[`commitment-${cm.id}`] = signature(
      "commitment",
      cm as unknown as Record<string, unknown>,
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
const POSITIONS_KEY_PREFIX = "graph-pos:v3:";

function loadPositions(projectId: string): Positions {
  try {
    // Drop superseded keys. Each column-layout shift bumps the version
    // suffix; stale caches would collide with the new X positions.
    for (const legacy of [
      `graph-pos:${projectId}`,
      `graph-pos:v2:${projectId}`,
    ]) {
      if (localStorage.getItem(legacy) !== null) {
        localStorage.removeItem(legacy);
      }
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
  // Sprint 1b: the "live" state is the one we hydrated from /state +
  // keep in sync via WS. When the user scrubs back, we swap `state`
  // for the /graph-at payload but stash the live copy so a snap-to-Live
  // doesn't require a round-trip. `cursorTs=null` means live.
  const liveStateRef = useRef<ProjectState>(initialState);
  const [cursorTs, setCursorTs] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
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
  const [commitModalOpen, setCommitModalOpen] = useState(false);
  // Counterfactual simulation overlay. When non-null, the graph renders
  // sim chips + dims unaffected nodes. Cleared by the "Exit simulation"
  // button or by navigating away.
  const [simulation, setSimulation] = useState<SimulationResult | null>(
    null,
  );
  const [simRunning, setSimRunning] = useState(false);
  // Sprint 3a — view toggle between the per-project graph and the
  // cross-project org meta-graph. Purely client state; no URL change
  // in v1. "graph" is the default so existing bookmarks keep working.
  const [viewMode, setViewMode] = useState<"graph" | "org">("graph");

  const prevSnapshotRef = useRef<SnapshotIndex>(buildSnapshotIndex(initialState));
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Mirror cursorTs into a ref so the WS-onmessage closure (bound at
  // mount time with [projectId] dep only) always reads the current
  // value rather than the mount-time stale one.
  const cursorTsRef = useRef<string | null>(cursorTs);
  useEffect(() => {
    cursorTsRef.current = cursorTs;
  }, [cursorTs]);

  // Hydrate localStorage positions once per project.
  useEffect(() => {
    setPositions(loadPositions(projectId));
  }, [projectId]);

  // Fetch the timeline metadata on mount. Markers + bounds rarely
  // change without a corresponding WS frame, so this runs exactly once
  // per project; the WS handler re-fetches when new events arrive.
  useEffect(() => {
    let cancelled = false;
    fetchTimeline(projectId)
      .then((tl) => {
        if (!cancelled) setTimeline(tl);
      })
      .catch(() => {
        // Non-fatal — strip renders nothing when timeline is null.
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Cursor change: fetch /graph-at and swap state. Null snaps back to
  // live (which uses the ref we stashed on every WS refetch so there's
  // no round-trip).
  useEffect(() => {
    if (cursorTs === null) {
      setState(liveStateRef.current);
      return;
    }
    let cancelled = false;
    fetchGraphAt(projectId, cursorTs)
      .then((historical) => {
        if (cancelled) return;
        // Shape matches ProjectState closely — GraphAtState is a
        // superset with `as_of`. Cast is safe because GraphCanvas only
        // reads the overlapping fields.
        setState(historical as unknown as ProjectState);
      })
      .catch(() => {
        // Leave the prior state in place; user will see stale data
        // momentarily until they pick a valid ts or click Live.
      });
    return () => {
      cancelled = true;
    };
  }, [cursorTs, projectId]);

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
                // Always stash the latest live state. If the user is
                // currently scrubbing the past, don't overwrite the
                // visible state — they explicitly chose a historical
                // view. They'll hit "Live" to catch up.
                liveStateRef.current = next;
                if (cursorTsRef.current === null) setState(next);
                // Re-fetch the timeline so new markers appear. Cheap —
                // projects have O(hundreds) of marker-worthy events.
                fetchTimeline(projectId)
                  .then(setTimeline)
                  .catch(() => {
                    // Non-fatal; strip keeps stale bounds.
                  });
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
    } else if (mode === "commitments") {
      // Commitments + the graph entities they scope to. Unanchored
      // commitments still light up — the promise itself is what the
      // viewer wants to focus on.
      for (const cm of state.commitments ?? []) {
        inMode.add(`commitment-${cm.id}`);
        if (cm.scope_ref_kind && cm.scope_ref_id) {
          if (cm.scope_ref_kind === "deliverable")
            inMode.add(`del-${cm.scope_ref_id}`);
          else if (cm.scope_ref_kind === "task")
            inMode.add(`task-${cm.scope_ref_id}`);
          else if (cm.scope_ref_kind === "goal")
            inMode.add(`goal-${cm.scope_ref_id}`);
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
    // Counterfactual overlay — when a simulation is active, build a
    // map of node-id → simulation role so the render pass can stamp
    // chips + dim non-affected nodes.
    const simRoleMap = new Map<
      string,
      "dropped" | "orphan" | "exposed" | "at_risk"
    >();
    if (simulation) {
      for (const d of simulation.dropped) simRoleMap.set(`task-${d.id}`, "dropped");
      for (const o of simulation.orphan_tasks) simRoleMap.set(`task-${o.id}`, "orphan");
      for (const d of simulation.exposed_deliverables)
        simRoleMap.set(`del-${d.id}`, "exposed");
      for (const c of simulation.at_risk_commitments)
        simRoleMap.set(`commitment-${c.id}`, "at_risk");
      // Milestones aren't rendered as graph nodes; the banner lists them.
    }

    const dimFor = (id: string, title: string, subtitle?: string) => {
      // Sim mode dominates: when active, only nodes in the blast radius
      // stay at full opacity. Search + intent dimming take a backseat
      // so the viewer focuses on the hypothetical.
      if (simulation) return !simRoleMap.has(id);
      if (rawQuery.length > 0 && !matchSearch(title, subtitle)) return true;
      if (mode !== "all" && !inMode.has(id)) return true;
      return false;
    };
    const simRoleFor = (id: string): NodeData["simRole"] =>
      simRoleMap.get(id) ?? null;

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
          simRole: simRoleFor(id),
        },
      });
    });

    // Commitments — promises of future state. Rendered in their own
    // column between goals and deliverables. Target-date shows as
    // subtitle when present; status badge via the bar color
    // (amber/sage later; see SEVERITY handling below).
    (state.commitments ?? []).forEach((cm, i) => {
      const id = `commitment-${cm.id}`;
      const title = trim(cm.headline, 64);
      const subtitleParts: string[] = [];
      if (cm.target_date) {
        try {
          subtitleParts.push(
            new Date(cm.target_date).toLocaleDateString(undefined, {
              month: "short",
              day: "numeric",
            }),
          );
        } catch {
          // fall through — no date on subtitle
        }
      }
      if (cm.status && cm.status !== "open") {
        subtitleParts.push(cm.status);
      }
      // SLA badge suffix: computed client-side to stay honest with the
      // live wall clock. The server-side SlaService fires escalation
      // messages when a commitment actually crosses a band, but the
      // badge below is just a visual state projection — it updates on
      // every re-render without waiting for an escalation event.
      const slaBadge = computeSlaBadge(
        cm.status,
        cm.target_date,
        cm.sla_window_seconds,
      );
      if (slaBadge) subtitleParts.push(slaBadge);
      const subtitle = subtitleParts.join(" · ") || undefined;
      rawNodes.push({
        id,
        type: "wg",
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        position: posOr(id, {
          x: COL_X.commitment,
          y: ROW_START + i * ROW_STEP,
        }),
        data: {
          kind: "commitment",
          title,
          subtitle,
          dimmed: dimFor(id, title, subtitle),
          pulseExpiresAt: pulseAt(id),
          simRole: simRoleFor(id),
        },
      });
      // If the commitment is anchored to a graph entity, emit a
      // dashed edge to it so the scope is visible.
      if (cm.scope_ref_kind && cm.scope_ref_id) {
        const targetNodeId = (() => {
          switch (cm.scope_ref_kind) {
            case "deliverable":
              return `del-${cm.scope_ref_id}`;
            case "task":
              return `task-${cm.scope_ref_id}`;
            case "goal":
              return `goal-${cm.scope_ref_id}`;
            case "milestone":
              return null; // milestones not rendered as nodes today
            default:
              return null;
          }
        })();
        if (targetNodeId) {
          rawEdges.push({
            id: `e-cm-${cm.id}`,
            source: id,
            target: targetNodeId,
            style: {
              stroke: "#d97706",
              strokeWidth: 1.1,
              strokeDasharray: "3 3",
              opacity: 0.7,
            },
            markerEnd: { type: MarkerType.ArrowClosed, color: "#d97706" },
          });
        }
      }
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
          simRole: simRoleFor(id),
        },
      });
      if (state.graph.goals.length > 0) {
        const anchor = state.graph.goals[0].id;
        rawEdges.push({
          id: `e-goal-${d.id}`,
          source: `goal-${anchor}`,
          target: id,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#2563eb" },
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
          simRole: simRoleFor(id),
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
            color: "#2563eb",
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
          simRole: simRoleFor(id),
        },
      });
      if (tk.deliverable_id) {
        rawEdges.push({
          id: `e-del-task-${tk.id}`,
          source: `del-${tk.deliverable_id}`,
          target: id,
          style: { stroke: "var(--wg-accent)", strokeWidth: 1.2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#2563eb" },
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
          simRole: simRoleFor(id),
        },
      });
    });

    return { rawNodes, rawEdges };
  }, [state, positions, pulses, rawQuery, mode, simulation]);

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

  const isPast = cursorTs !== null;
  const isOrgMode = viewMode === "org";
  const viewerTier = state.viewer_license_tier ?? "full";
  const licenseBannerKey =
    viewerTier === "task_scoped"
      ? "licenseBanner.taskScoped"
      : viewerTier === "observer"
        ? "licenseBanner.observer"
        : null;

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* License-scope banner — shows when the viewer is on a
          restricted tier so they understand why their /state is
          filtered. Sits above the timeline strip so it's the first
          thing their eye picks up when landing on the graph. */}
      {licenseBannerKey ? (
        <div
          role="status"
          data-testid="license-banner"
          style={{
            padding: "6px 12px",
            background: "var(--wg-amber-soft)",
            color: "var(--wg-ink)",
            border: "1px solid var(--wg-amber)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            margin: "4px 8px 0",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            flex: "0 0 auto",
          }}
        >
          {/* Use any-string lookup so older locales without the keys
              fall through without crashing — useTranslations returns
              the key itself on miss. */}
          {t(licenseBannerKey)}
        </div>
      ) : null}
      {/* Counterfactual simulation banner — tells the viewer what
          scenario is active and summarizes the blast radius. Click
          Exit to return to the live graph. */}
      {simulation ? (
        <div
          role="status"
          data-testid="sim-banner"
          style={{
            padding: "8px 12px",
            background: "rgba(37, 99, 235,0.06)",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            margin: "4px 8px 0",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            flex: "0 0 auto",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span style={{ color: "var(--wg-ink)" }}>
            {t("sim.banner", {
              headline:
                simulation.dropped[0]?.title ?? simulation.entity_id.slice(0, 8),
              orphans: simulation.orphan_tasks.length,
              exposed: simulation.exposed_deliverables.length,
              slipping: simulation.slipping_milestones.length,
              atRisk: simulation.at_risk_commitments.length,
            })}
          </span>
          <button
            type="button"
            onClick={() => setSimulation(null)}
            style={{
              background: "var(--wg-accent)",
              color: "#fff",
              border: 0,
              padding: "4px 10px",
              borderRadius: 4,
              fontFamily: "inherit",
              fontSize: 11,
              cursor: "pointer",
              letterSpacing: "0.04em",
            }}
          >
            {t("sim.exit")}
          </button>
        </div>
      ) : simRunning ? (
        <div
          role="status"
          style={{
            padding: "6px 12px",
            background: "var(--wg-surface-sunk)",
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            margin: "4px 8px 0",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            flex: "0 0 auto",
            color: "var(--wg-ink-soft)",
          }}
        >
          {t("sim.running")}
        </div>
      ) : null}
      {/* Timeline scrubber — rendered above the canvas so the user
          keeps the "when am I looking at?" context in peripheral view.
          Falls back to null when the timeline metadata hasn't loaded
          yet, which keeps the graph layout stable on cold cache.
          Sprint 3a: hidden in Org mode — the org meta-graph isn't
          time-cursor aware in v1, so showing the scrubber would
          misleadingly imply it is. */}
      {!isOrgMode ? (
        <div style={{ padding: "6px 0", flex: "0 0 auto" }}>
          <TimelineStrip
            timeline={timeline}
            cursorTs={cursorTs}
            onChange={setCursorTs}
            labels={{
              live: t("timeline.live"),
              asOf: t("timeline.asOf"),
              playhead: t("timeline.playhead"),
              markerDecision: t("timeline.markerDecision"),
              markerConflict: t("timeline.markerConflict"),
              markerTransition: t("timeline.markerTransition"),
            }}
          />
        </div>
      ) : null}
      {/* Canvas area — the dim overlay layers on top at 0.45 opacity
          when cursor is in the past, without blocking pointer events
          on the graph itself (markers, zoom, drawer still work). The
          "viewing as of" pill sits over the dim so it stays legible
          regardless of what's underneath. */}
      <div
        style={{
          position: "relative",
          flex: 1,
          minHeight: 0,
          // Dim via filter rather than opacity so the Background
          // gap/color from ReactFlow stays crisp. prefers-reduced-motion
          // handled by the transition: we drop the duration to 0 via
          // media query on the canvas container. Org mode skips the
          // dim entirely since it isn't time-scoped.
          filter:
            isPast && !isOrgMode
              ? "saturate(0.55) brightness(0.96)"
              : "none",
          transition: "filter 220ms ease-out",
        }}
      >
      {/* View-mode swap. Graph mode = full ReactFlow canvas with all
          the per-entity chrome (legend, intent strip, commit button,
          search). Org mode = OrgView with its own mini-ReactFlow; the
          surrounding chrome (WsBadge, view toggle) stays, the graph-
          specific chrome hides so the org canvas isn't visually noisy. */}
      {!isOrgMode ? (
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
      ) : (
        <OrgView projectId={projectId} />
      )}

      {/* Graph-mode-specific chrome — hidden in Org mode because the
          legend, intent strip, search bar, and + Commit button have
          no meaning against a cross-project view. */}
      {!isOrgMode ? (
        <>
          <Legend
            labels={{
              goal: t("legend.goal"),
              commitment: t("legend.commitment"),
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
              commitments: t("intent.commitments"),
            }}
          />
        </>
      ) : null}
      <WsBadge state={wsState} labels={t} />

      {/* View toggle — Graph | Org. Sits immediately to the left of
          WsBadge/the + Commit area so it shares the top-right strip.
          In Org mode the + Commit button is hidden, which shifts the
          toggle's right-offset to match the badge row. */}
      <ViewToggle
        mode={viewMode}
        onChange={setViewMode}
        labels={{
          graph: t("org.toggle.graph"),
          org: t("org.toggle.org"),
        }}
        rightOffset={isOrgMode ? 118 : 204}
      />

      {/* + Commit button — opens CommitModal. Positioned to the left of
          the WsBadge pill so they align on the same top-right row.
          Sprint 3a: hidden in Org mode (commitments are per-project). */}
      {!isOrgMode ? (
        <button
          type="button"
          onClick={() => setCommitModalOpen(true)}
          style={{
            position: "absolute",
            top: 12,
            right: 118,
            padding: "4px 12px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: 12,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            letterSpacing: "0.02em",
            cursor: "pointer",
            zIndex: 4,
            boxShadow: "0 1px 3px rgba(0,0,0,0.12)",
          }}
        >
          {t("commit.button")}
        </button>
      ) : null}

      {!isOrgMode && search !== null ? (
        <SearchBar
          value={search}
          onChange={setSearch}
          onClose={() => setSearch(null)}
          placeholder={t("search.placeholder")}
          count={rfNodes.filter((n) => !n.data.dimmed).length}
          noMatches={t("search.noMatches")}
        />
      ) : null}

      {!isOrgMode && hovered && hoveredNode ? (
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

      {!isOrgMode && selected ? (
        <NodeDrawer
          nodeId={selected}
          state={state}
          projectId={projectId}
          onClose={() => setSelected(null)}
          onSimulate={async (taskId) => {
            setSelected(null);
            setSimRunning(true);
            try {
              const result = await simulateDropTask(projectId, taskId);
              setSimulation(result);
            } catch {
              // Swallow — sim is a read-only exploration; worst case
              // the overlay doesn't appear and the graph stays live.
            } finally {
              setSimRunning(false);
            }
          }}
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
            simulate: t("drawer.simulate"),
          }}
        />
      ) : null}

      {!isOrgMode && commitModalOpen ? (
        <CommitModal
          projectId={projectId}
          onClose={() => setCommitModalOpen(false)}
          onCreated={() => {
            // Close the modal, then refetch project state so the
            // new commitment flows into the graph. No optimistic
            // merge — the backend's shape is authoritative and the
            // refetch costs one round-trip.
            setCommitModalOpen(false);
            api<ProjectState>(`/api/projects/${projectId}/state`)
              .then((next) => setState(next))
              .catch(() => {
                // stale state is fine; user can manually reload
              });
          }}
        />
      ) : null}

      </div>
      {/* "Viewing as of" pill — anchored bottom-left of the outer
          flex container so it sits outside the dimmed canvas wrapper
          and stays at full saturation. Click to snap back to Live.
          Sprint 3a: only shown in graph mode. Org mode isn't time-
          cursor aware, so the pill would be misleading there. */}
      {isPast && !isOrgMode ? (
        <button
          type="button"
          onClick={() => setCursorTs(null)}
          style={{
            position: "absolute",
            bottom: 14,
            left: 14,
            padding: "6px 12px",
            background: "var(--wg-ink)",
            color: "#fff",
            border: "none",
            borderRadius: 20,
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            letterSpacing: "0.04em",
            cursor: "pointer",
            zIndex: 12,
            boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            aria-hidden
            style={{
              width: 6,
              height: 6,
              borderRadius: 3,
              background: "var(--wg-accent)",
            }}
          />
          {t("timeline.viewingAsOf", {
            when: new Date(cursorTs).toLocaleString(),
          })}
          <span style={{ opacity: 0.7, marginLeft: 6 }}>
            · {t("timeline.backToLive")}
          </span>
        </button>
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
    { kind: "commitment" },
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
  const options: IntentMode[] = [
    "all",
    "flow",
    "decisions",
    "risks",
    "commitments",
  ];
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
      ? "#16a34a"
      : state === "connecting"
        ? "#d97706"
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

// ---- View-mode toggle (Sprint 3a) ---------------------------------------

function ViewToggle({
  mode,
  onChange,
  labels,
  rightOffset,
}: {
  mode: "graph" | "org";
  onChange: (next: "graph" | "org") => void;
  labels: { graph: string; org: string };
  // The toggle shares the top-right strip with the WsBadge and the
  // + Commit button. Right offset is computed at the call site so it
  // flexes with whichever neighbours are visible.
  rightOffset: number;
}) {
  return (
    <div
      role="group"
      aria-label="view mode"
      style={{
        position: "absolute",
        top: 12,
        right: rightOffset,
        display: "inline-flex",
        background: "rgba(255,255,255,0.94)",
        border: "1px solid var(--wg-line)",
        borderRadius: 12,
        padding: 2,
        fontFamily: "var(--wg-font-mono)",
        fontSize: 10,
        letterSpacing: "0.04em",
        zIndex: 4,
        boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
      }}
    >
      {(["graph", "org"] as const).map((m) => {
        const active = mode === m;
        return (
          <button
            key={m}
            type="button"
            onClick={() => onChange(m)}
            aria-pressed={active}
            style={{
              padding: "4px 10px",
              borderRadius: 10,
              border: "none",
              background: active ? "var(--wg-ink)" : "transparent",
              color: active ? "#fff" : "var(--wg-ink-soft)",
              cursor: active ? "default" : "pointer",
              transition: "background 120ms ease-out, color 120ms ease-out",
            }}
          >
            {labels[m]}
          </button>
        );
      })}
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
  simulate?: string;
}

function NodeDrawer({
  nodeId,
  state,
  projectId,
  onClose,
  onSimulate,
  labels,
}: {
  nodeId: string;
  state: ProjectState;
  projectId: string;
  onClose: () => void;
  // Called when the user clicks "⚡ Simulate drop" on a task node.
  // GraphCanvas fires the API call and flips the overlay on.
  onSimulate?: (taskId: string) => void;
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
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 8,
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
          {/* Simulate drop — only makes sense for tasks (the backend
              only supports drop_task in v1). Fires the API call via
              the parent callback; drawer closes so the overlay is
              uncluttered. */}
          {kind === "task" && onSimulate && labels.simulate ? (
            <button
              type="button"
              onClick={() => {
                if (entity.deepLinkId) {
                  onSimulate(entity.deepLinkId);
                }
              }}
              style={{
                padding: "4px 10px",
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                background: "var(--wg-accent)",
                color: "#fff",
                border: 0,
                borderRadius: 4,
                cursor: "pointer",
                letterSpacing: "0.04em",
              }}
            >
              {labels.simulate}
            </button>
          ) : null}
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
  if (nodeId.startsWith("commitment-")) {
    const id = nodeId.slice("commitment-".length);
    const cm = (state.commitments ?? []).find((x) => x.id === id);
    if (!cm) return undefined;
    const descParts: string[] = [];
    if (cm.target_date) {
      try {
        descParts.push(
          `Target: ${new Date(cm.target_date).toLocaleDateString()}`,
        );
      } catch {
        // skip
      }
    }
    if (cm.metric) descParts.push(`Metric: ${cm.metric}`);
    return {
      kind: "commitment",
      detail: {
        title: cm.headline,
        description: descParts.join("\n") || undefined,
        status: cm.status,
      },
    };
  }
  return undefined;
}
