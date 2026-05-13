// /flow-center — Flow Center, the doctrine-load-bearing surface.
//
// Phase C scaffold (2026-05-13). The full FlowCenter feature body
// lives at `apps/web/src/features/flow-center/FlowCenter.tsx`; this
// route file is a thin server wrapper that requires auth and renders
// the client-side feature.
//
// Doctrine — flow acceptance does NOT auto-accept memory. Each flow
// response routes through MemoryPromptDrawer with [review, skip,
// later] actions. Skip is reversible via
// `/api/flow-responses/:id/generate-memory-candidate`.
//
// API surface (Phase B.2):
//   GET   /api/flow-requests/summary
//   GET   /api/flow-requests?scope_id=...
//   GET   /api/flow-requests/:id
//   POST  /api/flow-requests/draft
//   PATCH /api/flow-requests/:id/attachments
//   POST  /api/flow-requests/:id/send
//   POST  /api/flow-requests/:id/respond
//   POST  /api/flow-responses/:id/generate-memory-candidate
//   GET   /api/memory-candidates/:id
//   POST  /api/memory-candidates/:id/{accept,defer,reject,reopen}
//
// FlowRequestType enum: "confirm" | "feedback" | "review"
//   | "clarification" | "handoff" | "accept_task" | "delegate" | "approval"

import { FlowCenter } from "@/features/flow-center/FlowCenter";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function FlowCenterPage() {
  await requireUser("/flow-center");
  return <FlowCenter />;
}
