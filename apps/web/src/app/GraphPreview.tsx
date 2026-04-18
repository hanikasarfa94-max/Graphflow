"use client";

import { useEffect, useState } from "react";

// Lightweight animated preview of the canonical WorkGraph shape. Nodes
// fade in one at a time, the "active" pulse walks the chain, and edges
// animate a flowing dash so the graph feels alive even before the user
// kicks off a real run. No data, no API — purely decorative.

type Stage = "intake" | "clarify" | "plan" | "decide" | "deliver";

const STAGES: { id: Stage; label: string; row: number; col: number }[] = [
  { id: "intake", label: "Intake", row: 0, col: 0 },
  { id: "clarify", label: "Clarify", row: 1, col: 1 },
  { id: "plan", label: "Plan", row: 2, col: 0 },
  { id: "decide", label: "Decide", row: 3, col: 1 },
  { id: "deliver", label: "Deliver", row: 4, col: 0 },
];

const EDGES: [Stage, Stage][] = [
  ["intake", "clarify"],
  ["clarify", "plan"],
  ["plan", "decide"],
  ["decide", "deliver"],
];

const WIDTH = 240;
const HEIGHT = 420;
const PAD_X = 32;
const ROW_GAP = (HEIGHT - 80) / (STAGES.length - 1);
const COL_LEFT = PAD_X + 20;
const COL_RIGHT = WIDTH - PAD_X - 20;
const NODE_RX = 42;
const NODE_RY = 16;

function nodeXY(s: { row: number; col: number }) {
  return {
    x: s.col === 0 ? COL_LEFT : COL_RIGHT,
    y: 40 + s.row * ROW_GAP,
  };
}

export function GraphPreview() {
  const [active, setActive] = useState<Stage>("intake");

  useEffect(() => {
    let i = 0;
    const t = setInterval(() => {
      i = (i + 1) % STAGES.length;
      setActive(STAGES[i].id);
    }, 1400);
    return () => clearInterval(t);
  }, []);

  return (
    <div
      aria-hidden
      style={{
        width: "100%",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        padding: "24px 0",
      }}
    >
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ display: "block" }}
      >
        {/* Edges */}
        {EDGES.map(([from, to], i) => {
          const a = STAGES.find((s) => s.id === from)!;
          const b = STAGES.find((s) => s.id === to)!;
          const p1 = nodeXY(a);
          const p2 = nodeXY(b);
          const activeIdx = STAGES.findIndex((s) => s.id === active);
          const edgeActive = activeIdx === i + 1;
          return (
            <line
              key={`${from}-${to}`}
              x1={p1.x}
              y1={p1.y + NODE_RY}
              x2={p2.x}
              y2={p2.y - NODE_RY}
              stroke={edgeActive ? "var(--wg-accent)" : "var(--wg-line)"}
              strokeWidth={edgeActive ? 1.75 : 1}
              className={edgeActive ? "wg-edge-flow" : undefined}
              style={{
                transition: "stroke 240ms ease-out",
                opacity: 0,
                animation: `wg-fade-in 360ms ease-out ${180 + i * 120}ms forwards`,
              }}
            />
          );
        })}

        {/* Nodes */}
        {STAGES.map((s, i) => {
          const { x, y } = nodeXY(s);
          const isActive = s.id === active;
          return (
            <g
              key={s.id}
              style={{
                opacity: 0,
                animation: `wg-fade-in 300ms ease-out ${i * 120}ms forwards`,
              }}
            >
              <rect
                x={x - NODE_RX}
                y={y - NODE_RY}
                rx={6}
                width={NODE_RX * 2}
                height={NODE_RY * 2}
                fill={
                  isActive
                    ? "var(--wg-accent-soft)"
                    : "var(--wg-surface-raised)"
                }
                stroke={isActive ? "var(--wg-accent)" : "var(--wg-line)"}
                strokeWidth={isActive ? 1.25 : 1}
                style={{ transition: "all 240ms ease-out" }}
              />
              <circle
                cx={x - NODE_RX + 10}
                cy={y}
                r={2.5}
                fill={isActive ? "var(--wg-accent)" : "var(--wg-ink-faint)"}
                style={{ transition: "fill 240ms ease-out" }}
              />
              <text
                x={x - NODE_RX + 20}
                y={y + 4}
                fontSize={11}
                fontFamily="var(--wg-font-mono)"
                fill={isActive ? "var(--wg-ink)" : "var(--wg-ink-soft)"}
              >
                {s.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
