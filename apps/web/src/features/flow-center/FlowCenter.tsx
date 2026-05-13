"use client";

// FlowCenter — the doctrine-load-bearing surface for v0.6.2.
//
// Phase C scaffold (2026-05-13). Renders the Flow Center page body:
// PageHeader + 4-tile metric strip + FlowTable. The right rail (per
// DESIGN_LOCK.md "Right rail follows shared spine") is deferred to a
// follow-up scaffold ticket.
//
// Doctrine surface — every flow response that returns a
// memory_candidate_prompt routes the user through MemoryPromptDrawer,
// and acceptance of a memory atom happens in MemoryReviewDrawer with
// server-side authority. Neither auto-accepts memory.
//
// Data plumbing is mocked for Phase C; Phase B.2 lands the real
// `/api/flow-requests/summary` (metric counts) + `/api/flow-requests?...`
// (table rows) endpoints. Search for `// TODO(phase-b.2)` to find every
// mock point.

import { Card, Metric, PageHeader, Text } from "@/components/ui";

import { FlowTable } from "./FlowTable";

// Stubbed counts. TODO(phase-b.2): replace with
//   `GET /api/flow-requests/summary?scope_id=...`
// returning { needs_me, waiting, awaiting_membrane, completed }.
function useFlowCenterSummary() {
  return {
    needsMe: 0,
    waiting: 0,
    awaitingMembrane: 0,
    completed: 0,
  };
}

export function FlowCenter() {
  const summary = useFlowCenterSummary();

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Flow Center"
        title="Flow Center"
        subtitle="Confirmations, reviews, handoffs, approvals. The control room for organizational state-change. Not a todo list."
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <Metric value={summary.needsMe} label="Needs me" tone="accent" />
        <Metric value={summary.waiting} label="Waiting on others" />
        <Metric
          value={summary.awaitingMembrane}
          label="Awaiting Membrane"
          tone="amber"
        />
        <Metric value={summary.completed} label="Recently completed" />
      </div>

      <Card title="Flow packets" flush>
        <FlowTable />
      </Card>

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        Memory crystallization is a separate decision.
      </Text>
    </main>
  );
}
