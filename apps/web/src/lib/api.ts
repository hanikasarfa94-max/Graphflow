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

// ---------- Gated-proposal counterfactual ("if approved") ----------

export interface CounterfactualReassignment {
  task_id: string;
  task_title: string;
  from_user_id: string | null;
  from_display_name: string | null;
  to_user_id: string | null;
  to_display_name: string | null;
}

export interface CounterfactualEffectRef {
  id: string;
  title: string;
}

export interface CounterfactualMilestoneSlip {
  id: string;
  title: string;
  slip_days: number;
}

export interface Counterfactual {
  empty: boolean;
  reason: string | null;
  proposal_id: string;
  status: string;
  action_count: number;
  advisory_count: number;
  reassignments: CounterfactualReassignment[];
  unblocks: CounterfactualEffectRef[];
  blocks: CounterfactualEffectRef[];
  milestone_slips: CounterfactualMilestoneSlip[];
  total_effects: number;
  project_id?: string;
}

export async function getGatedProposalCounterfactual(
  proposalId: string,
): Promise<Counterfactual> {
  const res = await api<{ ok: true; counterfactual: Counterfactual }>(
    `/api/gated-proposals/${proposalId}/counterfactual`,
    { method: "GET" },
  );
  return res.counterfactual;
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
  // Phase 1.B — provenance chips for factual claims inside `body`.
  claims?: CitedClaim[];
  uncited?: boolean;
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

// ---------- Scrimmage (PLAN-v3 §2.B agent-vs-agent debate) ----------
//
// Triggered from the routing composer ("Try scrimmage first" toggle).
// The backend runs 2–3 turns of debate between the two sub-agents and
// returns a transcript + outcome. Shapes mirror `_shape()` in
// services/scrimmage.py.

export type ScrimmageStance =
  | "agree_with_other"
  | "propose_compromise"
  | "hold_position";

export type ScrimmageOutcome =
  | "converged_proposal"
  | "unresolved_crux"
  | "in_progress";

export interface ScrimmageTurn {
  turn: number;
  speaker: "source" | "target";
  text: string;
  stance: ScrimmageStance;
  proposal_summary: string | null;
  citations: CitedClaim[];
  confidence: "high" | "medium" | "low";
  recommend_route: boolean;
  rationale?: string;
}

export interface ScrimmageProposal {
  proposal_text: string | null;
  source_stance: ScrimmageStance | null;
  target_stance: ScrimmageStance | null;
  source_closing: string | null;
  target_closing: string | null;
  decision_id: string | null;
}

export interface ScrimmageResult {
  id: string;
  project_id: string;
  routed_signal_id: string | null;
  source_user_id: string;
  target_user_id: string;
  question_text: string;
  transcript: ScrimmageTurn[];
  outcome: ScrimmageOutcome;
  proposal: ScrimmageProposal | null;
  trace_id: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export function runScrimmage(
  projectId: string,
  targetUserId: string,
  questionText: string,
  routedSignalId?: string,
): Promise<ScrimmageResult> {
  return api<ScrimmageResult>(`/api/projects/${projectId}/scrimmages`, {
    method: "POST",
    body: {
      target_user_id: targetUserId,
      question_text: questionText,
      routed_signal_id: routedSignalId ?? null,
    },
  });
}

// ---------- Handoff (Stage 3 skill succession) ----------

export interface HandoffRoutine {
  skill: string;
  summary: string;
  evidence_count: number;
  applies_to_roles: string[];
  sources: string[];
}

export interface HandoffRecord {
  id: string;
  project_id: string;
  from_user_id: string;
  to_user_id: string;
  from_display_name: string;
  to_display_name: string;
  status: "draft" | "finalized";
  role_skills_transferred: string[];
  profile_skill_routines: HandoffRoutine[];
  brief_markdown: string;
  created_at: string;
  finalized_at: string | null;
}

export interface HandoffListPayload {
  viewer_scope: "owner" | "successor";
  handoffs: HandoffRecord[];
}

export interface SuccessorInheritedPayload {
  project_id: string;
  successor_user_id: string;
  inherited_role_skills: string[];
  inherited_routines: HandoffRoutine[];
  predecessors: {
    handoff_id: string;
    from_display_name: string;
    finalized_at: string | null;
  }[];
}

export function prepareHandoff(
  projectId: string,
  fromUserId: string,
  toUserId: string,
): Promise<{ ok: true; handoff: HandoffRecord }> {
  return api(`/api/projects/${projectId}/handoff/prepare`, {
    method: "POST",
    body: { from_user_id: fromUserId, to_user_id: toUserId },
  });
}

export function finalizeHandoff(
  handoffId: string,
): Promise<{ ok: true; handoff: HandoffRecord }> {
  return api(`/api/handoff/${handoffId}/finalize`, { method: "POST" });
}

export function listProjectHandoffs(
  projectId: string,
): Promise<HandoffListPayload> {
  return api(`/api/projects/${projectId}/handoffs`);
}

export function fetchSuccessorInherited(
  projectId: string,
  userId: string,
): Promise<SuccessorInheritedPayload> {
  return api(`/api/projects/${projectId}/handoffs/for/${userId}`);
}

// ---------- Dissent (Phase 2.A) ----------

export type DissentValidatedOutcome =
  | "supported"
  | "refuted"
  | "still_open"
  | null;

export interface DissentRecord {
  id: string;
  decision_id: string;
  dissenter_user_id: string;
  dissenter_display_name: string;
  stance_text: string;
  created_at: string;
  validated_by_outcome: DissentValidatedOutcome;
  outcome_evidence_ids: string[];
}

export function listDecisionDissents(
  projectId: string,
  decisionId: string,
  baseUrl?: string,
): Promise<{ ok: boolean; dissents: DissentRecord[] }> {
  return api(
    `/api/projects/${projectId}/decisions/${decisionId}/dissents`,
    { baseUrl },
  );
}

export function recordDissent(
  projectId: string,
  decisionId: string,
  stanceText: string,
): Promise<{ ok: boolean; dissent: DissentRecord }> {
  return api(`/api/projects/${projectId}/decisions/${decisionId}/dissents`, {
    method: "POST",
    body: { stance_text: stanceText },
  });
}

// ---------- Silent consensus (Phase 1.A) ----------

export interface SilentConsensusMember {
  user_id: string;
  display_name: string;
}

export interface SilentConsensusSupportingAction {
  kind: "task_status" | "decision" | "commit" | string;
  id: string;
}

export interface SilentConsensusProposal {
  id: string;
  project_id: string;
  topic_text: string;
  supporting_action_ids: SilentConsensusSupportingAction[];
  inferred_decision_summary: string;
  members: SilentConsensusMember[];
  member_user_ids: string[];
  confidence: number;
  status: "pending" | "ratified" | "rejected";
  created_at: string | null;
  ratified_decision_id: string | null;
  ratified_at: string | null;
}

export function listSilentConsensus(
  projectId: string,
  baseUrl?: string,
): Promise<{ ok: boolean; proposals: SilentConsensusProposal[] }> {
  return api(`/api/projects/${projectId}/silent-consensus`, { baseUrl });
}

export function ratifySilentConsensus(
  projectId: string,
  scId: string,
): Promise<{
  ok: boolean;
  proposal: SilentConsensusProposal;
  decision_id: string;
}> {
  return api(
    `/api/projects/${projectId}/silent-consensus/${scId}/ratify`,
    { method: "POST" },
  );
}

export function rejectSilentConsensus(
  projectId: string,
  scId: string,
): Promise<{ ok: boolean; proposal: SilentConsensusProposal }> {
  return api(
    `/api/projects/${projectId}/silent-consensus/${scId}/reject`,
    { method: "POST" },
  );
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
  // Phase S — lets the group-stream renderer switch on structural
  // kinds (vote-opened, vote-resolved-approved, vote-resolved-denied,
  // gated-proposal-resolved, …) and render typed cards instead of the
  // default chat bubble. Absent on pre-Phase-S cached rows.
  kind?: string;
  linked_id?: string | null;
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
  | "silent-consensus-proposal"
  // Migration 0014 — Scene 2 gated proposals. `-pending` lands in the
  // gate-keeper's stream with linked_id → gated_proposals.id;
  // `-resolved` lands in the proposer's stream after approve/deny.
  | "gated-proposal-pending"
  | "gated-proposal-resolved"
  | string;

// Raw shape from the backend's route-proposal marker (see personal.py
// `_parse_route_proposal` + `_encode_route_proposal_body`).
export interface PersonalRouteTarget {
  user_id: string;
  username?: string;
  display_name: string;
  rationale?: string;
}

// Phase R v1 — Scene 2 routing taxonomy. See
// packages/agents/src/workgraph_agents/prompts/edge/v1.md §"Output schema".
// Kept as a string union (not a Literal-cast'd enum) so a future
// backend that ships a new route kind doesn't crash the frontend.
export type RouteKind = "discovery" | "gated" | string;
export type DecisionClass =
  | "budget"
  | "legal"
  | "hire"
  | "scope_cut"
  | string;

export interface PersonalRouteProposalMetadata {
  framing: string;
  targets: PersonalRouteTarget[];
  background: Array<{
    source: string;
    snippet: string;
    reference_id?: string | null;
  }>;
  status: string;
  // Optional so older messages (before migration 0014) deserialize
  // cleanly. Default behavior for missing route_kind = "discovery".
  route_kind?: RouteKind;
  decision_class?: DecisionClass | null;
  // v0.5 — user's raw utterance; only populated for gated routes so
  // the gate-keeper card can render the literal text the proposer
  // committed to. Null for discovery routes and pre-0015 markers.
  decision_text?: string | null;
  // Phase S — true when the project has ≥2 authority holders for
  // this decision_class (owners ∪ gate_keeper). The proposer's card
  // renders an [🗳 Open to vote] affordance next to [Send for
  // sign-off]. Default false on pre-Phase-S markers.
  can_open_to_vote?: boolean;
}

// Phase 1.B — provenance chips for edge-LLM claims. `kind` mirrors
// the backend CitationKind taxonomy; string fallback keeps us
// forward-compatible when the backend adds node kinds.
export type CitationKind =
  | "decision"
  | "task"
  | "risk"
  | "deliverable"
  | "goal"
  | "milestone"
  | "commitment"
  | "wiki_page"
  | "kb"
  | string;

export interface Citation {
  node_id: string;
  kind: CitationKind;
}

export interface CitedClaim {
  text: string;
  citations: Citation[];
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
  // Phase 1.B — structured claims parsed out of the body marker.
  // Empty / missing means "no structured claims" (the body is rendered
  // as-is, muted).
  claims?: CitedClaim[];
  // True iff every claim has an empty `citations` list. Lets the UI
  // decide once per card whether to render muted.
  uncited?: boolean;
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
        // Phase 1.B — structured claims + uncited flag.
        claims?: CitedClaim[];
        uncited?: boolean;
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
  // Phase 1.B — preview carries the same claims/uncited shape so the
  // rehearsal card can show provenance chips before the user commits.
  claims?: CitedClaim[];
  uncited?: boolean;
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
      route_kind?: string;
      decision_class?: string | null;
      decision_text?: string | null;
      can_open_to_vote?: boolean;
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
      route_kind: parsed.route_kind ?? "discovery",
      decision_class: parsed.decision_class ?? null,
      decision_text: parsed.decision_text ?? null,
      can_open_to_vote: parsed.can_open_to_vote ?? false,
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

// ---------- Phase 3.A — hierarchical KB ----------
//
// Folder tree on top of the flat KB. The tree endpoint returns folders
// + items as two flat arrays with parent_id pointers; the client nests
// in memory. Cycle detection + per-item license override live on the
// backend (see apps/api/src/workgraph_api/services/kb_hierarchy.py).

export type LicenseTier = "full" | "task_scoped" | "observer";

export interface KbFolderNode {
  id: string;
  project_id: string;
  parent_folder_id: string | null;
  name: string;
  created_by_user_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface KbTreeItem {
  id: string;
  folder_id: string | null;
  title: string;
  summary: string;
  source_kind: string;
  source_identifier: string | null;
  status: KbItemStatus;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
  license_tier_override: LicenseTier | null;
  ingested_by_username: string | null;
}

export interface KbTreeResponse {
  ok: true;
  folders: KbFolderNode[];
  items: KbTreeItem[];
  root_id: string | null;
}

export function getKbTree(
  projectId: string,
  baseUrl?: string,
): Promise<KbTreeResponse> {
  return api<KbTreeResponse>(`/api/projects/${projectId}/kb/tree`, {
    baseUrl,
  });
}

export function createKbFolder(
  projectId: string,
  body: { name: string; parent_folder_id: string | null },
): Promise<{ ok: true; folder: KbFolderNode }> {
  return api(`/api/projects/${projectId}/kb/folders`, {
    method: "POST",
    body,
  });
}

export function reparentKbFolder(
  projectId: string,
  folderId: string,
  newParentId: string | null,
): Promise<{ ok: true; folder: KbFolderNode }> {
  return api(
    `/api/projects/${projectId}/kb/folders/${folderId}/parent`,
    { method: "PATCH", body: { new_parent_id: newParentId } },
  );
}

export function deleteKbFolder(
  projectId: string,
  folderId: string,
): Promise<{ ok: true; deleted_id: string }> {
  return api(`/api/projects/${projectId}/kb/folders/${folderId}`, {
    method: "DELETE",
  });
}

export function moveKbItem(
  projectId: string,
  itemId: string,
  folderId: string,
): Promise<{ ok: true; item_id: string; folder_id: string | null }> {
  return api(
    `/api/projects/${projectId}/kb/items/${itemId}/folder`,
    { method: "PATCH", body: { folder_id: folderId } },
  );
}

export function setKbItemLicense(
  projectId: string,
  itemId: string,
  licenseTier: LicenseTier | null,
): Promise<{
  ok: true;
  item_id: string;
  license_tier: LicenseTier | null;
}> {
  return api(
    `/api/projects/${projectId}/kb/items/${itemId}/license`,
    { method: "PUT", body: { license_tier: licenseTier } },
  );
}

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

export type OnboardingSectionKind =
  | "vision"
  | "decisions"
  | "teammates"
  | "your_tasks"
  | "open_risks";

export interface OnboardingSection {
  kind: OnboardingSectionKind;
  title: string;
  body_md: string;
  claims: CitedClaim[];
}

export interface OnboardingWalkthrough {
  sections: OnboardingSection[];
  user_id: string;
  project_id: string;
  generated_at: string;
  license_tier: string;
  scope_user_id: string;
}

export interface OnboardingWalkthroughResponse {
  state: OnboardingState;
  walkthrough: OnboardingWalkthrough;
  valid_checkpoints: OnboardingCheckpoint[];
}

export function getOnboardingWalkthrough(
  projectId: string,
  baseUrl?: string,
): Promise<OnboardingWalkthroughResponse> {
  return api<OnboardingWalkthroughResponse>(
    `/api/projects/${projectId}/onboarding/walkthrough`,
    { baseUrl },
  );
}

export function postOnboardingCheckpoint(
  projectId: string,
  checkpoint: OnboardingCheckpoint,
): Promise<{ ok: boolean; state: OnboardingState }> {
  return api(
    `/api/projects/${projectId}/onboarding/checkpoint`,
    { method: "POST", body: { checkpoint } },
  );
}

export function postOnboardingDismiss(
  projectId: string,
): Promise<{ ok: boolean; state: OnboardingState }> {
  return api(
    `/api/projects/${projectId}/onboarding/dismiss`,
    { method: "POST" },
  );
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
// for when the edge agent emits a gated route and the frontend hits
// `createGatedProposal` instead of `confirmRouteProposal`.

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

// Convenience: DECISION_CLASSES mirrors the backend enum. Use this in
// the settings editor (to iterate the allowed classes) instead of
// hard-coding strings at multiple call sites.
export const DECISION_CLASSES: DecisionClass[] = [
  "budget",
  "legal",
  "hire",
  "scope_cut",
];

export interface GatedProposalResponse {
  ok: boolean;
  proposal: GatedProposal;
  decision_id?: string;
}

export function createGatedProposal(
  projectId: string,
  input: {
    decision_class: DecisionClass;
    proposal_body: string;
    // v0.5 — user's raw utterance. Optional so programmatic callers
    // (scripts, tests without an edge-LLM turn) keep working; the
    // route-proposal card fills it in from the marker metadata.
    decision_text?: string | null;
    // Shape matches DecisionRow.apply_actions on the backend: list of
    // structured dicts. In v0 the edge-agent emits an empty list, but
    // the shape is preserved so Option 2 hardening (wiring to
    // DecisionService._apply) doesn't require a schema change here.
    apply_actions?: Array<Record<string, string | number | boolean | null>>;
  },
): Promise<GatedProposalResponse> {
  return api<GatedProposalResponse>(
    `/api/projects/${projectId}/gated-proposals`,
    {
      method: "POST",
      body: {
        decision_class: input.decision_class,
        proposal_body: input.proposal_body,
        decision_text: input.decision_text ?? null,
        apply_actions: input.apply_actions ?? [],
      },
    },
  );
}

export function approveGatedProposal(
  proposalId: string,
  rationale?: string,
): Promise<GatedProposalResponse> {
  return api<GatedProposalResponse>(
    `/api/gated-proposals/${proposalId}/approve`,
    {
      method: "POST",
      body: { rationale: rationale ?? null },
    },
  );
}

// Phase S — open a pending single-approver proposal to a vote-mode
// resolution. The caller must be the proposer, a project owner, or
// the named gate-keeper; voter pool must be ≥ 2. On success the
// proposal transitions to status='in_vote' and voters get inbox cards.
export function openGatedProposalToVote(
  proposalId: string,
  rationale?: string,
): Promise<{
  ok: boolean;
  proposal: GatedProposal;
  threshold: number;
}> {
  return api(
    `/api/gated-proposals/${proposalId}/open-to-vote`,
    {
      method: "POST",
      body: { rationale: rationale ?? null },
    },
  );
}

// Phase S — cast a verdict on an in-vote proposal. Voters can change
// their verdict until the proposal resolves; upserts the VoteRow.
// `verdict ∈ {approve, deny, abstain}`.
export type VoteVerdict = "approve" | "deny" | "abstain";

export function castGatedProposalVote(
  proposalId: string,
  input: { verdict: VoteVerdict; rationale?: string },
): Promise<{
  ok: boolean;
  proposal: GatedProposal;
  tally: {
    approve: number;
    deny: number;
    abstain: number;
    outstanding: number;
    pool_size: number;
    threshold: number;
  };
  resolved_as: "approved" | "denied" | null;
  decision_id: string | null;
}> {
  return api(
    `/api/gated-proposals/${proposalId}/votes`,
    {
      method: "POST",
      body: {
        verdict: input.verdict,
        rationale: input.rationale ?? null,
      },
    },
  );
}

export function denyGatedProposal(
  proposalId: string,
  resolutionNote?: string,
): Promise<GatedProposalResponse> {
  return api<GatedProposalResponse>(
    `/api/gated-proposals/${proposalId}/deny`,
    {
      method: "POST",
      body: { resolution_note: resolutionNote ?? null },
    },
  );
}

export function withdrawGatedProposal(
  proposalId: string,
): Promise<GatedProposalResponse> {
  return api<GatedProposalResponse>(
    `/api/gated-proposals/${proposalId}/withdraw`,
    { method: "POST" },
  );
}

export function listGatedProposalsForProject(
  projectId: string,
  status?: GatedProposalStatus,
): Promise<{ ok: boolean; proposals: GatedProposal[] }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return api<{ ok: boolean; proposals: GatedProposal[] }>(
    `/api/projects/${projectId}/gated-proposals${qs}`,
  );
}

export function listPendingGatedProposalsForMe(): Promise<{
  ok: boolean;
  proposals: GatedProposal[];
}> {
  return api<{ ok: boolean; proposals: GatedProposal[] }>(
    `/api/gated-proposals/pending`,
  );
}

export function getGatedProposal(
  proposalId: string,
): Promise<{ ok: boolean; proposal: GatedProposal }> {
  return api<{ ok: boolean; proposal: GatedProposal }>(
    `/api/gated-proposals/${proposalId}`,
  );
}

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

export function listGatedInbox(
  opts: { limit?: number } = {},
): Promise<{ ok: boolean; items: GatedInboxItem[] }> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return api<{ ok: boolean; items: GatedInboxItem[] }>(
    `/api/inbox/gated${qs}`,
  );
}

export interface TallySnapshot {
  approve: number;
  deny: number;
  abstain: number;
  outstanding: number;
  pool_size: number;
  threshold: number | null;
  votes: Array<{
    voter_user_id: string;
    verdict: VoteVerdict;
    rationale: string | null;
    created_at: string | null;
    updated_at: string | null;
  }>;
}

export function getGatedProposalTally(
  proposalId: string,
): Promise<TallySnapshot> {
  return api<TallySnapshot>(`/api/gated-proposals/${proposalId}/tally`);
}

// ---------- Gate-keeper map (per-project Scene 2 settings) ----------

export interface GateKeeperMapResponse {
  ok: boolean;
  map: Record<string, string>;
  valid_classes: string[];
}

export function getGateKeeperMap(
  projectId: string,
): Promise<GateKeeperMapResponse> {
  return api<GateKeeperMapResponse>(
    `/api/projects/${projectId}/gate-keeper-map`,
  );
}

export function putGateKeeperMap(
  projectId: string,
  map: Record<string, string>,
): Promise<{ ok: boolean; map: Record<string, string> }> {
  return api<{ ok: boolean; map: Record<string, string> }>(
    `/api/projects/${projectId}/gate-keeper-map`,
    {
      method: "PUT",
      body: { map },
    },
  );
}
