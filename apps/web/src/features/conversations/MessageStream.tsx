"use client";

// MessageStream — scrolling message list for the active conversation.
//
// Phase D scaffold (2026-05-13). Renders the messages provided in the
// ConversationDetail payload. The stream owns scrolling + rendering
// only; posting belongs to ConversationComposer.
//
// Phase D.2 swap-in: load messages from
//   `GET /api/conversations/:conversationId`
// (which already includes initial `messages`) and append via SSE / WS
// as new ones arrive. For the scaffold the parent passes the messages
// down so the component stays pure.

import { Text } from "@/components/ui";

import type { ConversationMessage } from "./types";

export function MessageStream({
  messages,
}: {
  messages: ConversationMessage[];
}) {
  if (messages.length === 0) {
    return (
      <div
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 20,
        }}
      >
        <Text variant="body" muted>
          {/* TODO(i18n): shellV062.conversations.stream.empty */}
          No messages yet. Start the conversation below.
        </Text>
      </div>
    );
  }

  return (
    <div
      style={{
        flex: 1,
        overflowY: "auto",
        padding: "20px",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        background: "var(--wg-surface)",
      }}
    >
      {messages.map((msg) => (
        <MessageRow key={msg.id} msg={msg} />
      ))}
    </div>
  );
}

function MessageRow({ msg }: { msg: ConversationMessage }) {
  return (
    <article
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "10px 12px",
        border: "1px solid var(--wg-line-soft)",
        borderRadius: "var(--wg-radius)",
        background: "var(--wg-surface-raised)",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <Text variant="body" style={{ fontWeight: 600 }}>
          {msg.author.display_name}
        </Text>
        <Text variant="caption" muted>
          {formatTime(msg.posted_at)}
        </Text>
      </div>
      <Text variant="body" as="p" style={{ whiteSpace: "pre-wrap" }}>
        {msg.body}
      </Text>
    </article>
  );
}

// All visible timestamps funnel through lib/time so SSR + CSR render
// the same Asia/Shanghai string (avoids React hydration warnings).
import { formatIso as _formatIso } from "@/lib/time";
function formatTime(iso: string): string {
  return _formatIso(iso);
}
