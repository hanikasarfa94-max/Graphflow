"use client";

// DMRightRail — right rail for direct (1:1) conversations.
//
// Phase RW-4 (2026-05-13): honest minimal. Renders only what the
// live `GET /api/conversations/:id` response actually carries —
// the other participant + the scope (DMs typically have no scope).
//
// Removed (vs the Phase D scaffold): fabricated docs co-edited with
// the partner, invented follow-up task, made-up AI Assistance
// proposals, simulated primary action. Until those data sources are
// real, they are not rendered. The rail stays a real surface, not a
// stage set.

import { useTranslations } from "next-intl";

import { Card, EmptyState, Tag, Text } from "@/components/ui";

import type { ConversationDetail } from "./types";

export function DMRightRail({
  conv,
  viewerUserId,
}: {
  conv: ConversationDetail;
  viewerUserId: string;
}) {
  const t = useTranslations("shellV062.conversations.rightRail.dm");
  // The "other" participant — DMs always have exactly two members.
  // If the wire response is malformed (zero or only-me), fall back to
  // a neutral display rather than crashing.
  const other = conv.participants.find(
    (p) => p.user_id !== viewerUserId,
  );

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
      <Section title={t("withLabel")}>
        {other ? (
          <Text variant="body">
            {other.display_name || other.username || other.user_id.slice(0, 8)}
          </Text>
        ) : (
          <Text variant="caption" muted>
            {t("noCounterpart")}
          </Text>
        )}
      </Section>

      <Section title={t("scopeLabel")}>
        {conv.scope_id ? (
          <Tag tone="neutral">{conv.scope_id.slice(0, 12)}</Tag>
        ) : (
          <Text variant="caption" muted>
            {t("noScope")}
          </Text>
        )}
      </Section>

      <Card variant="sunk">
        <Text variant="caption" muted>
          {t("notWired")}
        </Text>
      </Card>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <Text
        variant="caption"
        muted
        style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}
      >
        {title}
      </Text>
      {children}
    </section>
  );
}
