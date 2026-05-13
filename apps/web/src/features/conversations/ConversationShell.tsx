"use client";

// ConversationShell — right pane of the Conversations surface.
//
// Phase D scaffold (2026-05-13). Loads the detail for the selected
// conversation and routes the right rail by ConversationType:
//
//   direct → DMRightRail
//   room   → RoomRightRail
//   topic  → TopicRightRail
//
// The header + message stream + composer are the same across types;
// only the right rail (and its primary action) varies.
//
// Phase D.2 swap-in: replace useConversation() with a real fetch
// against `GET /api/conversations/:id` and replace the composer's
// onSend with `POST /api/conversations/:id/messages`. The detail
// response already includes initial `messages` and `right_rail` per
// API_CONTRACT.md, so the wire-up should be a straight transcription.

import { Card, EmptyState, Text } from "@/components/ui";

import { ConversationComposer } from "./ConversationComposer";
import { ConversationHeader } from "./ConversationHeader";
import { DMRightRail } from "./DMRightRail";
import { MessageStream } from "./MessageStream";
import { RoomRightRail } from "./RoomRightRail";
import { TopicRightRail } from "./TopicRightRail";
import type { ConversationDetail } from "./types";

// TODO(phase-d.2): replace with real fetch against
//   `GET /api/conversations/:conversationId`
// Phase D returns a deterministic stub keyed by id so the surface
// renders end-to-end. The id prefix selects which conversation
// type's right rail surfaces — `conv_dm_*` → direct, `conv_room_*`
// → room, `topic_*` → topic. Real fetcher will read `type` off the
// wire response, not infer it from the id.
export function useConversation(id: string | null): ConversationDetail | null {
  if (!id) return null;

  const type: ConversationDetail["type"] = id.startsWith("topic_")
    ? "topic"
    : id.startsWith("conv_dm_")
      ? "direct"
      : "room";

  const title =
    type === "direct"
      ? "Mei"
      : type === "room"
        ? "Q3 Launch Room"
        : "Should Q3 launch slip to Sep 18?";

  const base: ConversationDetail = {
    id,
    type,
    title,
    scope_id: type === "direct" ? null : "scope_tikhub",
    messages: [
      {
        id: `${id}__m1`,
        author: { id: "user_mei", display_name: "Mei" },
        body:
          type === "topic"
            ? "Folks — I think we need to slip the launch by a week. Three blockers landed yesterday."
            : "Quick thread to sync on the launch plan.",
        posted_at: "2026-05-13T09:14:00Z",
      },
      {
        id: `${id}__m2`,
        author: { id: "user_ravi", display_name: "Ravi" },
        body: "Agreed on the blockers. Can we get marketing to weigh in before EOD?",
        posted_at: "2026-05-13T09:42:00Z",
      },
      {
        id: `${id}__m3`,
        author: { id: "user_alex", display_name: "Alex" },
        body: "Marketing here — we can shift the calendar, but we need a confirmation by Thursday or the ad spend locks.",
        posted_at: "2026-05-13T11:08:00Z",
      },
    ],
    right_rail: null,
  };

  if (type === "topic") {
    base.topic_status = "needs_input";
  }

  return base;
}

export function ConversationShell({ selectedId }: { selectedId: string | null }) {
  const conv = useConversation(selectedId);

  if (!conv) {
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
            {/* TODO(i18n): shellV062.conversations.shell.noSelection */}
            <Text variant="body" muted>
              Pick a conversation on the left, or start a new one from Create.
            </Text>
          </EmptyState>
        </Card>
      </section>
    );
  }

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
            // TODO(phase-d.2): wire to
            //   `POST /api/conversations/:conversationId/messages`
            // and append the returned message to the stream.
          }}
        />
      </div>

      {/* Right rail — routed by ConversationType */}
      {conv.type === "direct" ? <DMRightRail conv={conv} /> : null}
      {conv.type === "room" ? <RoomRightRail conv={conv} /> : null}
      {conv.type === "topic" ? <TopicRightRail conv={conv} /> : null}
    </section>
  );
}
