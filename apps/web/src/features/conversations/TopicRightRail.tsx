"use client";

// TopicRightRail — right rail for focused-thread (Topic) conversations.
//
// Phase RW-4 (2026-05-13): honest empty. Topic primitives (TopicRow,
// the /api/topics endpoints) are still Phase B.3 stubs — there's no
// real persisted Topic to render evidence / related work / a
// "waiting on" list for. The Phase D scaffold synthesized all of
// that from a title string; we don't.
//
// The drawer that opened on "Propose closure" is also gone — the
// underlying topic_closure proposal pipeline is a stub and would
// silently no-op. Bring it back when /api/topics/:id and the
// topic_closure proposal accept path are real.

import { useTranslations } from "next-intl";

import { Card, EmptyState, Tag, Text } from "@/components/ui";

import type { ConversationDetail } from "./types";

export function TopicRightRail({ conv }: { conv: ConversationDetail }) {
  const t = useTranslations("shellV062.conversations.rightRail.topic");

  return (
    <aside
      style={{
        width: 320,
        flexShrink: 0,
        borderLeft: "1px solid var(--wg-line)",
        background: "var(--wg-surface-sunk)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        padding: 16,
        overflowY: "auto",
      }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Tag tone="amber">{t("notWiredTag")}</Tag>
        {conv.topic_status ? (
          <Tag tone="neutral">{conv.topic_status}</Tag>
        ) : null}
      </header>

      <EmptyState>{t("notWiredBody")}</EmptyState>

      <Card variant="sunk">
        <Text variant="caption" muted>
          {t("scopeLabel")}: {conv.scope_id ?? "—"}
        </Text>
      </Card>
    </aside>
  );
}
