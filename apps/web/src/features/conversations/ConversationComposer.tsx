"use client";

// ConversationComposer — bottom-of-pane composer for posting messages
// into the active conversation.
//
// Phase RW-5 (2026-05-13): real POST. The caller (ConversationShell)
// wires `onSend(body) → Promise<SendResult>` against
// `POST /api/conversations/:id/messages` and refetches detail on
// success. The composer renders three states:
//
//   1. Enabled — direct + room conversations, default.
//   2. Disabled — topic conversations (or any caller-specified
//      disabledReason). The textarea + Send button are both inert
//      and an honest "not wired" line explains why.
//   3. Error — last send failed with a typed error kind. The
//      bilingual message renders inline above the Send button.
//
// No optimistic state: the composer doesn't append to the stream
// itself. The shell's refetch is what makes the new message visible,
// sourced from the server's authoritative response.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";

import type { SendResult } from "./conversationActions";

export function ConversationComposer({
  conversationId,
  onSend,
  disabledReasonI18nKey,
}: {
  conversationId: string;
  onSend: (body: string) => Promise<SendResult>;
  // When set, the composer is locked. The string is an i18n key,
  // resolved via the global `useTranslations()` root so the caller
  // can point at any locale-resolvable key.
  disabledReasonI18nKey?: string | null;
}) {
  const t = useTranslations();
  const composerT = useTranslations("shellV062.conversations.composer");
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const [errorKey, setErrorKey] = useState<SendResult["error"] | null>(null);

  const lockedReason = disabledReasonI18nKey
    ? t(disabledReasonI18nKey as Parameters<typeof t>[0])
    : null;
  const locked = lockedReason !== null;
  const canSend = !locked && value.trim().length > 0 && !sending;

  async function handleSend() {
    if (!canSend) return;
    setSending(true);
    setErrorKey(null);
    try {
      const result = await onSend(value.trim());
      if (result.ok) {
        setValue("");
      } else {
        setErrorKey(result.error ?? "unknown");
      }
    } finally {
      setSending(false);
    }
  }

  function errorMessage(key: SendResult["error"]): string {
    switch (key) {
      case "not_a_member":
        return composerT("errors.notMember");
      case "stream_not_found":
        return composerT("errors.notFound");
      case "validation":
        return composerT("errors.validation");
      case "network":
        return composerT("errors.network");
      default:
        return composerT("errors.network");
    }
  }

  return (
    <footer
      data-testid="conversation-composer"
      data-locked={locked ? "true" : "false"}
      style={{
        borderTop: "1px solid var(--wg-line)",
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: "var(--wg-surface)",
      }}
    >
      {locked ? (
        <Text variant="caption" muted>
          {lockedReason}
        </Text>
      ) : null}

      <textarea
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          if (errorKey) setErrorKey(null);
        }}
        placeholder={composerT("placeholder")}
        rows={3}
        disabled={locked || sending}
        data-conversation-id={conversationId}
        data-testid="composer-textarea"
        style={{
          width: "100%",
          resize: "vertical",
          minHeight: 64,
          padding: "10px 12px",
          fontSize: "var(--wg-fs-body)",
          fontFamily: "var(--wg-font-sans)",
          lineHeight: "var(--wg-lh-normal)",
          color: "var(--wg-ink)",
          background: locked
            ? "var(--wg-surface-sunk)"
            : "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          outline: "none",
          opacity: locked ? 0.7 : 1,
        }}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            void handleSend();
          }
        }}
      />

      {errorKey ? (
        <Text
          data-testid="composer-error"
          variant="caption"
          style={{ color: "var(--wg-amber)" }}
        >
          {errorMessage(errorKey)}
        </Text>
      ) : null}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <Text variant="caption" muted>
          {composerT("hint")}
        </Text>
        <Button
          data-testid="composer-send"
          variant="primary"
          onClick={handleSend}
          disabled={!canSend}
        >
          {sending ? composerT("sending") : composerT("send")}
        </Button>
      </div>
    </footer>
  );
}
