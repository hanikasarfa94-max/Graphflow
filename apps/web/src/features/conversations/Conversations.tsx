"use client";

// Conversations — the v0.6.2 IA's coordination surface.
//
// Phase D scaffold (2026-05-13). One of the five primary surfaces per
// DESIGN_LOCK.md (My AI / Conversations / Tasks / Documents / Flow).
// Renders a two-pane layout:
//
//   ConversationList (left, 320px fixed) | ConversationShell (right, flex)
//
// The page-level PageHeader sits above both panes. Selection state is
// owned here and threaded into both panes — the list reports clicks,
// the shell renders the active detail. Deep linking via
// `/conversations/[id]` is handled by the page wrapper, which passes
// `initialSelectedId` through.
//
// Doctrine reminders embedded in this scaffold:
//   * Recent (DMs + Rooms) and Active Topics are visually separate.
//   * INVARIANT_TESTS.md §"Topic deduplication": a conversation id
//     appears in exactly one group. ConversationList enforces this
//     defensively in addition to the server-side partition.
//   * Per DESIGN_LOCK.md #4 AI Assistance returns proposals only;
//     all proposal interactions route through DrawerHost.

import { useState } from "react";

import { PageHeader } from "@/components/ui";

import { ConversationList } from "./ConversationList";
import { ConversationShell } from "./ConversationShell";
import type { ConversationIndexResponse } from "./types";

export function Conversations({
  data,
  viewerUserId,
  initialSelectedId = null,
}: {
  // Phase RW-1.2 — data is fetched server-side in page.tsx via
  // `GET /api/conversations` and passed in as a prop. There is no
  // mock fallback; an empty server response renders an empty UI.
  data: ConversationIndexResponse;
  // Phase RW-4 — viewer id flows through so the DM rail can resolve
  // the "other" participant without inferring from local context.
  viewerUserId: string;
  initialSelectedId?: string | null;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId);

  return (
    <main
      style={{
        // Full-bleed two-pane layout — Conversations is denser than the
        // other surfaces, so we drop the centered max-width that My AI
        // and Tasks use and let the panes fill the viewport.
        height: "100%",
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <div style={{ padding: "24px 28px 12px" }}>
        <PageHeader
          // TODO(i18n): shellV062.conversations.pageHeader.*
          kicker="Conversations"
          title="Conversations"
          subtitle="Direct messages, rooms, and topics. The shared structure where coordination breaks open and resolves."
        />
      </div>

      <div
        style={{
          flex: 1,
          display: "flex",
          minHeight: 0,
          borderTop: "1px solid var(--wg-line)",
        }}
      >
        <ConversationList
          data={data}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <ConversationShell
          selectedId={selectedId}
          viewerUserId={viewerUserId}
        />
      </div>
    </main>
  );
}
