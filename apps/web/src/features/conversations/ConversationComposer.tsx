"use client";

// ConversationComposer — bottom-of-pane composer for posting messages
// into the active conversation.
//
// Phase D scaffold (2026-05-13). Plain controlled textarea + Send
// button. No slash-commands, no @mention picker, no attachment row in
// the scaffold — those come back in Phase D.2 once the wire contract
// for attachments stabilizes.
//
// Phase D.2 swap-in: replace the no-op `onSend` plumbing in the parent
// with a real mutator backed by
//   `POST /api/conversations/:conversationId/messages`
// and append the returned message to the stream on success.

import { useState } from "react";

import { Button, Text } from "@/components/ui";

export function ConversationComposer({
  conversationId,
  onSend,
}: {
  conversationId: string;
  onSend: (body: string) => Promise<void> | void;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);

  const canSend = value.trim().length > 0 && !sending;

  async function handleSend() {
    if (!canSend) return;
    setSending(true);
    try {
      await onSend(value.trim());
      setValue("");
    } finally {
      setSending(false);
    }
  }

  return (
    <footer
      style={{
        borderTop: "1px solid var(--wg-line)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: "var(--wg-surface)",
      }}
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={
          // TODO(i18n): shellV062.conversations.composer.placeholder
          "Write a message…"
        }
        rows={3}
        data-conversation-id={conversationId}
        style={{
          width: "100%",
          resize: "vertical",
          minHeight: 64,
          padding: "10px 12px",
          fontSize: "var(--wg-fs-body)",
          fontFamily: "var(--wg-font-sans)",
          lineHeight: "var(--wg-lh-normal)",
          color: "var(--wg-ink)",
          background: "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          outline: "none",
        }}
        onKeyDown={(e) => {
          // Cmd/Ctrl+Enter sends, matching the My AI composer convention.
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            void handleSend();
          }
        }}
      />
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <Text variant="caption" muted>
          {/* TODO(i18n): shellV062.conversations.composer.hint */}
          ⌘/Ctrl + Enter to send
        </Text>
        <Button variant="primary" onClick={handleSend} disabled={!canSend}>
          {/* TODO(i18n): shellV062.conversations.composer.send */}
          {sending ? "Sending…" : "Send"}
        </Button>
      </div>
    </footer>
  );
}
