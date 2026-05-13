// Feature-scoped types for the Flow Center + Memory Review surfaces.
//
// Phase C scaffold (2026-05-13). These types mirror the wire contract
// in graphflow_handoff_v062/API_CONTRACT.md. Phase B.2 will move the
// authoritative definitions into `@/lib/flowRequests` and `@/lib/memory`
// (paralleling `@/lib/flows`), and this file will re-export from there.
//
// Don't add a parallel review path for a new candidate kind here —
// extend `CandidateKind` in the canonical lib and import. (CLAUDE.md
// invariant: "Membrane is one boundary.")

// ── Live flow packet wire (RW-2.1) ───────────────────────────────────
//
// These mirror the wire shape from GET /api/flow-requests?scope_id=…
// (which wraps FlowProjectionService.list_for_project). The FE
// FlowTable consumes these directly.

export type FlowPacketRecipe =
  | "ask_with_context"
  | "promote_to_memory"
  | "promote_task_to_plan"
  | "crystallize_decision"
  | "manual_create_room"
  | "manual_skill_change"
  | "manual_invite"
  | "review"
  | "handoff"
  | "meeting_metabolism";

export type FlowPacketStatus =
  | "active"
  | "blocked"
  | "completed"
  | "rejected"
  | "expired";

export interface FlowPacket {
  id: string;
  project_id: string;
  recipe_id: FlowPacketRecipe;
  stage: string;
  status: FlowPacketStatus;
  source_user_id: string | null;
  target_user_ids: string[];
  current_target_user_ids: string[];
  authority_user_ids: string[];
  title: string | null;
  summary: string | null;
  intent: string | null;
}

export interface FlowParticipant {
  user_id: string;
  display_name: string;
  username?: string | null;
  avatar_url?: string | null;
}

export interface FlowListResponse {
  packets: FlowPacket[];
  participants: Record<string, FlowParticipant>;
}

// ── Flow Requests ────────────────────────────────────────────────────

export type FlowRequestType =
  | "confirm"
  | "feedback"
  | "review"
  | "clarification"
  | "handoff"
  | "accept_task"
  | "delegate"
  | "approval";

// Frontend-only enum until the BE projection lands.
export type FlowRequestStatus =
  | "draft"
  | "awaiting_response"
  | "in_membrane"
  | "responded"
  | "accepted"
  | "declined";

// ── Authority (mirrors AuthorityCheck in API_CONTRACT.md) ────────────

export type AuthorityRole =
  | "requester"
  | "approver"
  | "reviewer"
  | "assignee"
  | "project_owner";

export type AllowedAction =
  | "accept"
  | "decline"
  | "counter"
  | "escalate"
  | "send"
  | "revise"
  | "reject"
  | "defer"
  | "skip"
  | "reopen";

export interface AuthorityCheck {
  can_accept: boolean;
  required_roles: AuthorityRole[];
  user_roles: AuthorityRole[];
  allowed_actions: AllowedAction[];
}

// ── Memory Candidates ────────────────────────────────────────────────

export type MemoryCandidateStatus =
  | "draft"
  | "prompted"
  | "deferred"
  | "review_pending"
  | "accepted"
  | "rejected"
  | "skipped"
  | "reopened"
  | "expired"
  | "superseded";

// RW-2.2 (2026-05-13): shapes below match the live BE response from
// GET /api/memory-candidates/:id (MembraneService.get_candidate_full_detail).

export interface VerbatimSource {
  // The object the AI distilled from. `kind` is one of message /
  // document / flow_response; `object_id` is the row id (use it +
  // `kind` to build a deep-link when those routes land).
  kind: "message" | "document" | "flow_response";
  object_id: string;
  text: string;
  author_user_id: string | null;
}

export interface CompressionAnalysis {
  status: "no_warnings" | "warnings_found" | "clean";
  warning_count: number;
  method: Array<"rule_based" | "ai_semantic_check" | string>;
  // Doctrine string — must render verbatim wherever this object is
  // surfaced to a reviewer. Server guarantees it contains
  // "does not guarantee" per INVARIANT_TESTS.md §"Compression analysis
  // shape".
  caveat: string;
}

export interface ProposedMemoryAtom {
  // Optional kb_item_id present when a draft KB row already backs the
  // candidate (the M1 path). For task_promote / decision_crystallize
  // candidates, the row doesn't exist yet — title + claim are still
  // populated.
  kb_item_id?: string;
  title: string;
  claim: string;
  scope_id: string | null;
  tier: "cell" | "department" | "enterprise";
}

export interface LifecycleEvent {
  kind: string;
  // Server returns actor_user_id; FE may resolve to display name in a
  // follow-up (Phase RW-3) once a participants sidecar lands on the
  // candidate response.
  actor_user_id: string | null;
  at: string;
  note?: string | null;
}

export interface MemoryCandidate {
  candidate_id: string;
  status: MemoryCandidateStatus;
  scope_id: string | null;
  candidate_kind: string;
  verbatim_source: VerbatimSource;
  ai_extracted_claim: string;
  compression_analysis: CompressionAnalysis;
  compression_warnings: string[];
  proposed_memory_atom: ProposedMemoryAtom;
  authority_check: AuthorityCheck;
  affected_objects: Array<{ kind: string; id: string; label: string }>;
  lifecycle_events: LifecycleEvent[];
}

export interface MemoryCandidatePrompt {
  has_candidate: boolean;
  candidate_id: string;
  // Per API_CONTRACT.md: actions are always [review, skip, later].
  actions: Array<"review" | "skip" | "later">;
}

// ── Flow Request singleton (drawer body) ─────────────────────────────
//
// RW-9 wire shape from GET /api/flow-requests/:id. Currently the BE
// only serves route packets; other kinds raise 422 not_supported_yet.
// The drawer reads that error code and renders an honest non-
// respondable state for those kinds.

export interface FlowRequestBackgroundSnippet {
  source: string;
  snippet: string;
  reference_id?: string | null;
}

export interface FlowRequestOption {
  id: string;
  label: string;
  kind?: string;
  background?: string;
  reason?: string;
  tradeoff?: string;
  weight?: number;
}

export interface FlowRequestHumanGate {
  user_id: string;
  action: string;
  at: string;
  note?: string | null;
}

export interface FlowRequestRef {
  kind: string;
  id?: string;
  label?: string;
  href?: string;
}

export interface FlowRequestEvidence {
  citations: FlowRequestRef[];
  source_messages: FlowRequestRef[];
  artifacts: FlowRequestRef[];
  agent_runs: FlowRequestRef[];
  human_gates: FlowRequestHumanGate[];
  uncertainty: string[];
}

export interface FlowRequestTimelineEvent {
  at: string | null;
  actor: string;
  actor_user_id: string | null;
  kind: string;
  summary: string;
  refs: FlowRequestRef[];
}

// RW-9.5 — the verbatim reply once the target answers. Null while
// the row is still pending. The FE switches on null vs non-null to
// decide whether to render the RecordedReply card.
export interface FlowRequestRecordedReply {
  text: string | null;
  option_id: string | null;
  option_label: string | null;
  replied_at: string | null;
  replier_user_id: string | null;
}

// RW-9.5 — source↔target DM stream lookup result. Both fields null
// when the DM doesn't exist yet (no creation as a GET side effect).
// `href` always points at /conversations/{stream_id} when present.
export interface FlowRequestDmStream {
  stream_id: string | null;
  href: string | null;
}

// The packet shape, enriched with singleton-only fields (framing_full,
// background, options, source/target stream ids, raw_status,
// recorded_reply, dm).
export interface FlowRequestSingleton extends FlowPacket {
  framing_full: string;
  background: FlowRequestBackgroundSnippet[];
  options: FlowRequestOption[];
  source_stream_id: string | null;
  target_stream_id: string | null;
  raw_status: string;
  recorded_reply: FlowRequestRecordedReply | null;
  dm: FlowRequestDmStream;
  evidence: FlowRequestEvidence;
  timeline: FlowRequestTimelineEvent[];
  routed_signal_id?: string;
  project_id: string;
  created_at: string | null;
  updated_at: string | null;
}

export type FlowRequestResponseKind = "direct_response";

export interface FlowRequestRespondability {
  respondable: boolean;
  reason: string | null;
  response_kind: FlowRequestResponseKind | null;
}

export interface FlowRequestSingletonResponse {
  flow_request: FlowRequestSingleton;
  participants: Record<string, FlowParticipant>;
  respondability: FlowRequestRespondability;
}

export interface FlowRequestRespondResponse {
  ok: true;
  flow_request_id: string;
  response_kind: FlowRequestResponseKind;
  signal?: unknown;
  memory_candidate_prompt: MemoryCandidatePrompt;
}
