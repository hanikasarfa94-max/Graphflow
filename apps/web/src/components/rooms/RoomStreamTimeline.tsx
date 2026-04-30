"use client";

// RoomStreamTimeline — chronological inline view of one room.
//
// Renders the same TimelineItems the workbench projects, but inline
// in the chat order — source message → suggestion card → decision
// card. Each card carries `data-entity-kind` + `data-entity-id` so
// workbench PanelItems can scroll-to-card via the shared selector.
//
// Composer is mounted at the bottom and threads `streamId` (the room
// id) so posted messages land in this room's stream and any
// crystallized decision auto-scopes to it (B3 + pickup #6 chain).

import { useCallback, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Composer } from "@/components/stream/Composer";
import { DecisionCard } from "@/components/stream/cards";
import type {
  Decision,
  IMMessage,
  TimelineDecisionItem,
  TimelineItem,
  TimelineMessageItem,
  TimelineSuggestionItem,
} from "@/lib/api";
import type { UseRoomTimelineResult } from "@/hooks/useRoomTimeline";

interface Props {
  projectId: string;
  streamId: string;
  currentUserId: string;
  // Map produced by the page from the rooms list — passed to
  // DecisionCard so the vote-scope explainer can resolve names.
  roomNameById: Record<string, { name: string; memberCount: number }>;
  timeline: UseRoomTimelineResult;
}

export function RoomStreamTimeline({
  projectId,
  streamId,
  currentUserId,
  roomNameById,
  timeline,
}: Props) {
  const t = useTranslations("stream.rooms");
  const { items, optimisticInsert, removeOptimistic, error, loading } =
    timeline;
  const [composerError, setComposerError] = useState<string | null>(null);

  // Adapter: Composer expects an `IMMessage` shape for its optimistic
  // insert callback. We turn it into a TimelineMessageItem so the
  // reducer can handle it via the same upsert path the WS uses.
  const handleOptimisticSend = useCallback(
    (m: IMMessage) => {
      optimisticInsert({
        kind: "message",
        id: m.id,
        stream_id: streamId,
        project_id: projectId,
        author_id: m.author_id,
        author_username: null,
        body: m.body,
        kind_message: "text",
        linked_id: null,
        created_at: m.created_at,
      });
    },
    [optimisticInsert, projectId, streamId],
  );

  const handleOptimisticError = useCallback(
    (id: string) => {
      removeOptimistic("message", id);
    },
    [removeOptimistic],
  );

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "#fff",
      }}
    >
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "16px 16px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {loading && items.length === 0 && (
          <p style={emptyStyle}>{t("loading")}</p>
        )}
        {!loading && items.length === 0 && !error && (
          <p style={emptyStyle}>{t("emptyTimeline")}</p>
        )}
        {error && (
          <p style={{ ...emptyStyle, color: "var(--wg-warn, #b94a48)" }}>
            {error}
          </p>
        )}
        {items.map((item) => (
          <TimelineRow
            key={`${item.kind}:${item.id}`}
            item={item}
            projectId={projectId}
            roomNameById={roomNameById}
          />
        ))}
      </div>
      <div
        style={{
          borderTop: "1px solid var(--wg-line)",
          padding: "10px 16px 14px",
          background: "#fff",
        }}
      >
        {composerError && (
          <p
            style={{
              fontSize: 12,
              color: "var(--wg-warn, #b94a48)",
              margin: "0 0 6px",
            }}
          >
            {composerError}
          </p>
        )}
        <Composer
          projectId={projectId}
          currentUserId={currentUserId}
          streamId={streamId}
          onOptimisticSend={handleOptimisticSend}
          onOptimisticError={handleOptimisticError}
          onError={setComposerError}
        />
      </div>
    </div>
  );
}

const emptyStyle: CSSProperties = {
  margin: "32px auto",
  fontSize: 13,
  color: "var(--wg-ink-soft)",
};

function TimelineRow({
  item,
  projectId,
  roomNameById,
}: {
  item: TimelineItem;
  projectId: string;
  roomNameById: Record<string, { name: string; memberCount: number }>;
}) {
  if (item.kind === "message") {
    return <MessageBubble item={item} />;
  }
  if (item.kind === "im_suggestion") {
    return <SuggestionInlineCard item={item} />;
  }
  if (item.kind === "decision") {
    return (
      <DecisionCard
        projectId={projectId}
        decision={timelineItemToDecision(item)}
        roomNameById={roomNameById}
        // Inside a room the viewer is always at scope_stream_id ===
        // current room (timeline endpoint already filters), so vote
        // controls are always enabled here. The DecisionVoteControls
        // component handles its own membership check via the backend.
        voteEnabled
      />
    );
  }
  return null;
}

// Lightweight chat-bubble renderer for room messages. PersonalStream's
// renderer is coupled to the personal-stream user→agent shape;
// rooms are flat multi-author chat so a simpler bubble is right.
function MessageBubble({ item }: { item: TimelineMessageItem }) {
  return (
    <div
      data-entity-kind="message"
      data-entity-id={item.id}
      style={{
        marginBottom: 6,
        padding: "8px 12px",
        background: "#fff",
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          marginBottom: 2,
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {item.author_username ?? item.author_id}
        {item.kind_message !== "text" && (
          <span style={{ marginLeft: 6, opacity: 0.7 }}>
            · {item.kind_message}
          </span>
        )}
      </div>
      <div
        style={{
          fontSize: 14,
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
        }}
      >
        {item.body}
      </div>
    </div>
  );
}

// Inline rendering for a pending IM suggestion. Different shape from
// MembraneCard (which is for membrane-signal/KB-ingest review) — this
// is the LLM classifier's interpretation of a chat message asking
// the team to crystallize it as a decision/blocker/tag/etc.
function SuggestionInlineCard({ item }: { item: TimelineSuggestionItem }) {
  const t = useTranslations("stream.rooms");
  const proposal = item.proposal as Record<string, unknown> | null;
  const summary =
    (proposal && typeof proposal.summary === "string"
      ? (proposal.summary as string)
      : null) ?? item.reasoning;
  const isPending = item.status === "pending";

  return (
    <div
      data-entity-kind="im_suggestion"
      data-entity-id={item.id}
      style={{
        marginBottom: 8,
        marginLeft: 28,
        padding: 10,
        borderLeft: `3px solid ${
          isPending ? "var(--wg-warn, #d99500)" : "var(--wg-line)"
        }`,
        background: isPending ? "#fff8e6" : "#f7f7f7",
        borderRadius: "0 6px 6px 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: isPending
            ? "var(--wg-warn, #d99500)"
            : "var(--wg-ink-soft)",
          marginBottom: 4,
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
        }}
      >
        🧪 {t("suggestionLabel", { kind: item.kind_suggestion })}
        {!isPending && (
          <span style={{ marginLeft: 6, opacity: 0.7 }}>
            · {t(`suggestionStatus.${item.status}`)}
          </span>
        )}
      </div>
      <div style={{ color: "var(--wg-ink)" }}>{summary}</div>
      <div
        style={{
          marginTop: 6,
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          fontStyle: "italic",
        }}
      >
        {t("suggestionFromHint")}
      </div>
    </div>
  );
}

// Adapter: convert a TimelineDecisionItem into the existing Decision
// type that DecisionCard consumes. Keeps the inline card reusing the
// same component the rest of the app uses for decisions.
function timelineItemToDecision(item: TimelineDecisionItem): Decision {
  return {
    id: item.id,
    conflict_id: item.conflict_id,
    project_id: item.project_id,
    resolver_id: item.resolver_id,
    resolver_display_name: null,
    option_index: null,
    custom_text: item.custom_text,
    rationale: item.rationale,
    apply_actions: [],
    apply_outcome:
      item.apply_outcome === null ? undefined : item.apply_outcome,
    apply_detail: undefined,
    source_suggestion_id: item.source_suggestion_id,
    gated_via_proposal_id: null,
    decision_class: null,
    scope_stream_id: item.scope_stream_id,
    // N.4 — tally enriched at the timeline endpoint flows through
    // so DecisionCard's vote affordance can render without a fetch.
    tally: item.tally,
    created_at: item.created_at,
    applied_at: item.applied_at,
  };
}
