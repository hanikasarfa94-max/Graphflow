// Fetch wrapper. All calls go through /api/* which Next rewrites to the
// FastAPI backend (see next.config.mjs). Same-origin → the session cookie
// flows automatically. Throws `ApiError` on non-2xx so callers can
// distinguish 401/403/404 from a network error.

// Type-only import for the messaging helper `saveMessageAsKb` below,
// which produces a KbNote. The KB client itself lives in
// `features/kb/api.ts`; the public re-exports for the rest of the KB
// surface are at the bottom of this file.
import type { KbNote } from "@/features/kb/api";
// C1-B: generated OpenAPI schemas (single source of truth for wire shapes).
// Hand-written types are migrated to aliases of these, one slice at a time,
// keeping the exported names stable so consumers don't change.
import type { components } from "./api-types.gen";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// Pull a human-readable message out of an ApiError body. Handles three
// shapes the BE returns:
//   1. plain FastAPI:     { detail: "string" }
//   2. plain FastAPI 422: { detail: [{ msg, loc, type, … }, …] }
//   3. WG custom envelope:{ code, message, details: { errors: [{ msg, … }] } }
// Falls back to `null` when nothing useful is found so the caller can
// decide between a friendly local string and a generic "error N".
export function extractApiErrorDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;

  // Shape 3 — custom envelope. Prefer the structured per-field msg, fall
  // back to the top-level `message` only if no structured error is set.
  const details = b["details"];
  if (details && typeof details === "object") {
    const errors = (details as Record<string, unknown>)["errors"];
    if (Array.isArray(errors) && errors.length > 0) {
      const first = errors[0];
      if (first && typeof first === "object" && "msg" in first) {
        return String((first as { msg?: unknown }).msg ?? "") || null;
      }
    }
  }
  const message = b["message"];
  if (typeof message === "string" && message) return message;

  // Shape 1 / 2 — vanilla FastAPI `detail`.
  const detail = b["detail"];
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first) {
      return String((first as { msg?: unknown }).msg ?? "") || null;
    }
  }

  return null;
}

// Exported so feature-scoped clients (e.g. `features/kb/api.ts`) can
// type their request bodies against the shared `api()` wrapper.
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [k: string]: JsonValue };

export interface ApiOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  body?: JsonValue;
  signal?: AbortSignal;
  // Server-side fetch needs the full origin; callers pass a base.
  baseUrl?: string;
}

export async function api<T = unknown>(
  path: string,
  opts: ApiOptions = {},
): Promise<T> {
  const base = opts.baseUrl ?? "";
  const res = await fetch(`${base}${path}`, {
    method: opts.method ?? "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    credentials: "include",
    signal: opts.signal,
    cache: "no-store",
  });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    throw new ApiError(res.status, body, `api ${res.status} on ${path}`);
  }
  return body as T;
}

// ---------- Shared response shapes ----------

// C1-B: alias to the generated `UserResponse` schema (auth.py register/login/me
// response_model). The hand-written type previously declared a `created_at`
// field the backend UserResponse ({id, username, display_name}) never returns —
// a phantom FE-only field, now dropped. No consumer reads it (typecheck green).
export type User = components["schemas"]["UserResponse"];

// C1-B: generated-backed export for GET /api/user/active-scope
// (scopes.py response_model=ActiveScopeResponse). Stable name several page
// components migrate their local duplicates onto. Generated shape includes
// `updated_at: string | null`, which 3 of the 4 page-local copies omitted —
// a safe widening (none read it); flow-center already matched.
export type ActiveScope = components["schemas"]["ActiveScopeResponse"];

// C1-B: generated-backed exports for GET /api/my-ai/landing
// (my_ai.py response_model=MyAILandingResponse). Stable names the /my-ai page
// and MyAILandingClient migrate their local duplicates onto. The generated
// children mark scope_id/object_url/target_* optional (`?:`) where the local
// copies had required `string | null` — a safe widening; consumers read them
// null-tolerantly (e.g. `item.object_url || "#"`) and never read target_*.
export type GroundedItem = components["schemas"]["GroundedItem"];
export type ShareableDraft = components["schemas"]["ShareableDraft"];
export type MyAILandingResponse = components["schemas"]["MyAILandingResponse"];

// C1-C: generated-backed (GET /api/projects response_model=list[ProjectSummary]).
// Surfaces requirement_version (runtime always emitted it; the old hand type
// silently dropped it).
export type ProjectSummary = components["schemas"]["ProjectSummary"];

// ---------- Silent consensus (Phase 1.A) ----------
// C1-C: generated-backed (GET /api/projects/{id}/silent-consensus
// response_model=SilentConsensusListResponse). No mismatch — runtime and FE
// both model supporting_action_ids as {kind,id} objects. status widens
// union→string.

// C1-C: generated-backed (GET /projects/{id}/decisions response_model=
// DecisionListResponse, behind the consolidated _decisions_serialize helper).
// The four provenance fields (resolver_display_name/gated_via_proposal_id/
// decision_class/scope_stream_id) are now emitted by every decision path.
// apply_outcome widens from the FE union to string (runtime column is
// unconstrained); tally is optional (only WS/room-timeline paths enrich it).
export type Decision = components["schemas"]["Decision"];

// ---------- IM suggestions ----------

export interface IMSuggestionProposal {
  action: string;
  summary: string;
  detail: Record<string, unknown>;
}

export interface IMSuggestion {
  id: string;
  message_id: string;
  project_id: string;
  // Phase L: 'wiki_entry' (IM-assist proposes saving the message to
  // the project wiki). Phase membrane-reorg.S4: 'membrane_review' (the
  // membrane staged a kb_item_group or task_promote candidate; the
  // owner accepts here to flip draft → published / personal → plan).
  kind:
    | "none"
    | "tag"
    | "decision"
    | "blocker"
    | "wiki_entry"
    | "membrane_review";
  confidence: number;
  targets: string[];
  proposal: IMSuggestionProposal | null;
  reasoning: string;
  status: "pending" | "accepted" | "dismissed" | "countered" | "escalated";
  created_at: string;
  resolved_at: string | null;
  counter_of_id: string | null;
  decision_id: string | null;
  escalation_state: "requested" | null;
}

export interface IMMessage {
  id: string;
  project_id: string;
  author_id: string;
  author_username?: string;
  author_display_name?: string;
  body: string;
  // Phase S — lets the group-stream renderer switch on structural
  // kinds (vote-opened, vote-resolved-approved, vote-resolved-denied,
  // gated-proposal-resolved, …) and render typed cards instead of the
  // default chat bubble. Absent on pre-Phase-S cached rows.
  kind?: string;
  linked_id?: string | null;
  created_at: string;
  suggestion?: IMSuggestion | null;
}

// ---------- Streams (Phase B) ----------

export interface StreamMemberSummary {
  user_id: string;
  username: string;
  display_name: string;
  role_in_stream: string;
}

export interface StreamSummary {
  id: string;
  // Room and personal added in N-Next; persisted name only meaningful
  // for type='room'.
  type: "project" | "dm" | "room" | "personal";
  project_id: string | null;
  // owner_user_id is set for type='personal' (the user who owns the
  // sub-agent conversation). Null for project / dm / room.
  owner_user_id?: string | null;
  // Persisted display name (alembic 0029) — null for non-room types.
  name?: string | null;
  // Resolved canonical anchor (v-Next E-3 / Q-E):
  //   room with name      → stream.name
  //   project / room      → owning project's title
  //   personal (project)  → owning project's title (FE formats
  //                         "{display_name} 的 Agent" via i18n)
  //   personal (global)   → null (FE i18n: "通用 Agent" / "General Agent")
  //   dm                  → null (FE picks partner from members)
  display_name?: string | null;
  members: StreamMemberSummary[];
  last_activity_at: string | null;
  created_at: string | null;
  unread_count: number;
}

// v-next AgentFlow uses these directly. Existing PersonalStream /
// RoomStreamTimeline code paths still go through their own dedicated
// endpoints (/api/personal/{id}/* etc.) — these are the generic
// stream-id-driven ones that don't require project context.

// ---------- Personal stream (Phase N) ----------

// Raw shape from the backend's route-proposal marker (see personal.py
// `_parse_route_proposal` + `_encode_route_proposal_body`).
export interface PersonalRouteTarget {
  user_id: string;
  username?: string;
  display_name: string;
  rationale?: string;
  // B-facing draft of the question, rewritten as if the source is
  // asking the target directly. The user can refine this in the
  // route-proposal card before sending; the refined text becomes the
  // routed signal's framing so B sees a clean A→B ask.
  b_facing_draft?: string;
}

export type DecisionClass =
  | "budget"
  | "legal"
  | "hire"
  | "scope_cut"
  | string;

export interface ConfirmRouteResponse {
  ok: boolean;
  signal_id: string;
}

export function confirmRouteProposal(
  proposalId: string,
  targetUserId: string,
  refinedFraming?: string | null,
): Promise<ConfirmRouteResponse> {
  // B.2: canonical routing-namespace confirm (was
  // /api/personal/route/{id}/confirm; that endpoint is deprecated and
  // removed once this is the only caller).
  return api<ConfirmRouteResponse>(
    `/api/routing/proposals/${proposalId}/confirm`,
    {
      method: "POST",
      body: {
        target_user_id: targetUserId,
        ...(refinedFraming && refinedFraming.trim()
          ? { refined_framing: refinedFraming.trim() }
          : {}),
      },
    },
  );
}

// ---------- Routing signals (Phase L) ----------

export interface RoutingBackgroundSnippet {
  source: string;
  snippet: string;
  reference_id?: string | null;
}

export interface RoutingOption {
  id: string;
  label: string;
  kind: string;
  background: string;
  reason: string;
  tradeoff: string;
  weight: number;
}

export interface RoutingSignal {
  id: string;
  trace_id: string | null;
  source_user_id: string;
  target_user_id: string;
  source_stream_id: string;
  target_stream_id: string;
  project_id: string;
  framing: string;
  background: RoutingBackgroundSnippet[];
  options: RoutingOption[];
  status: "pending" | "replied" | "accepted" | "declined" | "expired";
  reply: {
    option_id?: string | null;
    custom_text?: string | null;
    picked_label?: string | null;
    replied_at?: string | null;
  } | null;
  created_at: string | null;
  responded_at: string | null;
}

export function getRoutingSignal(
  signalId: string,
): Promise<{ ok: boolean; signal: RoutingSignal }> {
  return api<{ ok: boolean; signal: RoutingSignal }>(
    `/api/routing/${signalId}`,
  );
}

export interface RoutingReplyResponse {
  ok: boolean;
  signal: RoutingSignal;
}

export function replyRoutingSignal(
  signalId: string,
  params: { option_id?: string; custom_text?: string },
): Promise<RoutingReplyResponse> {
  return api<RoutingReplyResponse>(`/api/routing/${signalId}/reply`, {
    method: "POST",
    body: params,
  });
}

// Source-side accept persists the close-the-loop click. Without this
// the Accept button reappeared on every refresh because the local
// useState in RoutedReplyCard didn't survive the next /state pull.
export function acceptRoutingSignal(
  signalId: string,
): Promise<{ ok: boolean; signal: RoutingSignal }> {
  return api<{ ok: boolean; signal: RoutingSignal }>(
    `/api/routing/${signalId}/accept`,
    { method: "POST" },
  );
}

// ---------- Routing inbox / outbox (Phase Q — sidebar drawer) ----------
//
// Phase Q corrects the routed-inbound pattern: inbound signals no longer
// interrupt the personal stream. They surface as a badge in the global
// sidebar, resolved via a right-slide drawer. These helpers back the
// sidebar badge count + the drawer list.

export interface RoutingInboxResponse {
  signals: RoutingSignal[];
}

export function listRoutedInbox(
  params: {
    status?: "pending" | "replied" | "accepted" | "declined" | "expired";
    limit?: number;
  } = {},
  baseUrl?: string,
): Promise<RoutingInboxResponse> {
  const qs: string[] = [];
  if (params.status) qs.push(`status=${encodeURIComponent(params.status)}`);
  if (params.limit) qs.push(`limit=${params.limit}`);
  const q = qs.length ? `?${qs.join("&")}` : "";
  return api<RoutingInboxResponse>(`/api/routing/inbox${q}`, { baseUrl });
}

export function listRoutedOutbox(
  params: {
    status?: "pending" | "replied" | "accepted" | "declined" | "expired";
    limit?: number;
  } = {},
  baseUrl?: string,
): Promise<RoutingInboxResponse> {
  const qs: string[] = [];
  if (params.status) qs.push(`status=${encodeURIComponent(params.status)}`);
  if (params.limit) qs.push(`limit=${params.limit}`);
  const q = qs.length ? `?${qs.join("&")}` : "";
  return api<RoutingInboxResponse>(`/api/routing/outbox${q}`, { baseUrl });
}

// ---------- Knowledge base — re-exported from features/kb/api.ts ----------
//
// Phase D of the Architecture Organization Pass v1: the KB client now
// lives in `features/kb/api.ts`. We re-export every public symbol here
// so the ~14 existing call sites that import from `@/lib/api` keep
// working unchanged. Future passes will migrate import sites directly
// to `@/features/kb/api`; until then this shim is the public surface.
export type {
  KbItemStatus,
  KbItem,
  KbItemDetail,
  KbListParams,
  LicenseTier,
  KbFolderNode,
  KbTreeItem,
  KbTreeResponse,
} from "@/features/kb/api";
export {
  listProjectKb,
  getKbItem,
  getKbTree,
  createKbFolder,
  reparentKbFolder,
  deleteKbFolder,
  moveKbItem,
  setKbItemLicense,
} from "@/features/kb/api";

// ---------- Phase 1.B — ambient onboarding ----------

export type OnboardingCheckpoint =
  | "not_started"
  | "vision"
  | "decisions"
  | "teammates"
  | "your_tasks"
  | "open_risks"
  | "completed";

export interface OnboardingState {
  id: string;
  user_id: string;
  project_id: string;
  first_seen_at: string | null;
  walkthrough_started_at: string | null;
  walkthrough_completed_at: string | null;
  last_checkpoint: OnboardingCheckpoint;
  dismissed: boolean;
}

export function postOnboardingReplay(
  projectId: string,
): Promise<{ ok: boolean; state: OnboardingState }> {
  return api(
    `/api/projects/${projectId}/onboarding/replay`,
    { method: "POST" },
  );
}

// ---------- Gated proposals (migration 0014, Scene 2) ----------
//
// Backend: apps/api/src/workgraph_api/routers/gated_proposals.py. See
// the edge prompt v4 (`prompts/edge/v1.md` §"4b. route_kind: 'gated'")
// for when the edge agent emits a gated route (a separate, demoted path
// from the discovery route handled by `confirmRouteProposal`).

export type GatedProposalStatus =
  | "pending"
  | "approved"
  | "denied"
  | "withdrawn"
  | string;

export interface GatedProposal {
  id: string;
  project_id: string;
  proposer_user_id: string;
  gate_keeper_user_id: string;
  decision_class: DecisionClass;
  proposal_body: string;
  // v0.5 — raw user utterance. Null on pre-0015 rows + callers that
  // don't supply it (e.g. programmatic proposals).
  decision_text: string | null;
  apply_actions: Array<Record<string, unknown>>;
  status: GatedProposalStatus;
  resolution_note: string | null;
  // Phase S — populated when status transitions to 'in_vote'.
  // List of voter user_ids; threshold derived as floor(n/2)+1.
  // Null for proposals that never entered vote mode.
  voter_pool: string[] | null;
  trace_id: string | null;
  created_at: string;
  resolved_at: string | null;
}

// Phase S — cast a verdict on an in-vote proposal. Voters can change
// their verdict until the proposal resolves; upserts the VoteRow.
// `verdict ∈ {approve, deny, abstain}`.
export type VoteVerdict = "approve" | "deny" | "abstain";

// Phase S — unified sidebar inbox feed for the caller's gated
// workload. Returns both kinds mixed (sorted most-recent-first):
//   kind='gate-sign-off' — caller is the named gate-keeper on a
//                          status=pending proposal.
//   kind='vote-pending'  — caller is in voter_pool on a
//                          status=in_vote proposal. my_vote is
//                          non-null if they've already cast.

export type GatedInboxItemKind = "gate-sign-off" | "vote-pending";

export interface GatedInboxVote {
  verdict: VoteVerdict;
  rationale: string | null;
  updated_at: string | null;
}

export interface GatedInboxItem {
  kind: GatedInboxItemKind;
  created_at: string | null;
  proposal: GatedProposal;
  my_vote: GatedInboxVote | null;
}

// ---------- Organizations / Workspaces (Phase T) ----------
//
// The tier above project. Backend: routers/organizations.py. Slug is
// the URL key everywhere except create.

// FE-only helper union for inputs (invite/role-change selectors). The GET
// response `role` fields widen to plain string (runtime is an unconstrained
// membership column), so the generated types below carry string, not this union.
export type WorkspaceRole = "owner" | "admin" | "member" | "viewer";

export type WorkspaceDetail = components["schemas"]["WorkspaceDetail"];
export type WorkspaceMember = components["schemas"]["WorkspaceMember"];

export function inviteToWorkspace(
  slug: string,
  input: { username: string; role?: WorkspaceRole },
): Promise<{ ok: boolean; user_id: string; username: string; display_name: string; role: WorkspaceRole }> {
  return api(`/api/organizations/${slug}/invite`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

// Phase T — personal-task surface. The owner of a personal task can
// list their own + promote individually to the group plan via the
// membrane review pathway.

// ---------- KB notes — re-exported from features/kb/api.ts ----------
//
// See the earlier KB re-export block — same shim pattern. `saveMessageAsKb`
// remains in this file (it's a messaging helper that produces a KbNote).
export type {
  KbNoteScope,
  KbNoteStatus,
  KbNoteSource,
  KbNoteAttachment,
  KbNote,
} from "@/features/kb/api";
export {
  listKbNotes,
  getKbNote,
  createKbNote,
  updateKbNote,
  deleteKbNote,
  promoteKbNote,
  demoteKbNote,
  archiveKbNote,
  requestArchiveKb,
  uploadKbNote,
  kbAttachmentUrl,
} from "@/features/kb/api";
