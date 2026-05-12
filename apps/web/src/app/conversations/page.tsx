// /conversations — index of conversations (DMs + Rooms + Topics).
//
// Phase A.1 scaffold (2026-05-12). The full ConversationIndex with
// Recent (DMs+Rooms) and Active Topics (separate, dedup invariant)
// arrives in Phase D per BUILD-v062.md.
//
// Doctrine invariant — a topic must never appear in both Recent and
// Active Topics. INVARIANT_TESTS.md §"Topic deduplication".
//
// API surface (Phase B):
//   GET /api/conversations?scope_id=...
//   GET /api/conversations/:id
//   POST /api/conversations/:id/messages
//
// ConversationType enum: "direct" | "room" | "topic"

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ConversationsIndexPage() {
  await requireUser("/conversations");

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Conversations"
        title="Conversations"
        subtitle="Direct messages, rooms, and topics. The shared structure where coordination breaks open and resolves."
      />

      <Card title="Coming next">
        <Text variant="body" muted>
          The DM + Room + Topic index with Active Topics separation lands in
          Phase D of <code>BUILD-v062.md</code>.
        </Text>
      </Card>
    </main>
  );
}
