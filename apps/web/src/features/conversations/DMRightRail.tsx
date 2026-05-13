"use client";

// DMRightRail — right rail for direct (1:1) conversations.
//
// Phase D scaffold (2026-05-13). Follows the DESIGN_LOCK.md spine:
//   Context / Related Work / Evidence / AI Assistance / Primary Action.
//
// DM-specific framing:
//   * Context shows the other participant + shared scopes.
//   * Related Work pulls items the two of you have collaborated on.
//   * Evidence is intentionally sparse for DMs — DMs rarely cite.
//   * AI Assistance is biased toward "elevate to topic" / "create
//     task candidate" proposals, since DMs are where coordination
//     often surfaces but isn't yet structured.
//   * Primary action is "Start a topic" — the DM's escape hatch into
//     a coordination-shaped conversation.

import {
  AIAssistanceSection,
  ContextSection,
  EvidenceSection,
  PrimaryActionFooter,
  RelatedWorkSection,
  linkRefFor,
  type LinkRef,
} from "./rightRailShared";
import type { ConversationDetail } from "./types";

// TODO(phase-d.2): replace with right_rail payload from
//   `GET /api/conversations/:conversationId`
// (the response already includes an initial `right_rail` slot, today
// returned as `null`). For the scaffold we synthesize a believable
// payload from the conversation title so the layout renders.
function useDMRightRail(conv: ConversationDetail) {
  const counterpart = conv.title;

  const related: LinkRef[] = [
    linkRefFor("doc", "doc_shared_brief", `Brief co-edited with ${counterpart}`),
    linkRefFor("task", "task_followup", "Follow-up task from last week"),
  ].filter((x): x is LinkRef => x !== null);

  const evidence: LinkRef[] = [];

  return {
    context: [
      { label: "With", value: counterpart },
      { label: "Shared scopes", value: conv.scope_id ?? "personal" },
    ],
    related,
    evidence,
    ai_assistance: [
      {
        id: "ai_dm_topic",
        label: "Suggest carving this into a topic",
        proposal_type: "topic_suggestion" as const,
      },
      {
        id: "ai_dm_task",
        label: "Surface task candidates from this thread",
        proposal_type: "task_candidate" as const,
      },
    ],
  };
}

export function DMRightRail({ conv }: { conv: ConversationDetail }) {
  const rail = useDMRightRail(conv);

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
      <ContextSection rows={rail.context} />
      <RelatedWorkSection items={rail.related} />
      <EvidenceSection items={rail.evidence} />
      <AIAssistanceSection actions={rail.ai_assistance} />
      <PrimaryActionFooter
        // TODO(i18n): shellV062.conversations.rightRail.dm.primary
        label="Start a topic from here"
        onClick={() => {
          // TODO(phase-d.2): wire to `POST /api/topics` with
          // source_conversation_id = conv.id and selected message ids.
        }}
        hint="Topics carve coordination out of chat."
      />
    </aside>
  );
}
