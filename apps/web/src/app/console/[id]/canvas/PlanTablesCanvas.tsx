"use client";

import { useState } from "react";

import type { ProjectState } from "@/lib/api";
import { formatIso } from "@/lib/time";

type Tab = "tasks" | "risks" | "decisions" | "conflicts";

export function PlanTablesCanvas({
  projectId,
  state,
}: {
  projectId: string;
  state: ProjectState;
}) {
  const [tab, setTab] = useState<Tab>("tasks");
  const [generating, setGenerating] = useState(false);

  async function generateDelivery() {
    setGenerating(true);
    try {
      await fetch(`/api/projects/${projectId}/delivery`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div
      data-testid="canvas-tables"
      style={{ padding: "24px 32px", maxWidth: 980, margin: "0 auto" }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
            {state.project.title}
          </h2>
          <p
            style={{
              margin: "4px 0 0",
              color: "var(--wg-ink-soft)",
              fontSize: 13,
            }}
          >
            {state.plan.tasks.length} task
            {state.plan.tasks.length === 1 ? "" : "s"} · {state.graph.risks.length}{" "}
            risks · {state.decisions.length} decisions
          </p>
        </div>
        {state.plan.tasks.length > 0 && !state.delivery ? (
          <button
            data-testid="generate-delivery-from-plan"
            onClick={generateDelivery}
            disabled={generating}
            style={{
              padding: "8px 14px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              fontWeight: 600,
              fontSize: 13,
              cursor: generating ? "wait" : "pointer",
            }}
          >
            {generating ? "Generating…" : "Generate delivery"}
          </button>
        ) : null}
      </header>

      <div
        role="tablist"
        style={{
          display: "flex",
          gap: 2,
          marginBottom: 16,
          borderBottom: "1px solid var(--wg-line)",
        }}
      >
        {(["tasks", "risks", "decisions", "conflicts"] as Tab[]).map((k) => {
          const n =
            k === "tasks"
              ? state.plan.tasks.length
              : k === "risks"
                ? state.graph.risks.length
                : k === "decisions"
                  ? state.decisions.length
                  : state.conflicts.length;
          const isActive = tab === k;
          return (
            <button
              key={k}
              role="tab"
              data-testid={`canvas-tab-${k}`}
              aria-selected={isActive}
              onClick={() => setTab(k)}
              style={{
                padding: "10px 14px",
                border: "none",
                background: "transparent",
                fontFamily: "var(--wg-font-sans)",
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? "var(--wg-ink)" : "var(--wg-ink-soft)",
                borderBottom: isActive
                  ? "2px solid var(--wg-accent)"
                  : "2px solid transparent",
                marginBottom: -1,
                cursor: "pointer",
              }}
            >
              {k} <span style={{ color: "var(--wg-ink-faint)" }}>{n}</span>
            </button>
          );
        })}
      </div>

      {tab === "tasks" && <TasksTable state={state} />}
      {tab === "risks" && <RisksTable state={state} />}
      {tab === "decisions" && <DecisionsTable state={state} />}
      {tab === "conflicts" && <ConflictsTable state={state} />}
    </div>
  );
}

function DataTable({
  headers,
  rows,
  empty,
}: {
  headers: string[];
  rows: React.ReactNode[][];
  empty: string;
}) {
  if (rows.length === 0) {
    return (
      <div
        style={{
          padding: 20,
          color: "var(--wg-ink-soft)",
          fontSize: 13,
          textAlign: "center",
          border: "1px dashed var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        {empty}
      </div>
    );
  }
  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontSize: 13,
      }}
    >
      <thead>
        <tr
          style={{
            textAlign: "left",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          {headers.map((h) => (
            <th key={h} style={{ padding: "8px 10px", fontWeight: 600 }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr
            key={i}
            data-testid="table-row"
            style={{
              borderTop: "1px solid var(--wg-line)",
            }}
          >
            {r.map((cell, j) => (
              <td
                key={j}
                style={{
                  padding: "10px",
                  verticalAlign: "top",
                }}
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TasksTable({ state }: { state: ProjectState }) {
  const headers = ["ID", "Title", "Role", "Hours", "Status"];
  const rows = state.plan.tasks.map((t) => [
    <Mono key="i">{t.id.slice(0, 8)}</Mono>,
    <span key="t">{t.title}</span>,
    <Mono key="r">{t.assignee_role ?? "—"}</Mono>,
    <Mono key="h">{t.estimate_hours ?? "—"}</Mono>,
    <StatusChip key="s" status={t.status} />,
  ]);
  return (
    <DataTable headers={headers} rows={rows} empty="No tasks yet." />
  );
}

function RisksTable({ state }: { state: ProjectState }) {
  const headers = ["Title", "Severity", "Status", "Content"];
  const rows = state.graph.risks.map((r) => [
    <span key="t">{r.title}</span>,
    <SeverityChip key="s" severity={r.severity} />,
    <Mono key="st">{r.status}</Mono>,
    <span key="c" style={{ color: "var(--wg-ink-soft)" }}>
      {r.content}
    </span>,
  ]);
  return <DataTable headers={headers} rows={rows} empty="No risks raised." />;
}

function DecisionsTable({ state }: { state: ProjectState }) {
  const headers = ["When", "Rationale", "Outcome"];
  const rows = state.decisions.map((d) => [
    <Mono key="w">
      {d.created_at ? formatIso(d.created_at) : "—"}
    </Mono>,
    <span key="r">{d.rationale || d.custom_text || "—"}</span>,
    <OutcomeChip key="o" outcome={d.apply_outcome ?? "pending"} />,
  ]);
  return (
    <DataTable headers={headers} rows={rows} empty="No decisions recorded." />
  );
}

function ConflictsTable({ state }: { state: ProjectState }) {
  const headers = ["Rule", "Severity", "Status", "Summary"];
  const rows = state.conflicts.map((c) => [
    <Mono key="r">{c.rule}</Mono>,
    <SeverityChip key="s" severity={c.severity} />,
    <Mono key="st">{c.status}</Mono>,
    <span key="sm" style={{ color: "var(--wg-ink-soft)" }}>
      {c.summary}
    </span>,
  ]);
  return <DataTable headers={headers} rows={rows} empty="No conflicts." />;
}

function Mono({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 12,
        color: "var(--wg-ink-soft)",
      }}
    >
      {children}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  return (
    <span
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 10,
        border: "1px solid var(--wg-line)",
        color: "var(--wg-ink-soft)",
      }}
    >
      {status}
    </span>
  );
}

function SeverityChip({ severity }: { severity: string }) {
  const color =
    severity === "critical" || severity === "high"
      ? "var(--wg-accent)"
      : severity === "medium"
        ? "var(--wg-amber)"
        : "var(--wg-ink-soft)";
  return (
    <span
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 10,
        border: `1px solid ${color}`,
        color,
      }}
    >
      {severity}
    </span>
  );
}

function OutcomeChip({ outcome }: { outcome: string }) {
  const color =
    outcome === "ok"
      ? "var(--wg-ok)"
      : outcome === "failed"
        ? "var(--wg-accent)"
        : outcome === "partial" || outcome === "pending"
          ? "var(--wg-amber)"
          : "var(--wg-ink-soft)";
  return (
    <span
      style={{
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        padding: "2px 8px",
        borderRadius: 10,
        background: "transparent",
        border: `1px solid ${color}`,
        color,
      }}
    >
      {outcome}
    </span>
  );
}
