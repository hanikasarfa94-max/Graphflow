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

// C1-C: generated-backed (GET /api/conversations response_model=
// ConversationIndexResponse). Stable names preserved. Runtime makes `title`
// nullable (name or title) — the generated alias widens the old non-null FE
// type. `type` is the full 3-value union (runtime-tolerant); ACTIVE_TOPIC_STATUSES
// + the FE-only ConversationType/TopicStatus helper unions are retained above.
import type { components } from "@/lib/api-types.gen";

// One row in `recent` (DMs + Rooms). Topics never appear here.
export type RecentConversationSummary =
  components["schemas"]["RecentConversationSummary"];

// One row in `active_topics`. The presence of `topic_status` is what makes
// this a Topic summary rather than a RecentConversationSummary.
export type ActiveTopicSummary = components["schemas"]["ActiveTopicSummary"];

// The shape returned by `GET /api/conversations?scope_id=...`.
export type ConversationIndexResponse =
  components["schemas"]["ConversationIndexResponse"];

// ── Message + conversation detail ────────────────────────────────────

// Wire shape from GET /api/conversations/:id messages[] — mirrors
// StreamService.list_messages, with the v0.6.2 field names the FE
// consumes directly.
export interface ConversationMessage {
  id: string;
  stream_id: string;
  project_id: string | null;
  author_id: string;
  author_username: string | null;
  body: string;
  kind: string | null;
  linked_id: string | null;
  created_at: string;
}

// Participant — one row from StreamMemberRepository, enriched with
// the user's display_name. The viewer is included; the DM rail
// filters them out client-side to find the "other" party.
export interface ConversationParticipant {
  user_id: string;
  username: string;
  display_name: string;
  role_in_stream: string | null;
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
  // Only populated for type === "topic"; backend leaves this null
  // until the TopicRow primitive lands (Phase B.3 follow-up).
  topic_status?: TopicStatus | null;
  participants: ConversationParticipant[];
  messages: ConversationMessage[];
  right_rail: RightRailPayload | null;
}
