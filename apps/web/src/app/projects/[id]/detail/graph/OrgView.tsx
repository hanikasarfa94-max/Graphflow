"use client";

import "reactflow/dist/style.css";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";

import { fetchOrgGraph, type OrgGraphPayload } from "@/lib/api";

// Sprint 3a — cross-project "Org" view.
//
// The landing page sells a zoom-out moment: your project shrinks and
// the surrounding team-nodes fade in. That animation is scripted in
// MorphingGraphDemo.tsx with canned peers. This component is the real
// thing — bound to /api/projects/{id}/org-graph, so the shape is
// whatever the user's live org actually is.
//
// Why a separate component instead of a mode toggle inside GraphCanvas:
//   * GraphCanvas is already ~2k LOC with timeline + commit + intent
//     strips — shoehorning another render path would obscure the
//     existing one. OrgView is stateless wrt the per-entity concerns
//     (status, severity, acceptance criteria) so its node renderer
//     is dramatically simpler.
//   * React Flow's `nodeTypes` dict is resolved once per mount; using
//     a separate subtree per mode means we can register a dedicated
//     "org-project" node type without polluting the graph view's
//     NODE_TYPES dict.
//
// Layout strategy: deterministic hub-and-spoke. The center sits at
// (0, 0) and peers are laid out on a ring of radius PEER_RADIUS. The
// angle for peer i is (2π * i / N) − π/2 so the first peer lands at
// the top of the ring (12 o'clock). This mirrors the visual rhythm
// the landing demo establishes.

const PEER_RADIUS = 260;
const CENTER_WIDTH = 240;
const PEER_WIDTH = 200;

// Relative-time formatter — compact form so peer nodes stay legible
// at a glance. We avoid pulling a date-fns-style dependency; the
// backend-returned ISO timestamp + these five bands is enough for
// the "Last activity …" line. Returns null if `iso` is null so the
// caller can render a localized "no activity yet" fallback.
function relativeTime(iso: string | null, now: Date): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const diffMs = now.getTime() - then;
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 14) return `${days}d ago`;
  const weeks = Math.round(days / 7);
  if (weeks < 8) return `${weeks}w ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

// ---- node types ---------------------------------------------------------

type CenterData = {
  title: string;
  youAreHereLabel: string;
};

type PeerData = {
  id: string;
  title: string;
  members: string;
  openRisks: number;
  openRisksLabel: string;
  lastActivity: string | null;
  lastActivityLabel: string;
  neverLabel: string;
  onOpen: (id: string) => void;
};

// Center cluster — single prominent pill. Per sprint spec, v1 keeps
// it simple (just title + "You are here" tag); v2 can swap in a live
// mini-graph if that proves useful.
function CenterNode({ data }: NodeProps<CenterData>) {
  return (
    <div
      style={{
        width: CENTER_WIDTH,
        padding: "14px 18px",
        background: "#fff",
        border: "2px solid var(--wg-accent)",
        borderRadius: 18,
        boxShadow: "0 4px 14px rgba(0,0,0,0.10)",
        fontFamily: "var(--wg-font-sans)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wg-accent)",
          marginBottom: 6,
        }}
      >
        {data.youAreHereLabel}
      </div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "var(--wg-ink)",
          lineHeight: 1.3,
        }}
      >
        {data.title}
      </div>
      {/* Handles live on all four sides so peer edges attach at the
          closest face rather than always hitting the top. */}
      <Handle type="source" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Left} style={{ opacity: 0 }} />
    </div>
  );
}

function PeerNode({ data }: NodeProps<PeerData>) {
  const hasRisk = data.openRisks > 0;
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => data.onOpen(data.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          data.onOpen(data.id);
        }
      }}
      style={{
        width: PEER_WIDTH,
        padding: "10px 12px",
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: 14,
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
        fontFamily: "var(--wg-font-sans)",
        cursor: "pointer",
        transition: "transform 120ms ease-out, box-shadow 120ms ease-out",
      }}
      onMouseEnter={(e) => {
        // Subtle lift on hover so the peer reads as interactive without
        // a loud blue border (we're on a paper-tone canvas).
        e.currentTarget.style.transform = "translateY(-1px)";
        e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.10)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "";
        e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.06)";
      }}
    >
      <div
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: "var(--wg-ink)",
          lineHeight: 1.3,
          marginBottom: 4,
        }}
      >
        {data.title}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontFamily: "var(--wg-font-mono)",
          fontSize: 10,
          color: "var(--wg-ink-soft)",
        }}
      >
        <span>{data.members}</span>
        {hasRisk ? (
          <span
            style={{
              padding: "1px 6px",
              background: "#fce7c2",
              color: "#8a5a00",
              border: "1px solid #c68a00",
              borderRadius: 8,
              letterSpacing: "0.02em",
            }}
          >
            {data.openRisksLabel.replace("{n}", String(data.openRisks))}
          </span>
        ) : null}
      </div>
      <div
        style={{
          marginTop: 4,
          fontFamily: "var(--wg-font-mono)",
          fontSize: 9,
          color: "var(--wg-ink-faint)",
          letterSpacing: "0.02em",
        }}
      >
        {data.lastActivity
          ? data.lastActivityLabel.replace("{time}", data.lastActivity)
          : data.neverLabel}
      </div>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const NODE_TYPES = {
  "org-center": CenterNode,
  "org-peer": PeerNode,
};

// ---- main component -----------------------------------------------------

export function OrgView({ projectId }: { projectId: string }) {
  const t = useTranslations("graph.org");
  const router = useRouter();
  const [payload, setPayload] = useState<OrgGraphPayload | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Pull the org graph on mount. Org membership changes are rare
  // enough that we don't bother with WS — the next time the user
  // toggles Org mode we refetch. An explicit refresh button is v2.
  useEffect(() => {
    let cancelled = false;
    setLoadError(false);
    fetchOrgGraph(projectId)
      .then((p) => {
        if (!cancelled) setPayload(p);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Build nodes + edges from the payload. useMemo so React Flow's
  // diff doesn't thrash when the parent re-renders for unrelated
  // reasons (like the toggle button hover).
  const { nodes, edges } = useMemo(() => {
    if (!payload) {
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }
    const now = new Date();
    const centerNode: Node = {
      id: `center:${payload.center.id}`,
      type: "org-center",
      position: { x: -CENTER_WIDTH / 2, y: -40 },
      data: {
        title: payload.center.title || "(untitled)",
        youAreHereLabel: t("youAreHere"),
      } satisfies CenterData,
      draggable: false,
      // Selecting the center does nothing — it represents where you
      // already are. Disable selection to suppress the ring.
      selectable: false,
    };

    const peerNodes: Node[] = payload.peers.map((peer, i) => {
      const total = Math.max(payload.peers.length, 1);
      // − π/2 offsets so peer 0 sits at 12 o'clock.
      const angle = (2 * Math.PI * i) / total - Math.PI / 2;
      const x = Math.cos(angle) * PEER_RADIUS - PEER_WIDTH / 2;
      const y = Math.sin(angle) * PEER_RADIUS - 30;
      const last = relativeTime(peer.last_activity_at, now);
      return {
        id: `peer:${peer.id}`,
        type: "org-peer",
        position: { x, y },
        data: {
          id: peer.id,
          title: peer.title || "(untitled)",
          members: t("members", { n: peer.member_count }),
          openRisks: peer.open_risks,
          openRisksLabel: t("openRisks", { n: peer.open_risks }),
          lastActivity: last,
          lastActivityLabel: t("lastActivity", { time: "{time}" }),
          neverLabel: t("never"),
          onOpen: (id: string) => router.push(`/projects/${id}/detail/graph`),
        } satisfies PeerData,
        draggable: false,
      };
    });

    const peerIds = new Set(payload.peers.map((p) => p.id));
    const edgeList: Edge[] = payload.edges
      // Defensive: an edge only renders if both endpoints are on-canvas.
      // The server already filters to the caller's projects but an
      // edge pointing at a non-rendered peer would be a dangling line.
      .filter(
        (e) =>
          e.from_project_id === payload.center.id && peerIds.has(e.to_project_id),
      )
      .map((e, i) => ({
        id: `org-edge:${i}`,
        source: `center:${e.from_project_id}`,
        target: `peer:${e.to_project_id}`,
        // Dashed stroke per sprint spec — says "connection, not
        // ownership." Weight label is the shared-member count.
        style: {
          stroke: "var(--wg-ink-faint)",
          strokeWidth: 1.2,
          strokeDasharray: "4 3",
        },
        label: t("sharedMembers", { n: e.weight }),
        labelStyle: {
          fontFamily: "var(--wg-font-mono)",
          fontSize: 9,
          fill: "var(--wg-ink-soft)",
        },
        labelBgStyle: { fill: "rgba(255,255,255,0.92)" },
        labelBgPadding: [4, 2] as [number, number],
        labelBgBorderRadius: 4,
        // No arrowhead — edge semantics are symmetric (shared member),
        // so a directional marker would misread. Keep the line clean.
        markerEnd: undefined as unknown as { type: MarkerType },
      }));

    return { nodes: [centerNode, ...peerNodes], edges: edgeList };
  }, [payload, t, router]);

  // React Flow insists on its own state hooks even though we never
  // mutate inside the canvas. Feeding our derived arrays via a setter
  // whenever they change keeps the library happy.
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(nodes);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(edges);

  useEffect(() => {
    setRfNodes(nodes);
  }, [nodes, setRfNodes]);
  useEffect(() => {
    setRfEdges(edges);
  }, [edges, setRfEdges]);

  if (loadError) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          color: "var(--wg-ink-faint)",
          fontSize: 13,
          padding: 24,
          textAlign: "center",
        }}
      >
        {t("noPeers")}
      </div>
    );
  }

  if (payload && payload.peers.length === 0) {
    // Empty state — still render the center so "you are here" is
    // always visible, but stack a soft explainer below it. The
    // canvas-in-canvas is deliberate: it says "this IS your org
    // graph, it just happens to be one node today."
    return (
      <div
        style={{
          position: "relative",
          width: "100%",
          height: "100%",
        }}
      >
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          nodesDraggable={false}
          panOnDrag
          zoomOnScroll={false}
          zoomOnPinch
          zoomOnDoubleClick={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} color="#e6e3db" />
        </ReactFlow>
        <div
          style={{
            position: "absolute",
            bottom: 20,
            left: "50%",
            transform: "translateX(-50%)",
            background: "rgba(255,255,255,0.94)",
            border: "1px dashed var(--wg-line)",
            borderRadius: 12,
            padding: "8px 14px",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            letterSpacing: "0.02em",
            maxWidth: 420,
            textAlign: "center",
          }}
        >
          {t("noPeers")}
        </div>
      </div>
    );
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="#e6e3db" />
        <Controls position="bottom-right" showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
