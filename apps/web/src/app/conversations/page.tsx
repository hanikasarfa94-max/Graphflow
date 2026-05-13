// /conversations — index of conversations (DMs + Rooms + Topics).
//
// Phase D scaffold (2026-05-13). Replaces the Phase A.1 placeholder.
// Thin server wrapper: requires auth, then renders the client-side
// `<Conversations />` feature.
//
// Doctrine invariant — a topic must never appear in both Recent and
// Active Topics. The server partitions the response in
// `apps/api/src/workgraph_api/routers/conversations.py` and the FE
// asserts the same defensively in ConversationList.
//
// API surface (Phase B.1 live, Phase B.2 fills in stubs):
//   GET  /api/conversations?scope_id=...
//   GET  /api/conversations/:id
//   POST /api/conversations/:id/messages
//   POST /api/topics                            (B.1 stub)
//   PATCH /api/topics/:id/status                (B.1 stub)
//   POST /api/topics/:id/propose-closure        (B.1 stub)
//
// ConversationType enum: "direct" | "room" | "topic"

import { Conversations } from "@/features/conversations/Conversations";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ConversationsIndexPage() {
  await requireUser("/conversations");
  return <Conversations />;
}
