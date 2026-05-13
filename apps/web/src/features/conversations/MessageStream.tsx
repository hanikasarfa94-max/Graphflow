"use client";

// MessageStream — scrolling message list for the active conversation.
//
// Phase RW-4 (2026-05-13): renders the live message rows returned by
// GET /api/conversations/:id. Each row is a real MessageRow shape
// from StreamService.list_messages (author_id, author_username,
// body, created_at, kind, linked_id). No mock messages.
//
// Display name resolution: we render `author_username` (the BE
// already resolved UserRow.username for each author). When username
// is null (system messages, edge agent posts), we render an
// abbreviated user_id so the row never displays an empty author.

import { useTranslations } from "next-intl";

import { Text } from "@/components/ui";

import type { ConversationMessage } from "./types";

export function MessageStream({
  messages,
}: {
  messages: ConversationMessage[];
}) {
  const t = useTranslations("shellV062.conversations.stream");

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
          {t("empty")}
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
  const author =
    msg.author_username || `user:${msg.author_id.slice(0, 8)}`;
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
          {author}
        </Text>
        <Text variant="caption" muted>
          {formatTime(msg.created_at)}
        </Text>
        {msg.kind && msg.kind !== "text" ? (
          <Text variant="caption" muted>
            · {msg.kind}
          </Text>
        ) : null}
      </div>
      <Text variant="body" as="p" style={{ whiteSpace: "pre-wrap" }}>
        {msg.body}
      </Text>
    </article>
  );
}

// All visible timestamps funnel through lib/time so SSR + CSR render
// the same Asia/Shanghai string (M1.1 invariant).
import { formatIso as _formatIso } from "@/lib/time";
function formatTime(iso: string): string {
  return _formatIso(iso);
}
