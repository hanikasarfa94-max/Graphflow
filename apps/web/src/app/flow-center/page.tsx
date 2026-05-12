// /flow-center — Flow Center, the doctrine-load-bearing surface.
//
// Phase A.1 scaffold (2026-05-12). The full Flow Center with
// FlowTable + FlowDrawer + MemoryPromptDrawer + MemoryReviewDrawer
// arrives in Phase C per BUILD-v062.md.
//
// Doctrine — flow acceptance does NOT auto-accept memory. Each flow
// response returns a memory_candidate_prompt with actions
// [review, skip, later]. Skip is reversible via
// /api/flow-responses/:id/generate-memory-candidate.
//
// API surface (Phase B):
//   POST  /api/flow-requests/draft
//   PATCH /api/flow-requests/:id/attachments
//   POST  /api/flow-requests/:id/send
//   POST  /api/flow-requests/:id/respond
//   POST  /api/flow-responses/:id/generate-memory-candidate
//
// FlowRequestType enum: "confirm" | "feedback" | "review"
//   | "clarification" | "handoff" | "accept_task" | "delegate" | "approval"

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function FlowCenterPage() {
  await requireUser("/flow-center");

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

      <Card title="Coming next">
        <Text variant="body" muted>
          Four-tile metric strip (Needs me / Waiting / Awaiting Membrane /
          Completed), FlowTable, FlowDrawer, and MemoryReviewDrawer land in
          Phase C of <code>BUILD-v062.md</code>. This is the doctrine
          surface — built first after the shell.
        </Text>
      </Card>
    </main>
  );
}
