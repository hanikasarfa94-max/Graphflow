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

// Topbar project-switcher fetch. Same shape as the server-rendered
// /projects list; the difference is calling context (client component
// loading on dropdown open).
export function fetchMyProjects(
  baseUrl?: string,
): Promise<ProjectSummary[]> {
  return api<ProjectSummary[]>("/api/projects", { baseUrl });
}

export interface ProjectMember {
  user_id: string;
  username: string | null;
  display_name: string | null;
  role: string;
  license_tier?: "full" | "task_scoped" | "observer";
  skill_tags?: string[];
}

// Lightweight members fetch used by the workbench Skills panel.
// Distinct from /state (which is a full graph snapshot) so the
// Skills panel doesn't pay for goals + risks + decisions on every open.
export function fetchProjectMembers(
  projectId: string,
  baseUrl?: string,
): Promise<ProjectMember[]> {
  return api<ProjectMember[]>(`/api/projects/${projectId}/members`, {
    baseUrl,
  });
}

export interface GraphNode {
  id: string;
  title: string;
  [k: string]: unknown;
}

export interface ProjectState {
  project: { id: string; title: string };
  requirement_version: number;
  // Phase membrane-reorg follow-up — surfaces requirement.budget_hours
  // so owners can edit it inline; the membrane's task_promote review
  // uses the value for the estimate-overflow check.
  requirement_id: string | null;
  budget_hours: number | null;
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
    // Per-project functional skill tags (frontend/backend/qa/etc).
    // Drives the membrane's task_promote assignee-coverage check.
    // Members can self-edit; owners can edit anyone.
    skill_tags?: string[];
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

// Phase S — team-level rollup of observed governance + activity. Only
// populated in the owner view (empty object for non-owner). All ratios
// are bounded to [0, 1] for easy UI rendering. The UI renders this as
// a "how does this team think" summary stripe next to the skill
// collective block.
export interface SkillAtlasTeamShape {
  member_count?: number;
  total_votes_30d?: number;
  total_approve_30d?: number;
  total_deny_30d?: number;
  total_abstain_30d?: number;
  total_decisions_30d?: number;
  total_messages_30d?: number;
  total_routings_30d?: number;
  active_voters_30d?: number;
  active_deciders_30d?: number;
  vote_participation_ratio?: number;
  decision_participation_ratio?: number;
  // 1.0 = one-person-show, ~1/N = fully distributed.
  decision_concentration?: number;
  // Fraction of casts that were deny + abstain. High = team votes
  // critically; low = rubber-stamp.
  dissent_mix?: number;
}

export interface SkillAtlasPayload {
  viewer_scope: "owner" | "self";
  members: SkillAtlasMemberCard[];
  collective: SkillAtlasCollective;
  team_shape?: SkillAtlasTeamShape;
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
  // Set true when the question demands a real-time human judgment the
  // sub-agent cannot pre-know (allocation, scheduling, capacity calls).
  // RouteProposalCard floats "Manual answer" to position 1 when set.
  human_answer_demand?: boolean;
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
  // Resolved name for the resolver_id (display_name || username), so
  // the dashboard doesn't have to render UUIDs. Null when the user
  // was deleted (resolver_id set to null on user delete).
  resolver_display_name?: string | null;
  option_index: number | null;
  custom_text: string | null;
  rationale: string;
  apply_actions?: Record<string, unknown>[];
  apply_outcome?: "pending" | "ok" | "partial" | "failed" | "advisory";
  apply_detail?: Record<string, unknown>;
  source_suggestion_id: string | null;
  // Scene 2 routing provenance — set when the decision came from a
  // gated proposal (gate-keeper sign-off → crystallize). Null for
  // IM-suggestion-originated or conflict-originated decisions.
  gated_via_proposal_id?: string | null;
  decision_class?: string | null;
  // Smallest-relevant-vote scope — set when the decision crystallized
  // from a message inside a specific room (B3 + pickup #6). Null for
  // legacy decisions and decisions from team-room messages. The room
  // view reads this to render the "Voting with <room>'s <N> members"
  // explainer on DecisionCard.
  scope_stream_id?: string | null;
  // N.4 — current vote tally + scope-derived quorum. Backend
  // enriches every decision payload with this (REST + WS upserts) so
  // the FE can render the tally without a follow-up GET.
  tally?: DecisionTally;
  created_at: string | null;
  applied_at: string | null;
}

// N.4 vote tally shape — emitted by DecisionVoteService.
export interface DecisionTally {
  approve: number;
  deny: number;
  abstain: number;
  cast: number;
  outstanding: number;
  quorum: number;
  majority: number;
  // 'open' = vote in progress; 'passed'/'failed' = majority reached;
  // 'tied' = full participation, no majority. The frontend should
  // render the badge differently per status.
  status: "open" | "passed" | "failed" | "tied";
  scope_kind: "room" | "project";
  scope_stream_id: string | null;
}

// Decision vote record. (VoteVerdict is defined further down in this
// file under the gated-proposals section — same shape, reused here.)
export interface DecisionVoteRecord {
  id: string;
  verdict: "approve" | "deny" | "abstain";
  rationale: string | null;
  voter_user_id: string;
  created_at: string | null;
  updated_at: string | null;
}

// GET response: my_vote may be null when the viewer hasn't voted yet.
export interface DecisionTallyResponse {
  tally: DecisionTally;
  my_vote: DecisionVoteRecord | null;
}

// POST response: my_vote is always populated (we just cast it).
export interface DecisionVoteCastResponse {
  tally: DecisionTally;
  my_vote: DecisionVoteRecord;
}

export function castDecisionVote(
  decisionId: string,
  body: { verdict: "approve" | "deny" | "abstain"; rationale?: string },
): Promise<DecisionVoteCastResponse> {
  return api<DecisionVoteCastResponse>(
    `/api/decisions/${decisionId}/votes`,
    {
      method: "POST",
      body,
    },
  );
}

export function getDecisionTally(
  decisionId: string,
): Promise<DecisionTallyResponse> {
  return api<DecisionTallyResponse>(`/api/decisions/${decisionId}/votes`);
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

export function listStreams(baseUrl?: string): Promise<{ streams: StreamSummary[] }> {
  return api<{ streams: StreamSummary[] }>(`/api/streams`, { baseUrl });
}

export function markStreamRead(streamId: string): Promise<unknown> {
  return api(`/api/streams/${streamId}/read`, { method: "POST" });
}

// v-next AgentFlow uses these directly. Existing PersonalStream /
// RoomStreamTimeline code paths still go through their own dedicated
// endpoints (/api/personal/{id}/* etc.) — these are the generic
// stream-id-driven ones that don't require project context.

export interface StreamMessage {
  id: string;
  stream_id: string;
  project_id: string | null;
  author_id: string;
  author_username: string | null;
  body: string;
  kind: string;
  linked_id: string | null;
  created_at: string;
}

export function listStreamMessages(
  streamId: string,
  opts: { limit?: number } = {},
): Promise<{ messages: StreamMessage[] }> {
  const q = opts.limit ? `?limit=${opts.limit}` : "";
  return api<{ messages: StreamMessage[] }>(
    `/api/streams/${streamId}/messages${q}`,
  );
}

export function postStreamMessage(
  streamId: string,
  body: string,
): Promise<{ ok: boolean } & StreamMessage> {
  return api(`/api/streams/${streamId}/messages`, {
    method: "POST",
    body: { body },
  });
}

// ---------- v-Next user preferences (E-6 / E-7 / E-9) ----------

export type VNextThinkingMode = "deep" | "fast";
export type VNextStreamKind = "personal" | "room" | "dm";
export type VNextPanelKind =
  | "tasks"
  | "knowledge"
  | "skills"
  | "requests"
  | "workflow";

export interface VNextPrefs {
  // E-6: per-stream override for the composer's auto-dispatch toggle.
  // Default is on — keys are present only for streams the user has
  // explicitly disabled.
  auto_dispatch_streams: Record<string, boolean>;
  // E-7: user's last-selected thinking-mode hint.
  thinking_mode: VNextThinkingMode;
  // E-9: per-stream-kind panel composition (order + presence).
  workbench_layout: Record<VNextStreamKind, VNextPanelKind[]>;
}

export function fetchVNextPrefs(): Promise<VNextPrefs> {
  return api("/api/vnext/prefs");
}

export interface VNextPrefsUpdate {
  thinking_mode?: VNextThinkingMode;
  auto_dispatch?: { stream_id: string; enabled: boolean };
  workbench?: { stream_kind: VNextStreamKind; panels: VNextPanelKind[] };
}

export function updateVNextPrefs(
  body: VNextPrefsUpdate,
): Promise<VNextPrefs> {
  return api("/api/vnext/prefs", {
    method: "PUT",
    body: body as unknown as JsonValue,
  });
}

// ---------- v-Next related-entities (E-5 analysisCard) ----------

export interface VNextRelatedTask {
  id: string;
  title: string;
  status: string;
  scope: string;
  assignee_role: string | null;
}

export interface VNextRelatedDecision {
  id: string;
  title: string;
  outcome: string;
  decision_class: string | null;
}

export interface VNextRelatedRisk {
  id: string;
  title: string;
  severity: string;
  status: string;
}

export interface VNextRelated {
  tasks: VNextRelatedTask[];
  decisions: VNextRelatedDecision[];
  risks: VNextRelatedRisk[];
}

export function fetchVNextRelated(streamId: string): Promise<VNextRelated> {
  return api(`/api/vnext/streams/${streamId}/related`);
}

// ---------- Room timeline (room-stream slice) ----------

// Discriminated union of timeline rows the room view renders.
// Mirrors RoomTimelineService.get_timeline output exactly. The
// frontend dispatcher (RoomStreamTimeline) switches on `kind`. Future
// kinds (`task`, `kb_item`) are reserved by the backend but only
// schema-typed here so adding their renderers later is a frontend-
// only change.
export type TimelineMessageItem = {
  kind: "message";
  id: string;
  stream_id: string;
  project_id: string;
  author_id: string;
  author_username: string | null;
  body: string;
  // Renamed away from `kind` to avoid clashing with the discriminator.
  kind_message: string;
  linked_id: string | null;
  created_at: string | null;
};

export type TimelineSuggestionItem = {
  kind: "im_suggestion";
  id: string;
  project_id: string;
  message_id: string;
  status: "pending" | "accepted" | "dismissed" | "countered" | "escalated";
  kind_suggestion: string;
  confidence: number | null;
  targets: unknown[];
  proposal: Record<string, unknown> | null;
  reasoning: string;
  decision_id: string | null;
  counter_of_id: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

export type TimelineDecisionItem = {
  kind: "decision";
  id: string;
  project_id: string;
  conflict_id: string | null;
  source_suggestion_id: string | null;
  resolver_id: string | null;
  rationale: string;
  custom_text: string | null;
  scope_stream_id: string | null;
  apply_outcome:
    | "pending"
    | "ok"
    | "partial"
    | "failed"
    | "advisory"
    | null;
  // N.4 — tally enriched at the timeline endpoint.
  tally?: DecisionTally;
  created_at: string | null;
  applied_at: string | null;
};

export type TimelineItem =
  | TimelineMessageItem
  | TimelineSuggestionItem
  | TimelineDecisionItem;

// Canonical WS event shape for room broadcasts. The reducer applies
// these via one switch over `event.type` — same wire shape backs both
// the inline timeline and the workbench `Requests` projection. The
// `kind` discriminator on the item identifies which entity type the
// event refers to, so `update` and `delete` events can patch any
// projection without specialized handlers.
export type RoomTimelineEvent =
  | { type: "timeline.upsert"; item: TimelineItem }
  | {
      type: "timeline.update";
      kind: TimelineItem["kind"];
      id: string;
      patch: Record<string, unknown>;
    }
  | {
      type: "timeline.delete";
      kind: TimelineItem["kind"];
      id: string;
    };

export interface RoomTimelineSnapshot {
  stream_id: string;
  project_id: string;
  items: TimelineItem[];
}

// GET /api/projects/{projectId}/rooms/{roomId}/timeline
// Snapshot for the room view; the WS channel reconciles incremental
// updates over /ws/streams/{roomId}.
export function getRoomTimeline(
  projectId: string,
  roomId: string,
  options: { limit?: number; baseUrl?: string } = {},
): Promise<RoomTimelineSnapshot> {
  const { limit, baseUrl } = options;
  const qs = limit ? `?limit=${limit}` : "";
  return api<RoomTimelineSnapshot>(
    `/api/projects/${projectId}/rooms/${roomId}/timeline${qs}`,
    { baseUrl },
  );
}

// GET /api/projects/{projectId}/rooms — list all rooms in a cell.
// Returns the rooms array shape the new RoomTimelineSnapshot pulls
// stream_id from for navigation / scope-name resolution.
export interface RoomSummary extends StreamSummary {
  type: "room";
  name: string | null;
}

export function listProjectRooms(
  projectId: string,
  baseUrl?: string,
): Promise<{ rooms: RoomSummary[] }> {
  return api<{ rooms: RoomSummary[] }>(
    `/api/projects/${projectId}/rooms`,
    { baseUrl },
  );
}

export interface CreateRoomResponse {
  ok: true;
  stream: RoomSummary;
}

// POST /api/projects/{projectId}/rooms — create a new room.
// Backend validates the creator is a project member and that every
// listed member is also a project member. Returns the new RoomSummary
// (with persisted name, members list, etc.).
export function createRoom(
  projectId: string,
  body: { name: string; member_user_ids: string[] },
): Promise<CreateRoomResponse> {
  return api<CreateRoomResponse>(`/api/projects/${projectId}/rooms`, {
    method: "POST",
    body,
  });
}

// GET /api/projects/{projectId}/im_suggestions?stream_id=...
// Used by the workbench `Requests` panel as a fallback / refresh path
// when the WS reducer state needs reconciliation. Day-to-day the panel
// derives from useRoomTimeline.items.filter(kind === 'im_suggestion'
// && status === 'pending').
export interface IMSuggestionListResponse {
  suggestions: Array<Record<string, unknown>>;
}

export function listIMSuggestions(
  projectId: string,
  options: { streamId?: string; limit?: number; baseUrl?: string } = {},
): Promise<IMSuggestionListResponse> {
  const { streamId, limit, baseUrl } = options;
  const params = new URLSearchParams();
  if (streamId) params.set("stream_id", streamId);
  if (limit) params.set("limit", String(limit));
  const qs = params.toString();
  return api<IMSuggestionListResponse>(
    `/api/projects/${projectId}/im_suggestions${qs ? `?${qs}` : ""}`,
    { baseUrl },
  );
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
  /** IMSuggestion kind for AI-generated signals, or `"routing"` for an
   *  unanswered peer routing inbox item. The home renders both in the
   *  same "needs your response" list so the count aligns with the
   *  sidebar inbox badge. */
  kind: IMSuggestion["kind"] | "routing";
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
  // B-facing draft of the question, rewritten as if the source is
  // asking the target directly. The user can refine this in the
  // route-proposal card before sending; the refined text becomes the
  // routed signal's framing so B sees a clean A→B ask.
  b_facing_draft?: string;
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
  scope?: Record<string, boolean> | null,
  scopeTiers?: Record<string, boolean> | null,
): Promise<PersonalPostResponse> {
  // Two orthogonal narrowings ride on this POST:
  //   * scope        — StreamContextPanel: which kinds of source (graph/kb/dms/audit)
  //   * scope_tiers  — ScopeTierPills:    which license tiers (personal/group/department/enterprise)
  // Both are forward-compat fields the server logs for debug; consumer
  // wiring (LicenseContextService.allowed_scopes intersect) lands in N.4.
  const payload = {
    body,
    ...(scope ? { scope } : {}),
    ...(scopeTiers ? { scope_tiers: scopeTiers } : {}),
  };
  return api<PersonalPostResponse>(`/api/personal/${projectId}/post`, {
    method: "POST",
    body: payload,
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
  refinedFraming?: string | null,
): Promise<ConfirmRouteResponse> {
  return api<ConfirmRouteResponse>(
    `/api/personal/route/${proposalId}/confirm`,
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

// Promote a stream message into a group-scope KB (wiki) draft. Manual
// trigger today; the backend reuses the same code path the future
// edge-agent auto-classifier will call so the system has one entry
// point regardless of who initiated the save.
export function saveMessageAsKb(
  projectId: string,
  messageId: string,
): Promise<{ ok: boolean; item: KbNote; source_message_id: string }> {
  return api<{ ok: boolean; item: KbNote; source_message_id: string }>(
    `/api/projects/${projectId}/messages/${messageId}/save-as-kb`,
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

// Two status vocabularies share the kb_items table post-fold:
//   * ingest rows (source='ingest')      — pending-review|approved|rejected|routed
//   * user-authored (manual/upload/llm)  — draft|published|archived
// Both are valid wherever a KB item appears. Renderer code switches on
// status to show the right chip; the backend doesn't enforce per-source
// transitions at the type system level.
export type KbItemStatus =
  | "pending-review"
  | "approved"
  | "rejected"
  | "routed"
  | "draft"
  | "published"
  | "archived";

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
  // User-authored shape — populated for save-as-kb / paste / upload
  // (source in {'manual','upload','llm'}). Null for ingest rows. The
  // BE _kb_detail_payload emits both shapes from the unified
  // kb_items table; the FE picks whichever is populated.
  title?: string | null;
  content_md?: string | null;
  scope?: string | null;
  source?: string | null;
  owner_user_id?: string | null;
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

export async function getKbItem(
  projectId: string,
  itemId: string,
  baseUrl?: string,
): Promise<KbItemDetail> {
  // BE returns `{ok: true, item: KbItemDetail}` — unwrap so callers get
  // the row directly. (Previously this helper claimed to return
  // KbItemDetail but actually resolved to the wrapper, leaving every
  // field undefined; the route page worked around it with a hand-typed
  // serverFetch. Keeping the helper honest prevents that landmine
  // recurring in any future caller.)
  const res = await api<{ ok: boolean; item: KbItemDetail }>(
    `/api/projects/${projectId}/kb/${itemId}`,
    { baseUrl },
  );
  return res.item;
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
  // KbItemRow.scope wire value — one of "personal" / "group" / "department"
  // / "enterprise". Used by ScopeTierPills to filter the tree client-side
  // (the backend access guard still enforces what the user can read at all).
  scope: string;
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

// ---------- Organizations / Workspaces (Phase T) ----------
//
// The tier above project. Backend: routers/organizations.py. Slug is
// the URL key everywhere except create.

export type WorkspaceRole = "owner" | "admin" | "member" | "viewer";

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  owner_user_id: string;
  description: string | null;
  created_at: string | null;
}

export interface WorkspaceWithRole extends WorkspaceSummary {
  role: WorkspaceRole;
}

export interface WorkspaceProject {
  id: string;
  title: string;
  updated_at: string | null;
}

export interface WorkspaceDetail extends WorkspaceWithRole {
  projects: WorkspaceProject[];
}

export interface WorkspaceMember {
  user_id: string;
  username: string;
  display_name: string;
  role: WorkspaceRole;
  invited_by_user_id: string | null;
  created_at: string | null;
}

export function createWorkspace(input: {
  name: string;
  slug: string;
  description?: string;
}): Promise<WorkspaceSummary> {
  return api<WorkspaceSummary>(`/api/organizations`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function listMyWorkspaces(
  baseUrl?: string,
): Promise<WorkspaceWithRole[]> {
  return api<WorkspaceWithRole[]>(`/api/organizations`, { baseUrl });
}

export function getWorkspace(
  slug: string,
  baseUrl?: string,
): Promise<WorkspaceDetail> {
  return api<WorkspaceDetail>(`/api/organizations/${slug}`, { baseUrl });
}

export function listWorkspaceMembers(
  slug: string,
  baseUrl?: string,
): Promise<WorkspaceMember[]> {
  return api<WorkspaceMember[]>(`/api/organizations/${slug}/members`, {
    baseUrl,
  });
}

export function inviteToWorkspace(
  slug: string,
  input: { username: string; role?: WorkspaceRole },
): Promise<{ ok: boolean; user_id: string; username: string; display_name: string; role: WorkspaceRole }> {
  return api(`/api/organizations/${slug}/invite`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function updateWorkspaceMemberRole(
  slug: string,
  userId: string,
  role: WorkspaceRole,
): Promise<{ ok: boolean; user_id: string; role: WorkspaceRole }> {
  return api(`/api/organizations/${slug}/members/${userId}`, {
    method: "PATCH",
    body: { role },
  });
}

export function removeWorkspaceMember(
  slug: string,
  userId: string,
): Promise<{ ok: boolean; user_id: string }> {
  return api(`/api/organizations/${slug}/members/${userId}`, {
    method: "DELETE",
  });
}

export function attachProjectToWorkspace(
  slug: string,
  projectId: string,
): Promise<{ ok: boolean; project_id: string; organization_id: string; slug: string }> {
  return api(
    `/api/organizations/${slug}/projects/${projectId}/attach`,
    { method: "POST" },
  );
}

// ---------- Task progress (Phase U — status self-report + scoring) ----

export type TaskStatusValue =
  | "open"
  | "in_progress"
  | "blocked"
  | "done"
  | "canceled";

export type TaskQuality = "good" | "ok" | "needs_work";

export interface TaskStatusUpdateRecord {
  id: string;
  actor_user_id: string;
  actor_display_name: string | null;
  old_status: string | null;
  new_status: string;
  note: string | null;
  created_at: string | null;
}

export interface TaskScoreRecord {
  quality: TaskQuality;
  feedback: string | null;
  reviewer_user_id: string;
  assignee_user_id: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskHistoryPayload {
  task_id: string;
  current_status: string;
  updates: TaskStatusUpdateRecord[];
  score: TaskScoreRecord | null;
}

export function updateTaskStatus(
  taskId: string,
  input: { new_status: TaskStatusValue; note?: string },
): Promise<{ ok: boolean; status: string; old_status?: string; no_op?: boolean }> {
  return api(`/api/tasks/${taskId}/status`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function scoreTask(
  taskId: string,
  input: { quality: TaskQuality; feedback?: string },
): Promise<{
  ok: boolean;
  quality: TaskQuality;
  feedback: string | null;
  assignee_user_id: string;
  reviewer_user_id: string;
  created: boolean;
}> {
  return api(`/api/tasks/${taskId}/score`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function fetchTaskHistory(
  taskId: string,
  baseUrl?: string,
): Promise<TaskHistoryPayload> {
  return api(`/api/tasks/${taskId}/history`, { baseUrl });
}

// Phase T — personal-task surface. The owner of a personal task can
// list their own + promote individually to the group plan via the
// membrane review pathway.

export type TaskScope = "plan" | "personal";

export interface PersonalTask {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  scope: TaskScope;
  status: string;
  owner_user_id: string | null;
  requirement_id: string | null;
  source_message_id: string | null;
  assignee_role: string | null;
  created_at: string | null;
}

export function fetchPersonalTasks(
  projectId: string,
  baseUrl?: string,
): Promise<{ ok: true; tasks: PersonalTask[] }> {
  return api(`/api/projects/${projectId}/personal-tasks`, { baseUrl });
}

export interface CreatePersonalTaskInput {
  title: string;
  description?: string;
  source_message_id?: string | null;
  estimate_hours?: number | null;
  assignee_role?: string | null;
}

export function createPersonalTask(
  projectId: string,
  body: CreatePersonalTaskInput,
): Promise<{ ok: true; task: PersonalTask }> {
  return api(`/api/projects/${projectId}/tasks`, {
    method: "POST",
    body: body as unknown as JsonValue,
  });
}

// Subjective decision crystallization — user identifies a message as
// decision-shaped and bypasses the auto-classifier. Idempotent on the
// backend; safe to retry. Returns the suggestion (existing or new).
export interface ProposeDecisionResponse {
  ok: true;
  suggestion: {
    id: string;
    project_id: string;
    message_id: string;
    kind: string;
    status: string;
    confidence: number;
    [k: string]: unknown;
  };
}

export function proposeDecisionFromMessage(
  messageId: string,
  body: { rationale?: string } = {},
): Promise<ProposeDecisionResponse> {
  return api(`/api/messages/${messageId}/propose_decision`, {
    method: "POST",
    body: body as unknown as JsonValue,
  });
}

export interface PromoteTaskResponse {
  ok: true;
  task: PersonalTask | null;
  deferred?: boolean;
  reason?: string;
  diff_summary?: string | null;
}

export function promoteTask(taskId: string): Promise<PromoteTaskResponse> {
  return api(`/api/tasks/${taskId}/promote`, { method: "POST" });
}

export function setRequirementBudget(
  projectId: string,
  requirementId: string,
  budgetHours: number | null,
): Promise<{ ok: true; requirement_id: string; budget_hours: number | null }> {
  return api(
    `/api/projects/${projectId}/requirements/${requirementId}/budget`,
    {
      method: "PATCH",
      body: { budget_hours: budgetHours },
    },
  );
}

export function setMemberSkills(
  projectId: string,
  userId: string,
  skillTags: string[],
): Promise<{ ok: true; user_id: string; skill_tags: string[] }> {
  return api(`/api/projects/${projectId}/members/${userId}/skills`, {
    method: "PATCH",
    body: { skill_tags: skillTags },
  });
}

// Batch C — membrane notes panel surface. Lists the project's
// outstanding membrane work: drafts waiting for owner review, and
// recent clarification questions waiting for proposer answers.
export interface MembraneReviewNote {
  id: string;
  message_id: string;
  kind: string;
  proposal: {
    action?: string;
    summary?: string;
    detail?: {
      candidate_kind?: string;
      kb_item_id?: string;
      task_id?: string;
      diff_summary?: string | null;
      conflict_with?: string[];
    };
  } | null;
  reasoning: string | null;
  created_at: string | null;
}
export interface MembraneClarifyNote {
  id: string;
  linked_id: string | null;
  body: string;
  stream_id: string | null;
  created_at: string | null;
}
export interface MembraneNotesResponse {
  ok: true;
  pending_reviews: MembraneReviewNote[];
  pending_clarifications: MembraneClarifyNote[];
}
export function fetchMembraneNotes(
  projectId: string,
  baseUrl?: string,
): Promise<MembraneNotesResponse> {
  return api(`/api/projects/${projectId}/membrane/notes`, { baseUrl });
}

// ---------- KB items (Phase V — manual-write notes) -------------------

export type KbNoteScope = "personal" | "group";
export type KbNoteStatus = "draft" | "published" | "archived";
export type KbNoteSource = "manual" | "upload" | "llm";

export interface KbNoteAttachment {
  filename: string;
  mime: string;
  bytes: number;
  download_url: string;
}

export interface KbNote {
  id: string;
  project_id: string;
  folder_id: string | null;
  owner_user_id: string;
  scope: KbNoteScope;
  title: string;
  content_md: string;
  status: KbNoteStatus;
  source: KbNoteSource;
  attachment: KbNoteAttachment | null;
  created_at: string | null;
  updated_at: string | null;
}

export function listKbNotes(
  projectId: string,
  baseUrl?: string,
): Promise<{ ok: boolean; items: KbNote[] }> {
  return api(`/api/projects/${projectId}/kb-items`, { baseUrl });
}

export function getKbNote(
  itemId: string,
  baseUrl?: string,
): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}`, { baseUrl });
}

export function createKbNote(
  projectId: string,
  input: {
    title: string;
    content_md?: string;
    scope?: KbNoteScope;
    folder_id?: string;
    source?: KbNoteSource;
    status?: KbNoteStatus;
  },
): Promise<KbNote> {
  return api(`/api/projects/${projectId}/kb-items`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function updateKbNote(
  itemId: string,
  input: {
    title?: string;
    content_md?: string;
    status?: KbNoteStatus;
    folder_id?: string | null;
  },
): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}`, {
    method: "PATCH",
    body: input as unknown as JsonValue,
  });
}

export function deleteKbNote(
  itemId: string,
): Promise<{ ok: boolean; deleted_id: string }> {
  return api(`/api/kb-items/${itemId}`, { method: "DELETE" });
}

export function promoteKbNote(itemId: string): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}/promote`, { method: "POST" });
}

export function demoteKbNote(itemId: string): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}/demote`, { method: "POST" });
}

// Phase B — file upload. Multipart, so we don't go through the
// JSON `api` helper. Browser sets Content-Type with boundary.
export async function uploadKbNote(
  projectId: string,
  input: { file: File; title?: string; scope?: KbNoteScope; folderId?: string },
): Promise<KbNote> {
  const fd = new FormData();
  fd.append("file", input.file);
  if (input.title) fd.append("title", input.title);
  if (input.scope) fd.append("scope", input.scope);
  if (input.folderId) fd.append("folder_id", input.folderId);
  const res = await fetch(
    `/api/projects/${projectId}/kb-items/upload`,
    { method: "POST", credentials: "include", body: fd, cache: "no-store" },
  );
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    throw new ApiError(res.status, body, `upload ${res.status}`);
  }
  return body as KbNote;
}

// Download URL for an attached file. Component can use as <a href>.
export function kbAttachmentUrl(itemId: string): string {
  return `/api/kb-items/${itemId}/attachment`;
}
