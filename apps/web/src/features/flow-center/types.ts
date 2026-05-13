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

export interface VerbatimSource {
  author: string;
  timestamp: string;
  text: string;
  citation_url?: string;
}

export interface CompressionAnalysis {
  status: "no_warnings" | "warnings_found";
  warning_count: number;
  method: Array<"rule_based" | "ai_semantic_check">;
  // Doctrine string — must render verbatim wherever this object is
  // surfaced to a reviewer.
  caveat: string;
}

export interface LifecycleEvent {
  kind:
    | "verbatim_captured"
    | "ai_distilled"
    | "reviewer_revised"
    | "accepted"
    | "rejected"
    | "deferred"
    | "skipped"
    | "reopened";
  actor: string;
  at: string;
  note?: string;
}

export interface MemoryCandidate {
  id: string;
  status: MemoryCandidateStatus;
  verbatim_source: VerbatimSource;
  ai_extracted_claim: string;
  compression_analysis: CompressionAnalysis;
  proposed_memory_atom: string;
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

// ── Flow Request detail (drawer body) ────────────────────────────────

export interface FlowRequestDetail {
  id: string;
  type: FlowRequestType;
  status: FlowRequestStatus;
  requester: { id: string; display_name: string };
  framing: string;
  attachments: Array<{ kind: string; id: string; label: string }>;
  authority_check: AuthorityCheck;
  // Populated after `/respond`. Drives MemoryPromptDrawer routing.
  memory_candidate_prompt?: MemoryCandidatePrompt;
}
