// Flow Packets — typed client for /api/projects/{id}/flows.
//
// Mirrors the §6 packet shape from docs/flow-packets-spec.md. Locking
// the contract in TypeScript prevents Slice C+ from drifting against
// what the projection actually emits — the BE returns dicts, but every
// caller on the FE goes through this typed boundary.
//
// Slice B is read-only; this file should NOT export action POST
// helpers until Slice C lands FlowActionService.

import { api } from "./api";

// Recipe ids the BE may emit. Slice A covers three; Slice E adds the
// rest. Keep the union exhaustive so TS narrows correctly in switch
// statements and we don't need a default branch.
export type FlowRecipeId =
  | "ask_with_context"
  | "promote_to_memory"
  | "crystallize_decision"
  | "review"
  | "handoff"
  | "meeting_metabolism";

// Packet status (the high-level lifecycle), separate from `stage`
// (display label). Spec §6.
export type FlowPacketStatus =
  | "active"
  | "blocked"
  | "completed"
  | "rejected"
  | "expired";

// Bucket — viewer-relative grouping. The BE applies the bucket filter;
// the FE only ever sends one of these as a query param.
export type FlowBucket =
  | "needs_me"
  | "waiting_on_others"
  | "awaiting_membrane"
  | "recent";

// FlowRef — pointer at a graph row carried in source_refs / graph_refs
// / evidence packet. `href` may be present when the BE has chosen a
// canonical surface for this entity; FE may render as link or chip.
export interface FlowRef {
  kind:
    | "message"
    | "decision"
    | "kb"
    | "task"
    | "risk"
    | "handoff"
    | "meeting"
    | "agent_run";
  id: string;
  label: string;
  href?: string;
}

// FlowAction — what the viewer can do next on this packet. The kind
// union is the FE boundary lock on the BE projection's emitted shapes.
// C.1 source-side mutations are `accept | counter_back |
// escalate_to_gate | custom_followup`. The `counter | delegate_up |
// dismiss | publish | request_review` kinds are reserved for later
// slices (C.2 target-side, KB review, etc.) and stay in the union
// so the FE compiles against the spec, not just against today's
// projection. `open` is the read-only link kind (Slice A/B).
export interface FlowAction {
  id: string;
  label: string;
  kind:
    | "accept"
    | "counter_back"
    | "custom_followup"
    | "counter"
    | "delegate_up"
    | "escalate_to_gate"
    | "dismiss"
    | "open"
    | "publish"
    | "request_review";
  actor_user_id?: string;
  requires_membrane: boolean;
  href?: string;
}

// FlowEvent — one timeline entry. Slice B doesn't render the timeline
// (that's flow detail in §10.2); the type stays here so Slice D can
// reach for it without re-typing.
export interface FlowEvent {
  at: string;
  actor: "human" | "edge_agent" | "parent_agent" | "membrane" | "system";
  actor_user_id?: string;
  kind: string;
  summary: string;
  refs: FlowRef[];
}

// EvidencePacket — Slice A emits an empty shell; Slice D fills it.
export interface EvidencePacket {
  citations: FlowRef[];
  source_messages: FlowRef[];
  artifacts: FlowRef[];
  agent_runs: FlowRef[];
  human_gates: Array<{
    user_id: string;
    // Spec §6 / §7 split: target-side `delegate_up` (push to authority
    // with stance attached) is distinct from source-side
    // `escalate_to_gate` (push to authority pool / quorum / Membrane).
    // Pre-v1.1 this union had a single ambiguous "escalate" — Slice C's
    // FlowActionService relies on the split, so the FE union must
    // match the spec exactly here.
    action:
      | "accept"
      | "counter"
      | "dismiss"
      | "delegate_up"
      | "escalate_to_gate"
      | "approve"
      | "reject";
    at: string;
    note?: string;
  }>;
  uncertainty: string[];
}

// FlowPacket — the §6 read-model shape. Optional ids (decision_id,
// kb_item_id, etc.) are nullable rather than absent because the BE
// emits them as null when not applicable; this keeps narrow checks
// uniform across recipes.
export interface FlowPacket {
  id: string;
  project_id: string;
  recipe_id: FlowRecipeId;
  // `stage` is a display label per §4 — never trust it as state-of-
  // truth. Drawer renders it; logic should branch on `status` and
  // `current_target_user_ids`.
  stage: string;
  status: FlowPacketStatus;
  source_user_id?: string | null;
  // `target_user_ids` is participation history; `current_target_user_ids`
  // is the derived "currently blocking" slice (§6 / line 276 of spec).
  // Drawer's "who is the current actor" reads current_target_user_ids,
  // never target_user_ids.
  target_user_ids: string[];
  current_target_user_ids: string[];
  authority_user_ids: string[];
  title: string;
  summary: string;
  intent: string;
  source_refs: FlowRef[];
  graph_refs: FlowRef[];
  evidence: EvidencePacket;
  routed_signal_id?: string | null;
  im_suggestion_id?: string | null;
  membrane_candidate?: {
    kind: string;
    action?: string;
    conflict_with: string[];
    warnings: string[];
  } | null;
  decision_id?: string | null;
  kb_item_id?: string | null;
  task_id?: string | null;
  handoff_id?: string | null;
  scrimmage_id?: string | null;
  meeting_transcript_id?: string | null;
  timeline: FlowEvent[];
  next_actions: FlowAction[];
  created_at: string;
  updated_at: string | null;
}

export interface FlowsListResponse {
  packets: FlowPacket[];
}

export interface FlowsListParams {
  status?: FlowPacketStatus;
  bucket?: FlowBucket;
  recipe?: FlowRecipeId;
  limit?: number;
}

function buildQuery(params?: FlowsListParams): string {
  if (!params) return "";
  const q = new URLSearchParams();
  if (params.status) q.set("status", params.status);
  if (params.bucket) q.set("bucket", params.bucket);
  if (params.recipe) q.set("recipe", params.recipe);
  if (params.limit) q.set("limit", String(params.limit));
  const s = q.toString();
  return s ? `?${s}` : "";
}

// listFlows — single endpoint helper. Slice B's drawer fans out three
// calls (one per bucket); we keep the helper bucket-agnostic so detail
// views in later slices can drop the bucket filter and reuse the
// same client.
export function listFlows(
  projectId: string,
  params?: FlowsListParams,
  baseUrl?: string,
): Promise<FlowsListResponse> {
  return api<FlowsListResponse>(
    `/api/projects/${projectId}/flows${buildQuery(params)}`,
    { baseUrl },
  );
}

// ---- C.1 — POST /actions client ----------------------------------------

// Discriminated union mirroring the BE Pydantic body. TS narrows on
// `action` so missing `framing` on counter_back / custom_followup
// won't compile.
export type FlowActionBody =
  | { action: "accept"; note?: string }
  | { action: "counter_back"; framing: string; note?: string }
  | { action: "escalate_to_gate"; note?: string }
  | { action: "custom_followup"; framing: string; note?: string };

export type FlowActionKind = FlowActionBody["action"];

// The mutation action kinds the FE renders as buttons. `open` is a
// link, not part of this set. Slice C.2 will widen this when target-
// side actions land; for C.1 these are source-side only.
export const MUTATION_ACTION_KINDS: readonly FlowActionKind[] = [
  "accept",
  "counter_back",
  "escalate_to_gate",
  "custom_followup",
];

export function isMutationAction(kind: string): kind is FlowActionKind {
  return (MUTATION_ACTION_KINDS as readonly string[]).includes(kind);
}

// Actions whose body must include a `framing` string. Used by the FE
// to know whether to render a textarea form or just a confirm button.
export function actionRequiresFraming(kind: FlowActionKind): boolean {
  return kind === "counter_back" || kind === "custom_followup";
}

export interface FlowActionResponse {
  ok: boolean;
  flow_id: string;
  // Original packet's projected status post-action. Memo §4.4: for
  // custom_followup this stays `completed` because the underlying
  // signal stays 'replied' which projects to packet status
  // 'completed'. The FE refresh logic should NOT assume `active`
  // means "the original is still alive" — read this status field
  // directly.
  status: "active" | "completed" | string;
  spawned_flow_id: string | null;
}

export function postFlowAction(
  projectId: string,
  flowId: string,
  body: FlowActionBody,
  baseUrl?: string,
): Promise<FlowActionResponse> {
  return api<FlowActionResponse>(
    `/api/projects/${projectId}/flows/${encodeURIComponent(flowId)}/actions`,
    { method: "POST", body, baseUrl },
  );
}

// Pretty labels for the three bucket buttons. Caller passes a
// next-intl translator; we don't import next-intl here so this file
// stays usable from non-React contexts (tests, scripts, etc.).
export const BUCKETS: readonly FlowBucket[] = [
  "needs_me",
  "waiting_on_others",
  "awaiting_membrane",
];

// Recipe icon — tiny visual anchor in the row, kept out of i18n
// because emoji are language-neutral. The mapping mirrors the rituals
// catalog so the same recipe wears the same glyph everywhere.
export const RECIPE_ICON: Record<FlowRecipeId, string> = {
  ask_with_context: "🧭",
  promote_to_memory: "📚",
  crystallize_decision: "💠",
  review: "🔎",
  handoff: "🤝",
  meeting_metabolism: "🗒",
};
