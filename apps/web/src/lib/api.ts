// Fetch wrapper. All calls go through /api/* which Next rewrites to the
// FastAPI backend (see next.config.mjs). Same-origin → the session cookie
// flows automatically. Throws `ApiError` on non-2xx so callers can
// distinguish 401/403/404 from a network error.

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

type JsonValue =
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

export interface User {
  id: string;
  username: string;
  display_name: string;
  created_at: string;
}

export interface ProjectSummary {
  id: string;
  title: string;
  role: string;
  updated_at: string | null;
}

export interface GraphNode {
  id: string;
  title: string;
  [k: string]: unknown;
}

export interface ProjectState {
  project: { id: string; title: string };
  requirement_version: number;
  parsed: Record<string, unknown>;
  parse_outcome: string | null;
  graph: {
    goals: GraphNode[];
    deliverables: (GraphNode & { kind?: string; status?: string })[];
    constraints: {
      id: string;
      kind: string;
      content: string;
      severity: string;
      status: string;
    }[];
    risks: {
      id: string;
      title: string;
      content: string;
      severity: string;
      status: string;
    }[];
  };
  plan: {
    tasks: {
      id: string;
      title: string;
      description: string;
      deliverable_id: string | null;
      assignee_role: string | null;
      estimate_hours: number | null;
      acceptance_criteria: string[];
      status: string;
    }[];
    dependencies: { id: string; from_task_id: string; to_task_id: string }[];
    milestones: {
      id: string;
      title: string;
      target_date: string | null;
      related_task_ids: string[];
      status: string;
    }[];
  };
  clarifications: {
    id: string;
    position: number;
    question: string;
    answer: string | null;
  }[];
  assignments: Record<string, unknown>[];
  members: {
    user_id: string;
    username: string;
    display_name: string;
    role: string;
    license_tier?: "full" | "task_scoped" | "observer";
  }[];
  conflicts: Conflict[];
  conflict_summary: ConflictSummary;
  decisions: Decision[];
  delivery: Delivery | null;
  commitments: Commitment[];
  // Sprint 3c — license-scoped view. Present on every /state response
  // so the frontend can render a banner when the viewer is seeing a
  // filtered subgraph. Defaults to "full" when absent (older backend).
  viewer_license_tier?: "full" | "task_scoped" | "observer";
}

// ---------- Commitments (Sprint 2a — thesis-commit primitive) ----------

export type CommitmentStatus = "open" | "met" | "missed" | "withdrawn";

export type CommitmentScopeKind =
  | "task"
  | "deliverable"
  | "goal"
  | "milestone";

export interface Commitment {
  id: string;
  project_id: string;
  created_by_user_id: string;
  owner_user_id: string | null;
  headline: string;
  target_date: string | null;
  metric: string | null;
  scope_ref_kind: CommitmentScopeKind | null;
  scope_ref_id: string | null;
  status: CommitmentStatus;
  source_message_id: string | null;
  sla_window_seconds: number | null;
  sla_last_escalated_at: string | null;
  created_at: string | null;
  resolved_at: string | null;
}

export interface CreateCommitmentParams {
  headline: string;
  owner_user_id?: string;
  target_date?: string; // ISO8601
  metric?: string;
  scope_ref_kind?: CommitmentScopeKind;
  scope_ref_id?: string;
  source_message_id?: string;
  sla_window_seconds?: number;
}

export function createCommitment(
  projectId: string,
  params: CreateCommitmentParams,
): Promise<{ ok: boolean; commitment: Commitment }> {
  return api(`/api/projects/${projectId}/commitments`, {
    method: "POST",
    body: params as unknown as JsonValue,
  });
}

export function listCommitments(
  projectId: string,
  opts: { status?: CommitmentStatus; limit?: number } = {},
  baseUrl?: string,
): Promise<{ commitments: Commitment[] }> {
  const qs: string[] = [];
  if (opts.status) qs.push(`status=${encodeURIComponent(opts.status)}`);
  if (opts.limit) qs.push(`limit=${opts.limit}`);
  const q = qs.length ? `?${qs.join("&")}` : "";
  return api(`/api/projects/${projectId}/commitments${q}`, { baseUrl });
}

export function setCommitmentStatus(
  commitmentId: string,
  status: CommitmentStatus,
): Promise<{ ok: boolean; commitment: Commitment }> {
  return api(`/api/commitments/${commitmentId}/status`, {
    method: "PATCH",
    body: { status },
  });
}

// ---------- Counterfactual simulation (/simulate) ----------

export type SimulationKind = "drop_task";

export interface SimulationAffected {
  id: string;
  kind: "task" | "deliverable" | "milestone" | "commitment";
  title: string;
  reason: string;
}

export interface SimulationResult {
  kind: SimulationKind;
  entity_kind: "task";
  entity_id: string;
  dropped: SimulationAffected[];
  orphan_tasks: SimulationAffected[];
  slipping_milestones: SimulationAffected[];
  exposed_deliverables: SimulationAffected[];
  at_risk_commitments: SimulationAffected[];
  total_blast_radius: number;
}

export function simulateDropTask(
  projectId: string,
  taskId: string,
): Promise<SimulationResult> {
  return api(`/api/projects/${projectId}/simulate`, {
    method: "POST",
    body: { kind: "drop_task", entity_kind: "task", entity_id: taskId },
  });
}

// ---------- Skill atlas (/projects/[id]/skills) ----------

export interface SkillAtlasMemberCard {
  user_id: string;
  username: string;
  display_name: string;
  project_role: string;
  role_hints: string[];
  role_skills: string[];
  profile_skills_declared: string[];
  profile_skills_observed: string[];
  profile_skills_validated: string[];
  observed_tallies: Record<string, number>;
  last_activity_at: string | null;
}

export interface SkillAtlasCollective {
  role_skill_coverage?: string[];
  declared_abilities_combined?: string[];
  observed_skills_combined?: string[];
  unvalidated_declarations?: string[];
}

export interface SkillAtlasPayload {
  viewer_scope: "owner" | "self";
  members: SkillAtlasMemberCard[];
  collective: SkillAtlasCollective;
}

export function fetchSkillAtlas(
  projectId: string,
  baseUrl?: string,
): Promise<SkillAtlasPayload> {
  return api(`/api/projects/${projectId}/skills`, { baseUrl });
}

// ---------- Pre-answer routing (Stage 2) ----------
//
// Sender's UI asks target's edge: "given their skills, what would they
// say?" The pre-answer lets the sender decide whether they even need to
// interrupt the human. If confidence is high and the answer stands on
// its own, the sender can cancel the route and save the target's time.

export interface PreAnswerDraft {
  body: string;
  confidence: "high" | "medium" | "low";
  matched_skills: string[];
  uncovered_topics: string[];
  recommend_route: boolean;
  rationale: string;
}

export interface PreAnswerTargetSummary {
  user_id: string;
  display_name: string;
  project_role: string;
  role_skills: string[];
  declared_abilities: string[];
  validated_skills: string[];
}

export interface PreAnswerPayload {
  ok: true;
  draft: PreAnswerDraft;
  target: PreAnswerTargetSummary;
  meta: {
    outcome: "ok" | "retry" | "manual_review";
    attempts: number;
  };
}

export function fetchPreAnswer(
  projectId: string,
  targetUserId: string,
  question: string,
): Promise<PreAnswerPayload> {
  return api<PreAnswerPayload>(`/api/projects/${projectId}/pre-answer`, {
    method: "POST",
    body: { target_user_id: targetUserId, question },
  });
}

export interface ConflictOption {
  label: string;
  detail: string;
  impact?: string;
}

export interface Conflict {
  id: string;
  project_id: string;
  rule: string;
  severity: "critical" | "high" | "medium" | "low";
  status: "open" | "stale" | "resolved" | "dismissed";
  targets: string[];
  detail: Record<string, unknown>;
  summary: string;
  options: ConflictOption[];
  explanation_outcome: string | null;
  explanation_prompt_version: string | null;
  resolved_option_index: number | null;
  resolved_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  resolved_at: string | null;
}

export interface ConflictSummary {
  open: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

export interface Decision {
  id: string;
  conflict_id: string | null;
  project_id: string;
  resolver_id: string | null;
  option_index: number | null;
  custom_text: string | null;
  rationale: string;
  apply_actions: Record<string, unknown>[];
  apply_outcome: "pending" | "ok" | "partial" | "failed" | "advisory";
  apply_detail: Record<string, unknown>;
  source_suggestion_id: string | null;
  created_at: string | null;
  applied_at: string | null;
}

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
  kind: "none" | "tag" | "decision" | "blocker";
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
  created_at: string;
  suggestion?: IMSuggestion | null;
}

export interface CounterSuggestionResponse {
  original_suggestion: IMSuggestion;
  new_message: IMMessage;
  new_suggestion: IMSuggestion | null;
}

export function counterSuggestion(
  suggestionId: string,
  text: string,
): Promise<CounterSuggestionResponse> {
  return api<CounterSuggestionResponse>(
    `/api/im_suggestions/${suggestionId}/counter`,
    { method: "POST", body: { text } },
  );
}

export function escalateSuggestion(
  suggestionId: string,
): Promise<IMSuggestion> {
  return api<IMSuggestion>(
    `/api/im_suggestions/${suggestionId}/escalate`,
    { method: "POST" },
  );
}

export function acceptSuggestion(suggestionId: string): Promise<unknown> {
  return api(`/api/im_suggestions/${suggestionId}/accept`, { method: "POST" });
}

export function dismissSuggestion(suggestionId: string): Promise<unknown> {
  return api(`/api/im_suggestions/${suggestionId}/dismiss`, { method: "POST" });
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
  type: "project" | "dm";
  project_id: string | null;
  members: StreamMemberSummary[];
  last_activity_at: string | null;
  created_at: string | null;
  unread_count: number;
}

export function listStreams(baseUrl?: string): Promise<{ streams: StreamSummary[] }> {
  return api<{ streams: StreamSummary[] }>(`/api/streams`, { baseUrl });
}

export function markStreamRead(streamId: string): Promise<unknown> {
  return api(`/api/streams/${streamId}/read`, { method: "POST" });
}

// Create-or-get the canonical 1:1 DM stream between the authed user and
// `otherUserId`. Backend dedups by sorted member pair, so repeated calls
// return the same stream. Response mirrors StreamSummary under `stream`.
export interface CreateDMResponse {
  ok: boolean;
  created: boolean;
  stream: StreamSummary;
}

export function createDMStream(
  otherUserId: string,
): Promise<CreateDMResponse> {
  return api<CreateDMResponse>(`/api/streams/dm`, {
    method: "POST",
    body: { other_user_id: otherUserId },
  });
}

// ---------- Home-specific helpers (Phase F) ----------

// Fetch the most recent messages for a project along with their attached
// suggestions. Used by the home page to derive pending signals without a
// dedicated /api/users/me/pending endpoint.
export function listProjectMessages(
  projectId: string,
  baseUrl?: string,
): Promise<{ messages: IMMessage[] }> {
  return api<{ messages: IMMessage[] }>(
    `/api/projects/${projectId}/messages?limit=200`,
    { baseUrl },
  );
}

// A "pending signal" for the home page. Phase F §1: derived client-side
// by scanning suggestions across all project streams the viewer belongs
// to and filtering status === 'pending' whose `targets` list references
// the viewer. Since targets are free-form strings from IMAssist we match
// generously against user_id, username, and display_name.
export interface PendingSignal {
  suggestion_id: string;
  message_id: string;
  project_id: string;
  project_title: string;
  summary: string;
  kind: IMSuggestion["kind"];
  created_at: string;
  jump_href: string;
}

export interface DeliveryCompletedItem {
  scope_item: string;
  evidence_task_ids: string[];
}

export interface DeliveryDeferredItem {
  scope_item: string;
  reason: string;
  decision_id: string | null;
}

export interface DeliveryKeyDecision {
  decision_id: string;
  headline: string;
  rationale: string;
}

export interface DeliveryRemainingRisk {
  title: string;
  content: string;
  severity: "low" | "medium" | "high";
}

export interface DeliveryEvidence {
  milestones: string[];
  conflicts_resolved: string[];
  assignments: string[];
}

export interface DeliveryContent {
  headline: string;
  narrative: string;
  completed_scope: DeliveryCompletedItem[];
  deferred_scope: DeliveryDeferredItem[];
  key_decisions: DeliveryKeyDecision[];
  remaining_risks: DeliveryRemainingRisk[];
  evidence: DeliveryEvidence;
}

export interface DeliveryQaReport {
  scope_items: string[];
  covered: Record<string, string[]>;
  uncovered: string[];
  deferred_via_decision: string[];
  agent_outcome: string;
  agent_attempts: number;
  agent_error: string | null;
}

export interface Delivery {
  id: string;
  project_id: string;
  requirement_version: number;
  content: DeliveryContent;
  parse_outcome: "ok" | "retry" | "manual_review";
  qa_report: DeliveryQaReport;
  prompt_version: string | null;
  trace_id: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface EventRow {
  id: string;
  name: string;
  trace_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

// ---------- Time-cursor (Sprint 1b) ----------

// /graph-at returns a payload shaped like ProjectState for the subset
// the time-cursor cares about — graph, plan, decisions, conflicts. Fields
// that aren't time-scoped (assignments, members, parsed, delivery) are
// echoed as empty so the GraphCanvas swap is drop-in. `as_of` carries
// the resolved timestamp so the UI can label the pill precisely.
export interface GraphAtState extends ProjectState {
  as_of: string;
}

// Timeline metadata for the scrubber strip: bounds + markers. Markers
// are keyed by kind so the strip can render each with its own glyph.
export interface TimelineTransition {
  id: string;
  entity_kind: string;
  entity_id: string;
  old_status: string | null;
  new_status: string;
  changed_at: string;
}

export interface TimelineDecision {
  id: string;
  created_at: string | null;
  rationale: string;
}

export interface TimelineConflict {
  id: string;
  rule: string;
  severity: string;
  created_at: string | null;
  resolved_at: string | null;
}

export interface TimelineResponse {
  project_id: string;
  created_at: string; // project birth — left bound of the slider
  now: string; // server clock — right bound (Live)
  transitions: TimelineTransition[];
  decisions: TimelineDecision[];
  conflicts: TimelineConflict[];
}

export function fetchGraphAt(
  projectId: string,
  ts: string,
): Promise<GraphAtState> {
  const q = new URLSearchParams({ ts }).toString();
  return api<GraphAtState>(`/api/projects/${projectId}/graph-at?${q}`);
}

export function fetchTimeline(
  projectId: string,
  baseUrl?: string,
): Promise<TimelineResponse> {
  return api<TimelineResponse>(`/api/projects/${projectId}/timeline`, {
    baseUrl,
  });
}

// ---------- Org graph (Sprint 3a) ----------

// The org-graph payload is the "meta-graph" above a single project:
// the center is whatever project the user is currently viewing; peers
// are the other projects the user belongs to; edges link center ↔ peer
// when those projects share at least one member. Backend lives in
// apps/api/src/workgraph_api/services/org_graph.py — keep this type in
// lockstep with the dict returned there.
export interface OrgGraphPeer {
  id: string;
  title: string;
  role: string;
  member_count: number;
  open_risks: number;
  last_activity_at: string | null;
}

export interface OrgGraphEdge {
  from_project_id: string;
  to_project_id: string;
  // "shared_member" in v1; the schema is open so v2 can add
  // "shared_decision" without breaking existing clients.
  kind: string;
  weight: number;
  shared_users: string[];
}

export interface OrgGraphPayload {
  center: { id: string; title: string };
  peers: OrgGraphPeer[];
  edges: OrgGraphEdge[];
}

export function fetchOrgGraph(projectId: string): Promise<OrgGraphPayload> {
  return api<OrgGraphPayload>(`/api/projects/${projectId}/org-graph`);
}

// ---------- Personal stream (Phase N) ----------

// Messages posted into a user's personal project stream. The backend
// tags structured turns with `kind` and optionally `linked_id` so the
// renderer can polymorphically dispatch to rich cards (route proposal,
// routed inbound, routed reply, edge answer/clarify). Unknown kinds
// must render as plain text for forward-compat.
export type PersonalMessageKind =
  | "text"
  | "edge-answer"
  | "edge-clarify"
  | "edge-thinking"
  | "edge-route-proposal"
  | "edge-route-confirmed"
  | "edge-reply-frame"
  | "edge-tool-call"
  | "edge-tool-result"
  | "routed-inbound"
  | "routed-reply"
  | "routed-dm-log"
  | "drift-alert"
  | "membrane-signal"
  | string;

// Raw shape from the backend's route-proposal marker (see personal.py
// `_parse_route_proposal` + `_encode_route_proposal_body`).
export interface PersonalRouteTarget {
  user_id: string;
  username?: string;
  display_name: string;
  rationale?: string;
}

export interface PersonalRouteProposalMetadata {
  framing: string;
  targets: PersonalRouteTarget[];
  background: Array<{
    source: string;
    snippet: string;
    reference_id?: string | null;
  }>;
  status: string;
}

export interface PersonalMessage {
  id: string;
  stream_id: string;
  project_id: string | null;
  author_id: string;
  author_username?: string | null;
  author_display_name?: string | null;
  body: string;
  kind: PersonalMessageKind;
  linked_id: string | null;
  created_at: string;
  // Present on edge-route-proposal messages — backend parses the marker
  // server-side. The body has already had the marker stripped.
  route_proposal?: PersonalRouteProposalMetadata;
}

// edge_response.kind uses the EdgeAgent response kinds (not the stored
// message kinds). We normalise to PersonalMessageKind when inserting
// optimistic cards. See personal.py PersonalStreamService.post.
export type EdgeResponseKind =
  | "silence"
  | "answer"
  | "clarify"
  | "route_proposal";

export interface PersonalPostResponse {
  ok: boolean;
  message_id: string;
  edge_response:
    | {
        kind: EdgeResponseKind;
        body: string | null;
        reply_message_id?: string;
        route_proposal_id?: string;
        targets?: PersonalRouteTarget[];
      }
    | null;
}

// Convert an EdgeAgent response kind into the stored stream-message kind.
export function edgeKindToMessageKind(
  kind: EdgeResponseKind,
): PersonalMessageKind | null {
  if (kind === "answer") return "edge-answer";
  if (kind === "clarify") return "edge-clarify";
  if (kind === "route_proposal") return "edge-route-proposal";
  return null; // silence → no card
}

export function postPersonalMessage(
  projectId: string,
  body: string,
): Promise<PersonalPostResponse> {
  return api<PersonalPostResponse>(`/api/personal/${projectId}/post`, {
    method: "POST",
    body: { body },
  });
}

export function listPersonalMessages(
  projectId: string,
): Promise<{ stream_id: string; messages: PersonalMessage[] }> {
  return api<{ stream_id: string; messages: PersonalMessage[] }>(
    `/api/personal/${projectId}/messages`,
  );
}

export interface ConfirmRouteResponse {
  ok: boolean;
  signal_id: string;
}

export function confirmRouteProposal(
  proposalId: string,
  targetUserId: string,
): Promise<ConfirmRouteResponse> {
  return api<ConfirmRouteResponse>(
    `/api/personal/route/${proposalId}/confirm`,
    {
      method: "POST",
      body: { target_user_id: targetUserId },
    },
  );
}

// ---------- Pre-commit rehearsal (vision.md §5.3) ----------
//
// Debounced keystroke call to /api/personal/{id}/preview. Returns the
// EdgeAgent classification the draft *would* produce, without persisting
// anything. The frontend renders this above the composer so users see
// how their message will be classified (answer / clarify / route) and
// can reframe before committing.

// silent_preview: draft too short for a real classification; the card
// should render nothing. Other kinds mirror EdgeResponseKind.
export type RehearsalKind =
  | "silent_preview"
  | "silence"
  | "answer"
  | "clarify"
  | "route_proposal";

export interface RehearsalPreview {
  kind: RehearsalKind;
  body?: string | null;
  reasoning?: string;
  targets?: PersonalRouteTarget[];
}

export interface PreviewResponse {
  ok: boolean;
  preview: RehearsalPreview;
}

export async function previewPersonalMessage(
  projectId: string,
  body: string,
  signal?: AbortSignal,
): Promise<PreviewResponse> {
  return api<PreviewResponse>(`/api/personal/${projectId}/preview`, {
    method: "POST",
    body: { body },
    signal,
  });
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

// Counter-back: source user replies to a target's reply by dispatching a
// new routed signal back to the same target. For v1 we reuse
// /api/routing/dispatch. The `framing` argument carries the source-side
// follow-up framing. We stamp the parent signal id into a background
// snippet so the target can visually trace the chain until the backend
// exposes a parent_signal_id column.
export interface CounterBackParams {
  target_user_id: string;
  project_id: string;
  framing: string;
  parent_signal_id?: string;
}

export function dispatchCounterBack(
  params: CounterBackParams,
): Promise<{ ok: boolean; signal_id: string }> {
  const background = params.parent_signal_id
    ? [
        {
          source: "routing",
          snippet: `Counter-back to signal ${params.parent_signal_id}`,
          reference_id: params.parent_signal_id,
        },
      ]
    : [];
  return api<{ ok: boolean; signal_id: string }>(`/api/routing/dispatch`, {
    method: "POST",
    body: {
      target_user_id: params.target_user_id,
      project_id: params.project_id,
      framing: params.framing,
      background,
      options: [],
    },
  });
}

// Fallback parser for the `<route-proposal>{...}</route-proposal>` body
// marker. The backend already strips + parses this into `route_proposal`
// metadata; this helper exists so a missing-metadata payload (older API
// build, partial response) still produces a usable card.
export function parseRouteProposalFromBody(
  body: string,
): PersonalRouteProposalMetadata | null {
  const match = body.match(
    /<route-proposal>\s*(\{[\s\S]*?\})\s*<\/route-proposal>/,
  );
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[1]) as {
      framing?: string;
      targets?: Array<{
        user_id?: string;
        username?: string;
        display_name?: string;
        rationale?: string;
      }>;
      background?: PersonalRouteProposalMetadata["background"];
      status?: string;
    };
    const targets = (parsed.targets ?? [])
      .filter(
        (t): t is PersonalRouteTarget =>
          typeof t.user_id === "string" &&
          typeof t.display_name === "string",
      )
      .map((t) => ({
        user_id: t.user_id,
        username: t.username,
        display_name: t.display_name,
        rationale: t.rationale,
      }));
    return {
      framing: parsed.framing ?? "",
      targets,
      background: parsed.background ?? [],
      status: parsed.status ?? "pending",
    };
  } catch {
    return null;
  }
}

// Strip the route-proposal marker — backend pre-strips but we keep this
// as a safety net for cached/raw bodies.
export function stripRouteProposalMarker(body: string): string {
  return body
    .replace(/<route-proposal>[\s\S]*?<\/route-proposal>/g, "")
    .trim();
}

// ---------- Rendered artifacts (Phase R) ----------

export interface RenderedSection {
  heading: string;
  body_markdown: string;
}

export interface PostmortemDocShape {
  title: string;
  one_line_summary: string;
  sections: RenderedSection[];
}

export interface HandoffDocShape {
  title: string;
  sections: RenderedSection[];
}

export interface RenderedArtifact<TDoc> {
  kind: "postmortem" | "handoff";
  project_id: string;
  user_id: string | null;
  doc: TDoc;
  generated_at: string;
  prompt_version: string | null;
  outcome: "ok" | "retry" | "manual_review";
  attempts: number;
  error: string | null;
}

export type PostmortemRender = RenderedArtifact<PostmortemDocShape>;
export type HandoffRender = RenderedArtifact<HandoffDocShape>;

export function getPostmortemRender(
  projectId: string,
  baseUrl?: string,
): Promise<PostmortemRender> {
  return api<PostmortemRender>(
    `/api/projects/${projectId}/renders/postmortem`,
    { baseUrl },
  );
}

export function regeneratePostmortemRender(
  projectId: string,
): Promise<PostmortemRender> {
  return api<PostmortemRender>(
    `/api/projects/${projectId}/renders/postmortem/regenerate`,
    { method: "POST" },
  );
}

export function getHandoffRender(
  projectId: string,
  userId: string,
  baseUrl?: string,
): Promise<HandoffRender> {
  return api<HandoffRender>(
    `/api/projects/${projectId}/renders/handoff/${userId}`,
    { baseUrl },
  );
}

export function regenerateHandoffRender(
  projectId: string,
  userId: string,
): Promise<HandoffRender> {
  return api<HandoffRender>(
    `/api/projects/${projectId}/renders/handoff/${userId}/regenerate`,
    { method: "POST" },
  );
}

// ---------- Knowledge base (Phase Q.6) ----------
//
// Browseable KB surface. Backend endpoints:
//   GET /api/projects/{id}/kb               → list (optional query/source_kind/limit)
//   GET /api/projects/{id}/kb/{item_id}     → single item + raw_content
//
// The KB corpus is primarily LLM-facing (routing, retrieval, citations),
// but per `docs/north-star.md` §Q.6 the user-facing browse/search page
// ships in v1 so humans can audit what the edge LLM is grounded on. The
// listing endpoint may 404 while Phase Q-A is in flight — callers must
// catch `ApiError` with `status === 404` and render a "coming soon" state
// rather than propagating the failure.

export type KbItemStatus = "pending-review" | "approved" | "rejected" | "routed";

export interface KbItem {
  id: string;
  source_kind: string;
  source_identifier: string | null;
  summary: string;
  tags: string[];
  status: KbItemStatus;
  created_at: string;
  ingested_by_user_id: string | null;
  ingested_by_username?: string;
}

export interface KbItemDetail extends KbItem {
  raw_content: string;
  classification_json?: Record<string, unknown> | null;
}

export interface KbListParams {
  query?: string;
  source_kind?: string;
  limit?: number;
}

function buildKbQuery(params?: KbListParams): string {
  if (!params) return "";
  const q = new URLSearchParams();
  if (params.query && params.query.trim()) q.set("query", params.query.trim());
  if (params.source_kind && params.source_kind !== "all") {
    q.set("source_kind", params.source_kind);
  }
  if (params.limit) q.set("limit", String(params.limit));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listProjectKb(
  projectId: string,
  params?: KbListParams,
  baseUrl?: string,
): Promise<{ items: KbItem[] }> {
  return api<{ items: KbItem[] }>(
    `/api/projects/${projectId}/kb${buildKbQuery(params)}`,
    { baseUrl },
  );
}

export function getKbItem(
  projectId: string,
  itemId: string,
  baseUrl?: string,
): Promise<KbItemDetail> {
  return api<KbItemDetail>(
    `/api/projects/${projectId}/kb/${itemId}`,
    { baseUrl },
  );
}
