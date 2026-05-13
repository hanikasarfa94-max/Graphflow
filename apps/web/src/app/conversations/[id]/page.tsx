// /conversations/[id] — deep-link to a specific conversation.
//
// Phase RW-1.2 wiring (2026-05-13): same server-side load as the
// index, with the requested id pre-selected. The detail-pane body
// stays minimal in RW-1; the `GET /api/conversations/:id` fetcher
// for the right pane lands in RW-3.

import { Conversations } from "@/features/conversations/Conversations";
import type { ConversationIndexResponse } from "@/features/conversations/types";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

async function loadConversations(): Promise<ConversationIndexResponse> {
  try {
    return await serverFetch<ConversationIndexResponse>("/api/conversations");
  } catch {
    return { recent: [], active_topics: [] };
  }
}

export default async function ConversationDetailPage({
  params,
}: {
  // Next 15 / App Router — params is a Promise on dynamic routes.
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/conversations/${id}`);
  const data = await loadConversations();
  return (
    <Conversations
      data={data}
      viewerUserId={user.id}
      initialSelectedId={id}
    />
  );
}
