"use client";

// RoomRightRail — right rail for room (multi-party) conversations.
//
// Phase D scaffold (2026-05-13). Follows the DESIGN_LOCK.md spine:
//   Context / Related Work / Evidence / AI Assistance / Primary Action.
//
// Room-specific framing:
//   * Context shows scope + active members.
//   * Related Work surfaces the room's project brief, open tasks,
//     and recently published docs.
//   * Evidence pulls KB items pinned to the room's scope.
//   * AI Assistance leans on "carve a topic from this thread" and
//     "draft a document from the discussion" — the moments where a
//     room conversation should commit into a structured artifact.
//   * Primary action is "Carve a topic" — the room's escalation
//     surface when coordination breaks.

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
function useRoomRightRail(conv: ConversationDetail) {
  const related: LinkRef[] = [
    linkRefFor("scope", conv.scope_id ?? "scope_tikhub", "Project brief"),
    linkRefFor("task", "task_q3_launch_plan", "Q3 launch plan task"),
    linkRefFor("doc", "doc_launch_memo", "Launch memo v4"),
  ].filter((x): x is LinkRef => x !== null);

  const evidence: LinkRef[] = [
    linkRefFor("kb_item", "kb_launch_constraints", "Launch constraints (KB)"),
    linkRefFor("decision", "dec_2026_03_pricing", "Pricing decision Mar '26"),
  ].filter((x): x is LinkRef => x !== null);

  return {
    context: [
      { label: "Scope", value: conv.scope_id ?? "—" },
      // TODO(phase-d.2): real member roster from RightRailService.
      { label: "Active members", value: "Mei, Ravi, Alex, Jess" },
    ],
    related,
    evidence,
    ai_assistance: [
      {
        id: "ai_room_topic",
        label: "Carve a topic from this thread",
        proposal_type: "topic_suggestion" as const,
      },
      {
        id: "ai_room_doc_draft",
        label: "Draft a document from the discussion",
        proposal_type: "document_draft" as const,
      },
      {
        id: "ai_room_impact",
        label: "Show impact analysis for the open question",
        proposal_type: "impact_analysis" as const,
      },
    ],
  };
}

export function RoomRightRail({ conv }: { conv: ConversationDetail }) {
  const rail = useRoomRightRail(conv);

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
        // TODO(i18n): shellV062.conversations.rightRail.room.primary
        label="Carve a topic"
        onClick={() => {
          // TODO(phase-d.2): wire to `POST /api/topics` with
          // source_conversation_id = conv.id and selected message ids.
        }}
        hint="When a thread becomes a coordination problem, give it a status."
      />
    </aside>
  );
}
