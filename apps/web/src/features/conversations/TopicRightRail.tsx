"use client";

// TopicRightRail — right rail for focused-thread (Topic) conversations.
//
// Phase D scaffold (2026-05-13). Follows the DESIGN_LOCK.md spine:
//   Context / Related Work / Evidence / AI Assistance / Primary Action.
//
// Topic-specific framing:
//   * Context shows TopicStatus, source conversation, and the people
//     whose input is being waited on.
//   * Related Work surfaces tasks / docs that depend on this topic
//     resolving.
//   * Evidence is the verbatim source for the question — KB items,
//     prior decisions, attached docs.
//   * AI Assistance proposes a closure (the doctrine entry point for
//     turning a resolved topic into a memory candidate). PER
//     DESIGN_LOCK.md #6+#7 a topic closure proposal is a proposal —
//     authority must accept before any memory crystallizes.
//   * Primary action is "Propose closure" — opens a topic_closure
//     proposal via DrawerHost; mutation happens server-side after
//     authority accepts.

import { useDrawer } from "@/components/shell/v062/DrawerHost";

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
function useTopicRightRail(conv: ConversationDetail) {
  const related: LinkRef[] = [
    linkRefFor("task", "task_marketing_lock", "Marketing schedule lock"),
    linkRefFor("doc", "doc_launch_memo", "Launch memo v4"),
  ].filter((x): x is LinkRef => x !== null);

  const evidence: LinkRef[] = [
    linkRefFor("conversation", "conv_room_launch", "Source: Q3 Launch Room"),
    linkRefFor("kb_item", "kb_launch_constraints", "Launch constraints"),
    linkRefFor("decision", "dec_2026_04_dates", "April date decision"),
  ].filter((x): x is LinkRef => x !== null);

  return {
    context: [
      { label: "Status", value: conv.topic_status ?? "open" },
      { label: "Scope", value: conv.scope_id ?? "—" },
      // TODO(phase-d.2): real waiting-on list from server-side
      // authority + topic-state aggregation.
      { label: "Waiting on", value: "Alex (approver)" },
    ],
    related,
    evidence,
    ai_assistance: [
      {
        id: "ai_topic_closure",
        label: "Summarize the resolution so far",
        proposal_type: "topic_closure" as const,
      },
      {
        id: "ai_topic_memcand",
        label: "Draft a memory candidate from this topic",
        proposal_type: "memory_candidate" as const,
      },
    ],
  };
}

export function TopicRightRail({ conv }: { conv: ConversationDetail }) {
  const rail = useTopicRightRail(conv);
  const drawer = useDrawer();

  // Propose closure is the topic's primary commit point. Per the
  // doctrine the proposal envelope is created server-side (`POST
  // /api/topics/:id/propose-closure` returns `mutates_state: false`)
  // and the resulting proposal is routed through the generic
  // proposal accept path — the topic itself doesn't close until
  // authority accepts. The button opens the proposal in DrawerHost;
  // it does NOT mutate state directly.
  function handleProposeClosure() {
    drawer.open({
      type: "flow_request",
      // TODO(i18n): shellV062.conversations.rightRail.topic.proposeClosure
      title: "Propose closure",
      props: { topic_id: conv.id, proposal_type: "topic_closure" },
    });
  }

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
        // TODO(i18n): shellV062.conversations.rightRail.topic.primary
        label="Propose closure"
        onClick={handleProposeClosure}
        hint="Authority decides whether the resolution sticks."
      />
    </aside>
  );
}
