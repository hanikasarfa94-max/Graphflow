// /conversations/[id] — deep-link to a specific conversation.
//
// Phase D scaffold (2026-05-13). Thin server wrapper: requires auth,
// then renders the client-side `<Conversations />` feature with the
// requested conversation pre-selected. The client component owns the
// detail fetch (Phase D.2 wires
//   `GET /api/conversations/:id`
// against the live router in
//   apps/api/src/workgraph_api/routers/conversations.py).
//
// We deliberately don't pre-fetch + render server-side here — the
// list pane is interactive (selection state, mark-as-read, etc.) and
// the deep-link is just a starting point. Treating the URL as
// `initialSelectedId` keeps the page reactive once the user clicks
// around without forcing a server roundtrip per selection.

import { Conversations } from "@/features/conversations/Conversations";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ConversationDetailPage({
  params,
}: {
  // Next 15 / App Router — params is a Promise on dynamic routes.
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/conversations/${id}`);
  return <Conversations initialSelectedId={id} />;
}
