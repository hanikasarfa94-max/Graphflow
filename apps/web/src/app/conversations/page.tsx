// /conversations — index of conversations (DMs + Rooms + Topics).
//
// Phase RW-1.2 wiring (2026-05-13): pulls real data from
// GET /api/conversations server-side and passes it into the client
// feature component. The mock useConversations() hook has been
// removed; an empty live response renders honest empty states rather
// than fabricated rows.
//
// Doctrine invariant — a topic must never appear in both Recent and
// Active Topics. The server partitions the response; ConversationList
// asserts the same defensively at render time.
//
// API surface:
//   GET  /api/conversations?scope_id=...                ← live (RW-1.2)
//   GET  /api/conversations/:id                         ← Phase RW-3
//   POST /api/conversations/:id/messages                ← Phase RW-3
//   POST /api/topics                                    ← Phase B.3 stub
//   PATCH /api/topics/:id/status                        ← Phase B.3 stub
//   POST /api/topics/:id/propose-closure                ← Phase B.3 stub
//
// ConversationType enum: "direct" | "room" | "topic"

import { Conversations } from "@/features/conversations/Conversations";
import type { ConversationIndexResponse } from "@/features/conversations/types";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

async function loadConversations(): Promise<ConversationIndexResponse> {
  try {
    return await serverFetch<ConversationIndexResponse>("/api/conversations");
  } catch {
    // Transient API failure → render empty state, not crash.
    return { recent: [], active_topics: [] };
  }
}

export default async function ConversationsIndexPage() {
  await requireUser("/conversations");
  const data = await loadConversations();
  return <Conversations data={data} />;
}
