// Feature-scoped types for the Conversations surface.
//
// Phase D scaffold (2026-05-13). Mirrors the v0.6.2 wire contract in
// graphflow_handoff_v062/API_CONTRACT.md §Conversations + §Topics. The
// authoritative wire shapes will move to `@/lib/conversations` once
// Phase D.2 lands the real fetchers; for now these types live here so
// the scaffold isn't blocked on cross-cutting lib work.
//
// Doctrine invariants reflected in this type surface:
//   * ConversationType has exactly three values: "direct" | "room" |
//     "topic". A Topic is a focused thread, not a sub-tab inside a
//     room.
//   * TopicStatus carries lifecycle. "active" (open / needs_input /
//     waiting) is the subset rendered under Active Topics; resolved
//     and archived fall off the index entirely.
//   * INVARIANT_TESTS.md §"Topic deduplication": a conversation id
//     appears in exactly one of `recent` or `active_topics`. The
//     server filters; the FE renders.

// ── Conversation core ────────────────────────────────────────────────

export type ConversationType = "direct" | "room" | "topic";

export type TopicStatus =
  | "open"
  | "needs_input"
  | "waiting"
  | "resolved"
  | "archived";

// The subset of TopicStatus values that count as "active" for the
// Active Topics group in the index. Resolved + archived are excluded.
export const ACTIVE_TOPIC_STATUSES: ReadonlyArray<TopicStatus> = [
  "open",
  "needs_input",
  "waiting",
];

// One row in `recent` (DMs + Rooms). Topics never appear here.
export interface RecentConversationSummary {
  id: string;
  type: Exclude<ConversationType, "topic">;
  title: string;
  scope_id: string | null;
  last_message_at: string | null;
  unread_count: number;
}

// One row in `active_topics`. The presence of `topic_status` (always
// in ACTIVE_TOPIC_STATUSES) is what makes this a Topic summary rather
// than a RecentConversationSummary.
export interface ActiveTopicSummary {
  id: string;
  type: "topic";
  title: string;
  scope_id: string | null;
  last_message_at: string | null;
  unread_count: number;
  topic_status: TopicStatus;
}

// The shape returned by `GET /api/conversations?scope_id=...`. Per
// the contract, `recent` and `active_topics` partition the user's
// conversations — never an id in both.
export interface ConversationIndexResponse {
  recent: RecentConversationSummary[];
  active_topics: ActiveTopicSummary[];
}

// ── Message + conversation detail ────────────────────────────────────

export interface ConversationMessage {
  id: string;
  author: { id: string; display_name: string };
  body: string;
  posted_at: string;
}

// Right rail spine, shared across surfaces per DESIGN_LOCK.md:
//   Context / Related Work / Evidence / AI Assistance / Primary Action
// The conversation detail endpoint returns a `right_rail` payload
// shaped roughly like this. Phase D.2 will firm up the exact shape;
// today this is a loose placeholder so the scaffold can render.
export interface RightRailPayload {
  context: Array<{ label: string; value: string }>;
  related_work: Array<{ kind: string; id: string; label: string; url: string }>;
  evidence: Array<{ kind: string; id: string; label: string; url: string }>;
  ai_assistance: Array<{
    id: string;
    label: string;
    proposal_type: string;
  }>;
  primary_action: { label: string; kind: "send" | "resolve" | "promote" } | null;
}

export interface ConversationDetail {
  id: string;
  type: ConversationType;
  title: string;
  scope_id: string | null;
  // Only populated for type === "topic"
  topic_status?: TopicStatus;
  messages: ConversationMessage[];
  right_rail: RightRailPayload | null;
}
