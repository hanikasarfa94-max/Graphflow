"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

const LOOP_MS = 12000;
const FADE = 320;

// Piecewise linear: 0 before inAt, ramps to 1 by inAt+FADE, holds, ramps back
// to 0 between outAt-FADE and outAt. Used everywhere so reveals/fadeouts stay
// consistent with the 320ms motion token.
function fade(t: number, inAt: number, outAt: number): number {
  if (t < inAt) return 0;
  if (t < inAt + FADE) return (t - inAt) / FADE;
  if (t < outAt - FADE) return 1;
  if (t < outAt) return (outAt - t) / FADE;
  return 0;
}

// Edges use pathLength=100, so offset is a 0-100 number.
function edgeOffset(t: number, inAt: number): number {
  if (t < inAt) return 100;
  if (t < inAt + FADE) return 100 - ((t - inAt) / FADE) * 100;
  return 0;
}

// Smoothstep clamped to [0,1] — used for the zoom-out interpolation so the
// camera pull doesn't jerk.
function smoothstep(x: number): number {
  const c = Math.max(0, Math.min(1, x));
  return c * c * (3 - 2 * c);
}

type StageKey = "intake" | "clarify" | "plan" | "decide" | "deliver";
const NODE_R = 14;
const NODES: { key: StageKey; cx: number; cy: number; inAt: number }[] = [
  { key: "intake", cx: 60, cy: 200, inAt: 900 },
  { key: "clarify", cx: 150, cy: 200, inAt: 1400 },
  { key: "plan", cx: 240, cy: 200, inAt: 1900 },
  { key: "decide", cx: 330, cy: 200, inAt: 2400 },
  { key: "deliver", cx: 420, cy: 200, inAt: 2900 },
];
const COMP_CX = 285;
const COMP_CY = 120;

// Zoom-out — your graph shrinks to 32% around this point, and five peer
// team-nodes fade in around it. The Legal peer closes the narrative loop
// (Legal flagged compliance earlier; here you see Legal as a node of your
// org graph with an edge to yours).
const ZOOM_START = 7300;
const ZOOM_END = 8500;
const ZOOM_SCALE = 0.32;
const GRAPH_CENTER = { x: 240, y: 180 }; // pre-zoom center of the 5 nodes
const ZOOM_TARGET = { x: 260, y: 190 }; // where the shrunken cluster lands

type PeerKey = "legal" | "mobile" | "design" | "infra" | "ops";
const PEERS: { key: PeerKey; x: number; y: number; inAt: number; w: number }[] =
  [
    { key: "legal", x: 120, y: 150, inAt: 8200, w: 64 },
    { key: "mobile", x: 260, y: 70, inAt: 8320, w: 72 },
    { key: "design", x: 400, y: 150, inAt: 8440, w: 68 },
    { key: "infra", x: 340, y: 290, inAt: 8560, w: 64 },
    { key: "ops", x: 180, y: 290, inAt: 8680, w: 56 },
  ];

const META_EDGES = [
  // Central cluster ↔ peers. Start point is the post-zoom center of your
  // graph; end point is a peer node. The Legal edge lands first to tie back
  // to the earlier "Legal flagged compliance" bubble.
  { x1: 260, y1: 190, x2: 120, y2: 150, inAt: 8700 },
  { x1: 260, y1: 190, x2: 260, y2: 70, inAt: 8820 },
  { x1: 260, y1: 190, x2: 400, y2: 150, inAt: 8940 },
  // One peer-to-peer edge so it reads as a network, not hub-and-spoke.
  { x1: 400, y1: 150, x2: 340, y2: 290, inAt: 9060 },
];

export function MorphingGraphDemo() {
  const t = useTranslations("landing");
  const [elapsed, setElapsed] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (reducedMotion) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      setElapsed((now - start) % LOOP_MS);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reducedMotion]);

  // Reduced motion: freeze at the end-state (meta-graph visible) so viewers
  // still see the payoff frame.
  const e = reducedMotion ? 10000 : elapsed;

  // Chat bubbles fade out before the zoom so the camera pull feels clean.
  const chat1Op = fade(e, 400, 7000);
  const chat2Op = fade(e, 4400, 7000);

  // The direct Plan→Decide edge dims to 0.25 when the compliance reroute
  // arrives, signaling "rerouted" rather than "deleted."
  const directDimmed = e > 5000;
  const directOpFull = fade(e, 2200, 11400);
  const directOp = directDimmed ? directOpFull * 0.25 : directOpFull;
  const compOp = fade(e, 5100, 11400);
  const slaBeforeOp = fade(e, 3100, 5800);
  const slaAfterOp = fade(e, 6000, 11400);

  // Stage text labels fade out pre-zoom — at 0.32x they'd be unreadable, and
  // the "Stellar Drift" pill replaces them post-zoom.
  const labelOutAt = 7000;

  // Zoom progression — drives the SVG matrix on the main-graph group.
  const zp = smoothstep((e - ZOOM_START) / (ZOOM_END - ZOOM_START));
  const s = 1 - (1 - ZOOM_SCALE) * zp;
  const tx = (ZOOM_TARGET.x - ZOOM_SCALE * GRAPH_CENTER.x) * zp;
  const ty = (ZOOM_TARGET.y - ZOOM_SCALE * GRAPH_CENTER.y) * zp;

  const captionOp = fade(e, 3400, 7000);
  const captionZoomedOp = fade(e, 8600, 11400);
  const selfLabelOp = fade(e, 8500, 11400);

  return (
    <div
      style={{
        width: "100%",
        maxWidth: 560,
        aspectRatio: "520 / 340",
        position: "relative",
        fontFamily: "var(--wg-font-sans)",
      }}
      aria-label="Demo: a message lands, the graph rewires, the delivery date shifts, then zooms out to the org graph"
      role="img"
    >
      {/* Chat bubbles — HTML for clean typography */}
      <ChatBubble opacity={chat1Op} top={8}>
        {t("demo.bubble1")}
      </ChatBubble>
      <ChatBubble opacity={chat2Op} top={54} accent>
        {t("demo.bubble2")}
      </ChatBubble>

      {/* SLA badge — flips from sage to amber */}
      <SlaBadge opacity={slaBeforeOp} tone="ok" label={t("demo.slaBefore")} />
      <SlaBadge opacity={slaAfterOp} tone="warn" label={t("demo.slaAfter")} />

      <svg
        viewBox="0 0 520 340"
        width="100%"
        height="100%"
        style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
        aria-hidden
      >
        {/* Peer nodes (org graph) — fade in during / after zoom */}
        {PEERS.map((p) => {
          const op = fade(e, p.inAt, 11400);
          return (
            <g key={p.key} opacity={op}>
              <rect
                x={p.x - p.w / 2}
                y={p.y - 12}
                width={p.w}
                height={24}
                rx={6}
                fill="var(--wg-surface-raised)"
                stroke="var(--wg-line)"
                strokeWidth={1}
              />
              <text
                x={p.x}
                y={p.y + 4}
                textAnchor="middle"
                fontSize={12}
                fontFamily="var(--wg-font-mono)"
                fill="var(--wg-ink-soft)"
              >
                {t(`demo.peer.${p.key}`)}
              </text>
            </g>
          );
        })}

        {/* Meta-graph edges between the central cluster and the peers */}
        {META_EDGES.map((me, i) => (
          <line
            key={`me-${i}`}
            x1={me.x1}
            y1={me.y1}
            x2={me.x2}
            y2={me.y2}
            stroke="var(--wg-ink-faint)"
            strokeWidth={1}
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={edgeOffset(e, me.inAt)}
            opacity={fade(e, me.inAt, 11400) * 0.8}
          />
        ))}

        {/* Main graph group — everything below this transform zooms together */}
        <g transform={`matrix(${s} 0 0 ${s} ${tx} ${ty})`}>
          {/* Straight edges — intake → clarify → plan → decide → deliver */}
          {NODES.slice(0, -1).map((n, i) => {
            const next = NODES[i + 1];
            const isDirectPD = n.key === "plan" && next.key === "decide";
            const inAt = n.inAt + 300;
            return (
              <line
                key={`e-${n.key}`}
                x1={n.cx + NODE_R}
                y1={n.cy}
                x2={next.cx - NODE_R}
                y2={next.cy}
                stroke="var(--wg-ink-faint)"
                strokeWidth={1.5}
                pathLength={100}
                strokeDasharray={100}
                strokeDashoffset={edgeOffset(e, inAt)}
                opacity={isDirectPD ? directOp : fade(e, inAt, 11400)}
                style={{ transition: "opacity 280ms ease-out" }}
              />
            );
          })}

          {/* Reroute edges — plan → compliance → decide */}
          <line
            x1={240 + 10}
            y1={200 - 10}
            x2={COMP_CX - 10}
            y2={COMP_CY + 10}
            stroke="var(--wg-accent)"
            strokeWidth={1.5}
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={edgeOffset(e, 5400)}
            opacity={compOp}
          />
          <line
            x1={COMP_CX + 10}
            y1={COMP_CY + 10}
            x2={330 - 10}
            y2={200 - 10}
            stroke="var(--wg-accent)"
            strokeWidth={1.5}
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={edgeOffset(e, 5700)}
            opacity={compOp}
          />

          {/* Stage nodes */}
          {NODES.map((n) => {
            const op = fade(e, n.inAt, 11400);
            const labelOp = fade(e, n.inAt, labelOutAt);
            return (
              <g key={n.key}>
                <g opacity={op}>
                  <circle
                    cx={n.cx}
                    cy={n.cy}
                    r={NODE_R}
                    fill="var(--wg-surface-raised)"
                    stroke="var(--wg-ink)"
                    strokeWidth={1.25}
                  />
                  <circle cx={n.cx} cy={n.cy} r={3} fill="var(--wg-accent)" />
                </g>
                <text
                  x={n.cx}
                  y={n.cy + NODE_R + 18}
                  textAnchor="middle"
                  fontSize={12}
                  fontFamily="var(--wg-font-mono)"
                  fill="var(--wg-ink-soft)"
                  opacity={labelOp}
                >
                  {t(`stages.${n.key}`)}
                </text>
              </g>
            );
          })}

          {/* Compliance node — spawns mid-loop */}
          <g opacity={compOp}>
            <circle
              cx={COMP_CX}
              cy={COMP_CY}
              r={NODE_R}
              fill="var(--wg-surface-raised)"
              stroke="var(--wg-accent)"
              strokeWidth={1.5}
            />
            <circle cx={COMP_CX} cy={COMP_CY} r={3} fill="var(--wg-accent)" />
            <text
              x={COMP_CX}
              y={COMP_CY - NODE_R - 8}
              textAnchor="middle"
              fontSize={12}
              fontFamily="var(--wg-font-mono)"
              fill="var(--wg-accent)"
              opacity={fade(e, 5100, labelOutAt)}
            >
              + {t("demo.extraNode")}
            </text>
          </g>
        </g>

        {/* "Stellar Drift" pill that tags your cluster after zoom-out */}
        <g opacity={selfLabelOp}>
          <rect
            x={ZOOM_TARGET.x - 45}
            y={ZOOM_TARGET.y + 32}
            width={90}
            height={22}
            rx={6}
            fill="var(--wg-accent-soft)"
            stroke="var(--wg-accent)"
            strokeWidth={1}
          />
          <text
            x={ZOOM_TARGET.x}
            y={ZOOM_TARGET.y + 47}
            textAnchor="middle"
            fontSize={11}
            fontFamily="var(--wg-font-mono)"
            fill="var(--wg-accent)"
          >
            {t("demo.selfLabel")}
          </text>
        </g>
      </svg>

      {/* Captions — primary pre-zoom, zoomed-out variant post-zoom */}
      <Caption opacity={captionOp}>{t("demo.caption")}</Caption>
      <Caption opacity={captionZoomedOp}>{t("demo.captionZoomed")}</Caption>
    </div>
  );
}

function Caption({
  children,
  opacity,
}: {
  children: React.ReactNode;
  opacity: number;
}) {
  return (
    <div
      style={{
        position: "absolute",
        bottom: -4,
        left: 0,
        right: 0,
        textAlign: "center",
        fontSize: 12,
        color: "var(--wg-ink-faint)",
        fontFamily: "var(--wg-font-mono)",
        letterSpacing: "0.02em",
        opacity,
        transition: "opacity 240ms ease-out",
        pointerEvents: "none",
      }}
    >
      {children}
    </div>
  );
}

function ChatBubble({
  children,
  opacity,
  top,
  accent,
}: {
  children: React.ReactNode;
  opacity: number;
  top: number;
  accent?: boolean;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top,
        right: 4,
        maxWidth: 260,
        padding: "6px 10px",
        background: accent ? "var(--wg-accent-soft)" : "var(--wg-surface-raised)",
        border: `1px solid ${accent ? "var(--wg-accent-ring)" : "var(--wg-line)"}`,
        borderRadius: "var(--wg-radius)",
        fontSize: 13,
        color: "var(--wg-ink)",
        opacity,
        transform: `translateY(${(1 - opacity) * 4}px)`,
        transition: "opacity 240ms ease-out, transform 240ms ease-out",
        pointerEvents: "none",
      }}
    >
      {children}
    </div>
  );
}

function SlaBadge({
  opacity,
  tone,
  label,
}: {
  opacity: number;
  tone: "ok" | "warn";
  label: string;
}) {
  const color = tone === "ok" ? "var(--wg-ok)" : "var(--wg-amber)";
  const bg =
    tone === "ok" ? "rgba(22, 163, 74, 0.08)" : "var(--wg-amber-soft)";
  return (
    <div
      style={{
        position: "absolute",
        bottom: 28,
        right: 16,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 8px",
        background: bg,
        border: `1px solid ${color}`,
        borderRadius: "var(--wg-radius)",
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        color,
        opacity,
        transition: "opacity 240ms ease-out",
        pointerEvents: "none",
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: 5,
          height: 5,
          borderRadius: "50%",
          background: color,
        }}
      />
      {label}
    </div>
  );
}
