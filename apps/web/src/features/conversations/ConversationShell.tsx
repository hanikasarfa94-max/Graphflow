"use client";

// ConversationShell — right pane of the Conversations surface.
//
// Phase RW-4 (2026-05-13): the mock useConversation() hook is gone.
// The shell does a client-side fetch against the live
// GET /api/conversations/:id whenever selection changes. The response
// already carries title, type, scope_id, participants, messages, plus
// a right_rail slot (currently null). All of that flows straight into
// the rendered surface — no fabricated rows, no invented people.
//
// Routing of the right rail by ConversationType:
//   direct → DMRightRail (real participants + scope if any)
//   room   → RoomRightRail (real scope + participants)
//   topic  → TopicRightRail (honest empty; no backend persistence yet)

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Card, EmptyState, Text } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

import { ConversationComposer } from "./ConversationComposer";
import { ConversationHeader } from "./ConversationHeader";
import { DMRightRail } from "./DMRightRail";
import { MessageStream } from "./MessageStream";
import { RoomRightRail } from "./RoomRightRail";
import { TopicRightRail } from "./TopicRightRail";
import { postConversationMessage } from "./conversationActions";
import type { ConversationDetail } from "./types";

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; conv: ConversationDetail };

function useConversationDetail(id: string | null): {
  state: FetchState;
  refetch: () => void;
} {
  const [state, setState] = useState<FetchState>(
    id ? { status: "loading" } : { status: "idle" },
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!id) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    // First load: show loading. Subsequent refetches (tick > 0) keep
    // the existing ready state so the message stream doesn't flash
    // empty between POST and the new GET.
    if (tick === 0) setState({ status: "loading" });
    api<ConversationDetail>(
      `/api/conversations/${encodeURIComponent(id)}`,
    )
      .then((data) => {
        if (!cancelled) setState({ status: "ready", conv: data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError
            ? `couldn't load conversation (${err.status})`
            : "couldn't load conversation";
        setState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [id, tick]);

  // Reset tick when id changes so the fresh selection always shows
  // the loading spinner instead of stale-ready state from the
  // previous conversation.
  useEffect(() => {
    setTick(0);
  }, [id]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  return { state, refetch };
}

export function ConversationShell({
  selectedId,
  viewerUserId,
}: {
  selectedId: string | null;
  viewerUserId: string;
}) {
  const t = useTranslations("shellV062.conversations.shell");
  const { state, refetch } = useConversationDetail(selectedId);

  if (state.status === "idle") {
    return <CenteredCard>{t("noSelection")}</CenteredCard>;
  }
  if (state.status === "loading") {
    return <CenteredCard>{t("loading")}</CenteredCard>;
  }
  if (state.status === "error") {
    return <CenteredCard>{t("error", { hint: state.message })}</CenteredCard>;
  }

  const conv = state.conv;

  // Composer behavior per conversation type. Direct + room send for
  // real; topic stays disabled because the topic primitive isn't
  // persisted and POSTing into a stub stream would silently no-op.
  const composerDisabledKey: string | null =
    conv.type === "topic"
      ? "shellV062.conversations.composer.disabledTopic"
      : null;

  return (
    <section
      style={{
        flex: 1,
        display: "flex",
        minHeight: 0,
      }}
    >
      {/* Center column — header + stream + composer */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
        }}
      >
        <ConversationHeader conv={conv} />
        <MessageStream messages={conv.messages} />
        <ConversationComposer
          conversationId={conv.id}
          // Real POST + refetch loop. The shell owns the side-effect;
          // the composer stays purely about input.
          onSend={async (body) => {
            const result = await postConversationMessage(conv.id, body);
            if (result.ok) {
              // Refetch is the cheapest path to server-authoritative
              // state. The new message includes its server-assigned
              // id, kind, created_at, and author_username (which the
              // POST response also includes, but appending would
              // bypass any other side-effects the BE emits — e.g.
              // edge-agent auto-replies in personal streams).
              refetch();
            }
            return result;
          }}
          disabledReasonI18nKey={composerDisabledKey}
        />
      </div>

      {/* Right rail — routed by ConversationType. Each rail consumes
          conv.participants + conv.scope_id from the real wire response;
          there's no rail-internal fabrication. The topic rail is an
          honest "not wired yet" until TopicRow lands. */}
      {conv.type === "direct" ? (
        <DMRightRail conv={conv} viewerUserId={viewerUserId} />
      ) : null}
      {conv.type === "room" ? <RoomRightRail conv={conv} /> : null}
      {conv.type === "topic" ? <TopicRightRail conv={conv} /> : null}
    </section>
  );
}

function CenteredCard({ children }: { children: React.ReactNode }) {
  return (
    <section
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 32,
        background: "var(--wg-surface-sunk)",
      }}
    >
      <Card>
        <EmptyState>
          <Text variant="body" muted>
            {children}
          </Text>
        </EmptyState>
      </Card>
    </section>
  );
}
