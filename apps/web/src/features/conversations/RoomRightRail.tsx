"use client";

// RoomRightRail — right rail for room (multi-party) conversations.
//
// Phase RW-4 (2026-05-13): honest minimal. Renders only what the
// live conversation detail carries — the room's scope + its real
// member list. The Phase D scaffold rendered fake docs, fake KB
// items, fake decisions, fake AI Assistance proposals. All of that
// is gone until those data sources are real.

import { useTranslations } from "next-intl";

import { Card, Tag, Text } from "@/components/ui";

import type { ConversationDetail } from "./types";

export function RoomRightRail({ conv }: { conv: ConversationDetail }) {
  const t = useTranslations("shellV062.conversations.rightRail.room");

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
      <Section title={t("scopeLabel")}>
        {conv.scope_id ? (
          <Tag tone="neutral">{conv.scope_id.slice(0, 12)}</Tag>
        ) : (
          <Text variant="caption" muted>
            {t("noScope")}
          </Text>
        )}
      </Section>

      <Section
        title={t("participantsLabel", { count: conv.participants.length })}
      >
        {conv.participants.length === 0 ? (
          <Text variant="caption" muted>
            {t("noParticipants")}
          </Text>
        ) : (
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            {conv.participants.map((p) => (
              <li key={p.user_id}>
                <Text variant="body">
                  {p.display_name || p.username || p.user_id.slice(0, 8)}
                </Text>
                {p.role_in_stream && p.role_in_stream !== "member" ? (
                  <Text variant="caption" muted>
                    {" "}
                    · {p.role_in_stream}
                  </Text>
                ) : null}
              </li>
            ))}
          </ul>
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
