"use client";

// MyAI Composer — client component for /my-ai.
//
// The /my-ai page renders private-reasoning surface: grounded re-entry
// cards + (eventually) drafts ready to share. This composer is the
// active "think with AI" loop — the user writes, posts to
// /api/my-ai/messages, and the assistant reply + any proposals
// (routing_suggestion, task_candidate, ...) render inline.
//
// Memory decoupling invariant: an assistant reply is NEVER auto-
// crystallized into a memory atom. Proposals surface as cards; the
// user opts in via MemoryReviewDrawer if/when they want to promote.
//
// Scope: requires a concrete scope_id from /api/user/active-scope —
// the underlying PersonalStreamService.post is scope-bound. If the
// user has no focused scope, we render an honest "pick a scope" card
// instead of a broken composer.

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Card, Tag, Text } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type Role = "user" | "assistant" | "system";

interface ThreadEntry {
  id: string;
  role: Role;
  body: string;
  // Proposals attached to the assistant turn (raw envelope for now —
  // a richer renderer per ProposalType lands when the wire normalizes
  // in Phase B.2).
  proposals?: unknown[];
}

// PersonalStreamService.post returns this envelope. The assistant
// reply lives at `edge_response.body`; `edge_response.claims` carries
// citations the FE may surface later. `tool_messages` is the proposals
// channel (routing_suggestion, task_candidate, ...).
interface MyAIMessageResponse {
  ok: boolean;
  message_id?: string;
  edge_response?: {
    kind?: string;
    body?: string;
    reply_message_id?: string;
    claims?: Array<{
      text?: string;
      citations?: Array<{ node_id?: string; kind?: string }>;
    }>;
    uncited?: boolean;
  };
  tool_messages?: unknown[];
  error?: string;
}

export function MyAIComposer({
  scopeId,
  onActivity,
}: {
  scopeId: string | null;
  // Fired once when the user shows intent to interact: textarea focus
  // OR first successful send. Idempotent — the parent (landing
  // wrapper) is expected to handle re-fires gracefully. Optional so
  // the composer can be embedded in surfaces that don't care.
  onActivity?: () => void;
}) {
  const t = useTranslations("shellV062.myAi.composer");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadEntry[]>([]);

  // Guard so a noisy parent doesn't get one callback per keystroke;
  // we want exactly "user is engaged" semantics, fired once.
  const activitySignaled = useRef(false);
  const signalActivity = useCallback(() => {
    if (activitySignaled.current) return;
    activitySignaled.current = true;
    onActivity?.();
  }, [onActivity]);

  if (!scopeId) {
    return (
      <Card variant="sunk">
        <Text variant="caption" muted>
          {t("noScope")}
        </Text>
      </Card>
    );
  }

  const onSubmit = async () => {
    if (busy) return;
    const trimmed = text.trim();
    if (!trimmed) {
      setError(t("errorEmpty"));
      return;
    }
    // Fire activity here too — covers the case where the user keeps
    // their cursor in the textarea (focus already fired) AND also
    // covers programmatic sends (Cmd+Enter from outside focus).
    signalActivity();
    setBusy(true);
    setError(null);

    // Optimistic: push the user turn so the textarea clears
    // immediately and the thread reads naturally. If the POST fails
    // we mark the entry with an error tag, but never silently drop
    // user content.
    const userId = `local-${Date.now()}`;
    setThread((prev) => [
      ...prev,
      { id: userId, role: "user", body: trimmed },
    ]);
    setText("");

    try {
      const result = await api<MyAIMessageResponse>("/api/my-ai/messages", {
        method: "POST",
        body: { body: trimmed, scope_id: scopeId },
      });

      const edge = result.edge_response;
      const assistantBody = edge?.body || null;
      const proposals = result.tool_messages;
      if (assistantBody) {
        setThread((prev) => [
          ...prev,
          {
            id: edge?.reply_message_id || `assistant-${Date.now()}`,
            role: "assistant",
            body: assistantBody,
            proposals,
          },
        ]);
      } else if (proposals && Array.isArray(proposals) && proposals.length > 0) {
        setThread((prev) => [
          ...prev,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            body: "(no message body — see proposals below)",
            proposals,
          },
        ]);
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? t("errorStatus", { status: err.status })
          : t("errorNetwork");
      setError(msg);
      // Tag the optimistic user entry as failed so the user can see
      // it didn't go through. We don't remove it — they might want
      // to copy the text.
      setThread((prev) =>
        prev.map((e) =>
          e.id === userId
            ? { ...e, body: `${e.body}  ${t("failedSuffix")}` }
            : e,
        ),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {thread.length > 0 ? (
        <div
          data-testid="my-ai-thread"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            maxHeight: 480,
            overflowY: "auto",
            padding: "4px 2px",
          }}
        >
          {thread.map((entry) => (
            <Entry key={entry.id} entry={entry} />
          ))}
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          border: "1px solid var(--wg-line)",
          borderRadius: 10,
          padding: 12,
          background: "var(--wg-surface)",
        }}
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={signalActivity}
          placeholder={t("placeholder")}
          rows={3}
          disabled={busy}
          data-testid="my-ai-textarea"
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
              e.preventDefault();
              onSubmit();
            }
          }}
          style={{
            width: "100%",
            padding: 8,
            fontFamily: "var(--wg-font-sans)",
            fontSize: "var(--wg-fs-body)",
            lineHeight: "var(--wg-lh-normal)",
            color: "var(--wg-ink)",
            background: "transparent",
            border: "none",
            outline: "none",
            resize: "vertical",
          }}
        />
        {error ? (
          <Text variant="caption" style={{ color: "var(--wg-danger)" }}>
            {error}
          </Text>
        ) : null}
        <div
          style={{ display: "flex", justifyContent: "space-between", gap: 8 }}
        >
          <Text variant="caption" muted>
            {t("scopeBound")}
          </Text>
          <Button
            size="lg"
            variant="primary"
            onClick={onSubmit}
            disabled={busy || text.trim().length === 0}
            data-testid="my-ai-send"
          >
            {busy ? t("sending") : t("send")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Entry({ entry }: { entry: ThreadEntry }) {
  const t = useTranslations("shellV062.myAi.composer");
  const isUser = entry.role === "user";
  return (
    <div
      style={{
        alignSelf: isUser ? "flex-end" : "flex-start",
        maxWidth: "85%",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <Tag tone={isUser ? "neutral" : "ai"}>
        {isUser ? t("roleUser") : t("roleAssistant")}
      </Tag>
      <Card variant={isUser ? "default" : "sunk"}>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            margin: 0,
            fontFamily: "var(--wg-font-sans)",
            fontSize: "var(--wg-fs-body)",
            lineHeight: "var(--wg-lh-normal)",
            color: "var(--wg-ink)",
          }}
        >
          {entry.body}
        </pre>
      </Card>
      {entry.proposals && entry.proposals.length > 0 ? (
        <Card variant="sunk">
          <Text variant="caption" muted>
            {t("proposals", { count: entry.proposals.length })}
          </Text>
        </Card>
      ) : null}
    </div>
  );
}
