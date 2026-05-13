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

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Card, EmptyState, Text } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

import { ConversationComposer } from "./ConversationComposer";
import { ConversationHeader } from "./ConversationHeader";
import { DMRightRail } from "./DMRightRail";
import { MessageStream } from "./MessageStream";
import { RoomRightRail } from "./RoomRightRail";
import { TopicRightRail } from "./TopicRightRail";
import type { ConversationDetail } from "./types";

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; conv: ConversationDetail };

function useConversationDetail(id: string | null): FetchState {
  const [state, setState] = useState<FetchState>(
    id ? { status: "loading" } : { status: "idle" },
  );

  useEffect(() => {
    if (!id) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
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
  }, [id]);

  return state;
}

export function ConversationShell({
  selectedId,
  viewerUserId,
}: {
  selectedId: string | null;
  viewerUserId: string;
}) {
  const t = useTranslations("shellV062.conversations.shell");
  const state = useConversationDetail(selectedId);

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
          onSend={async () => {
            // RW-4 is read-only by brief. POST /api/conversations/:id/messages
            // wiring lands in a later phase. The composer is left visible
            // but its send is a no-op so the surface looks complete;
            // the textarea still accepts text but submitting won't post.
            // TODO(RW-5): POST /api/conversations/:id/messages
          }}
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
