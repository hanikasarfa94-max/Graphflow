"use client";

// ConversationList — left pane of the Conversations surface.
//
// Phase D scaffold (2026-05-13). Two visually separate groups:
//
//   1. Recent          — DMs + Rooms (ConversationType in {direct,room})
//   2. Active Topics   — Topics with status ∈ {open, needs_input, waiting}
//
// INVARIANT (INVARIANT_TESTS.md §"Topic deduplication"): the same id
// never appears in both groups. The server partitions the response and
// we render it as-given; this file additionally asserts the invariant
// at render time so a regression on the wire is caught visibly.
//
// Phase D.2 swap-in: replace useConversations() with a real fetch
// against `GET /api/conversations?scope_id=...`. Today the hook
// returns a deterministic stub so the surface eyeballs end-to-end.

import { useMemo } from "react";

import { Card, EmptyState, Tag, Text } from "@/components/ui";

import type {
  ActiveTopicSummary,
  ConversationIndexResponse,
  RecentConversationSummary,
} from "./types";

// TODO(phase-d.2): replace with real fetch against
//   `GET /api/conversations?scope_id=<active>`
// Phase D returns a deterministic stub keyed off no input so the
// styling renders in isolation. Includes at least one DM, one Room,
// and one Active Topic so the grouping grammar is exercised.
export function useConversations(): ConversationIndexResponse {
  return {
    recent: [
      {
        id: "conv_dm_mei",
        type: "direct",
        title: "Mei",
        scope_id: null,
        last_message_at: "2026-05-13T14:32:00Z",
        unread_count: 2,
      },
      {
        id: "conv_dm_ravi",
        type: "direct",
        title: "Ravi",
        scope_id: null,
        last_message_at: "2026-05-13T11:08:00Z",
        unread_count: 0,
      },
      {
        id: "conv_room_launch",
        type: "room",
        title: "Q3 Launch Room",
        scope_id: "scope_tikhub",
        last_message_at: "2026-05-13T13:55:00Z",
        unread_count: 5,
      },
      {
        id: "conv_room_growth",
        type: "room",
        title: "Growth Weekly",
        scope_id: "scope_growth",
        last_message_at: "2026-05-12T22:40:00Z",
        unread_count: 0,
      },
    ],
    active_topics: [
      {
        id: "topic_launch_date",
        type: "topic",
        title: "Should Q3 launch slip to Sep 18?",
        scope_id: "scope_tikhub",
        last_message_at: "2026-05-13T15:02:00Z",
        unread_count: 1,
        topic_status: "needs_input",
      },
      {
        id: "topic_pricing_floor",
        type: "topic",
        title: "Pricing floor for the SMB tier",
        scope_id: "scope_tikhub",
        last_message_at: "2026-05-13T09:14:00Z",
        unread_count: 0,
        topic_status: "waiting",
      },
    ],
  };
}

// TODO(i18n): shellV062.conversations.list.* keys
const RECENT_LABEL = "Recent";
const ACTIVE_TOPICS_LABEL = "Active Topics";
const EMPTY_RECENT = "No DMs or rooms yet.";
const EMPTY_TOPICS = "No active topics. Topics are carved from messages where coordination breaks open.";

const TYPE_TONE: Record<"direct" | "room" | "topic", "neutral" | "accent" | "amber"> = {
  direct: "neutral",
  room: "accent",
  topic: "amber",
};

const TOPIC_STATUS_LABEL: Record<string, string> = {
  open: "open",
  needs_input: "needs input",
  waiting: "waiting",
};

export function ConversationList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const data = useConversations();

  // Defensive: assert the topic dedup invariant at render time. If the
  // server ever regresses and emits the same id in both groups, drop
  // the duplicate from active_topics so the UI doesn't double-render
  // the row. Logs a console warning so the regression is visible in
  // dev without taking down the page.
  const safeActiveTopics = useMemo(() => {
    const recentIds = new Set(data.recent.map((r) => r.id));
    const filtered: ActiveTopicSummary[] = [];
    for (const t of data.active_topics) {
      if (recentIds.has(t.id)) {
        // eslint-disable-next-line no-console
        console.warn(
          `[ConversationList] topic dedup invariant violated: id=${t.id} appears in both recent and active_topics`,
        );
        continue;
      }
      filtered.push(t);
    }
    return filtered;
  }, [data.recent, data.active_topics]);

  return (
    <aside
      style={{
        width: 320,
        flexShrink: 0,
        borderRight: "1px solid var(--wg-line)",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: 16,
        overflowY: "auto",
        background: "var(--wg-surface)",
      }}
    >
      <Group label={RECENT_LABEL}>
        {data.recent.length === 0 ? (
          <EmptyState>{EMPTY_RECENT}</EmptyState>
        ) : (
          data.recent.map((row) => (
            <RecentRow
              key={row.id}
              row={row}
              selected={row.id === selectedId}
              onSelect={onSelect}
            />
          ))
        )}
      </Group>

      <Group label={ACTIVE_TOPICS_LABEL}>
        {safeActiveTopics.length === 0 ? (
          <EmptyState>{EMPTY_TOPICS}</EmptyState>
        ) : (
          safeActiveTopics.map((row) => (
            <TopicRow
              key={row.id}
              row={row}
              selected={row.id === selectedId}
              onSelect={onSelect}
            />
          ))
        )}
      </Group>
    </aside>
  );
}

function Group({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Text
        as="div"
        variant="caption"
        muted
        style={{
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          fontWeight: 600,
        }}
      >
        {label}
      </Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {children}
      </div>
    </section>
  );
}

function RecentRow({
  row,
  selected,
  onSelect,
}: {
  row: RecentConversationSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(row.id)}
      style={{
        textAlign: "left",
        background: selected ? "var(--wg-surface-sunk)" : "transparent",
        border: "1px solid",
        borderColor: selected ? "var(--wg-line)" : "transparent",
        borderRadius: "var(--wg-radius)",
        padding: "10px 12px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
      aria-pressed={selected}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Tag tone={TYPE_TONE[row.type]}>{row.type}</Tag>
        <Text variant="body" style={{ fontWeight: 600 }}>
          {row.title}
        </Text>
        {row.unread_count > 0 ? (
          <span style={{ marginLeft: "auto" }}>
            <Tag tone="accent">{row.unread_count}</Tag>
          </span>
        ) : null}
      </div>
      {row.last_message_at ? (
        <Text variant="caption" muted>
          {formatRelative(row.last_message_at)}
        </Text>
      ) : null}
    </button>
  );
}

function TopicRow({
  row,
  selected,
  onSelect,
}: {
  row: ActiveTopicSummary;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(row.id)}
      style={{
        textAlign: "left",
        background: selected ? "var(--wg-surface-sunk)" : "transparent",
        border: "1px solid",
        borderColor: selected ? "var(--wg-line)" : "transparent",
        borderRadius: "var(--wg-radius)",
        padding: "10px 12px",
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
      aria-pressed={selected}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Tag tone="amber">topic</Tag>
        <Tag tone="neutral">
          {TOPIC_STATUS_LABEL[row.topic_status] ?? row.topic_status}
        </Tag>
        {row.unread_count > 0 ? (
          <span style={{ marginLeft: "auto" }}>
            <Tag tone="accent">{row.unread_count}</Tag>
          </span>
        ) : null}
      </div>
      <Text variant="body" style={{ fontWeight: 600 }}>
        {row.title}
      </Text>
      {row.last_message_at ? (
        <Text variant="caption" muted>
          {formatRelative(row.last_message_at)}
        </Text>
      ) : null}
    </button>
  );
}

// All visible timestamps funnel through lib/time so SSR + CSR render
// the same Asia/Shanghai string (M1.1 invariant).
import { formatIso as _formatIso } from "@/lib/time";
function formatRelative(iso: string): string {
  return _formatIso(iso);
}
