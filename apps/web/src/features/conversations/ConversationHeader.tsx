"use client";

// ConversationHeader — title row of the right pane. Shows the
// conversation title, type chip, and (for Topics) the TopicStatus.
//
// Phase D scaffold (2026-05-13). The Topic status tag is the only
// place inside the shell where TopicStatus surfaces inline; the right
// rail surfaces the same value with affordances (propose closure,
// change status), but the header keeps it visible during scroll.

import { Heading, Tag, Text } from "@/components/ui";

import type { ConversationDetail } from "./types";

// TODO(i18n): shellV062.conversations.header.* keys
const TYPE_LABEL: Record<ConversationDetail["type"], string> = {
  direct: "Direct",
  room: "Room",
  topic: "Topic",
};

const TYPE_TONE: Record<ConversationDetail["type"], "neutral" | "accent" | "amber"> = {
  direct: "neutral",
  room: "accent",
  topic: "amber",
};

const TOPIC_STATUS_LABEL: Record<string, string> = {
  open: "open",
  needs_input: "needs input",
  waiting: "waiting",
  resolved: "resolved",
  archived: "archived",
};

export function ConversationHeader({ conv }: { conv: ConversationDetail }) {
  return (
    <header
      style={{
        padding: "16px 20px",
        borderBottom: "1px solid var(--wg-line)",
        display: "flex",
        alignItems: "center",
        gap: 12,
        background: "var(--wg-surface)",
      }}
    >
      <Tag tone={TYPE_TONE[conv.type]}>{TYPE_LABEL[conv.type]}</Tag>
      <Heading level={2} style={{ margin: 0 }}>
        {conv.title}
      </Heading>
      {conv.type === "topic" && conv.topic_status ? (
        <Tag tone="neutral">
          {TOPIC_STATUS_LABEL[conv.topic_status] ?? conv.topic_status}
        </Tag>
      ) : null}
      {conv.scope_id ? (
        <Text
          variant="caption"
          muted
          style={{ marginLeft: "auto" }}
          title={conv.scope_id}
        >
          {conv.scope_id}
        </Text>
      ) : null}
    </header>
  );
}
