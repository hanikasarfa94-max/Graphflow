"use client";

import type { ProjectState } from "@/lib/api";
import type { Stage } from "@/lib/stage";

const STAGE_ROWS: {
  key: Stage;
  label: string;
  count: (s: ProjectState) => number;
}[] = [
  { key: "intake", label: "intake", count: () => 1 },
  {
    key: "clarify",
    label: "clarify",
    count: (s) => s.clarifications.length,
  },
  {
    key: "plan",
    label: "plan",
    count: (s) => s.plan.tasks.length,
  },
  {
    key: "conflict",
    label: "conflict",
    count: (s) => s.conflicts.filter((c) => c.status === "open").length,
  },
  {
    key: "delivery",
    label: "delivery",
    count: (s) => (s.delivery ? 1 : 0),
  },
];

export function GraphSidebar({
  state,
  stage,
  activeAgent,
}: {
  state: ProjectState;
  stage: Stage;
  activeAgent: string | null;
}) {
  return (
    <nav
      data-testid="graph-river"
      aria-label="workflow graph"
      style={{
        padding: "20px 18px",
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        letterSpacing: "0.02em",
      }}
    >
      <div
        style={{
          textTransform: "uppercase",
          color: "var(--wg-ink-soft)",
          marginBottom: 18,
          letterSpacing: "0.12em",
        }}
      >
        Graph
      </div>

      <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {STAGE_ROWS.map((row, idx) => {
          const count = row.count(state);
          const isActive = row.key === stage;
          const pulsing =
            isActive && activeAgent !== null && row.key !== "done";
          return (
            <li
              key={row.key}
              data-testid={`river-row-${row.key}`}
              data-active={isActive ? "true" : undefined}
              style={{
                display: "grid",
                gridTemplateColumns: "72px 1fr",
                alignItems: "center",
                padding: "8px 0",
                color: isActive ? "var(--wg-ink)" : "var(--wg-ink-soft)",
                fontWeight: isActive ? 600 : 400,
              }}
            >
              <span style={{ whiteSpace: "nowrap" }}>{row.label}</span>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  position: "relative",
                }}
              >
                <RiverDot active={isActive} pulsing={pulsing} />
                {count > 0 ? (
                  <span
                    style={{
                      color: "var(--wg-ink-soft)",
                      fontSize: 10,
                    }}
                  >
                    ×{count}
                  </span>
                ) : null}
              </div>
              {idx < STAGE_ROWS.length - 1 ? (
                <span
                  aria-hidden
                  style={{
                    gridColumn: "2 / 3",
                    width: 1,
                    height: 14,
                    marginLeft: 3,
                    background: "var(--wg-line)",
                    display: "block",
                  }}
                />
              ) : null}
            </li>
          );
        })}
      </ol>

      <GraphEntities state={state} />
    </nav>
  );
}

function RiverDot({
  active,
  pulsing,
}: {
  active: boolean;
  pulsing: boolean;
}) {
  return (
    <span
      className={pulsing ? "wg-pulse" : undefined}
      aria-hidden
      style={{
        width: 8,
        height: 8,
        borderRadius: 50,
        background: active ? "var(--wg-accent)" : "var(--wg-line)",
        border: active ? "none" : "1px solid var(--wg-line)",
        flexShrink: 0,
        transition: "background var(--wg-motion-fast)",
      }}
    />
  );
}

function GraphEntities({ state }: { state: ProjectState }) {
  const rows = [
    { label: "deliverables", n: state.graph.deliverables.length },
    { label: "constraints", n: state.graph.constraints.length },
    { label: "risks", n: state.graph.risks.length },
    { label: "tasks", n: state.plan.tasks.length },
    { label: "decisions", n: state.decisions.length },
  ];
  return (
    <div
      style={{
        marginTop: 28,
        paddingTop: 16,
        borderTop: "1px solid var(--wg-line)",
        display: "grid",
        gridTemplateColumns: "1fr auto",
        rowGap: 4,
        fontSize: 11,
      }}
    >
      {rows.map((r) => (
        <div key={r.label} style={{ display: "contents" }}>
          <span style={{ color: "var(--wg-ink-soft)" }}>{r.label}</span>
          <span style={{ color: r.n > 0 ? "var(--wg-ink)" : "var(--wg-ink-faint)" }}>
            {r.n}
          </span>
        </div>
      ))}
    </div>
  );
}
