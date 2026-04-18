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
  members: { user_id: string; username: string; display_name: string; role: string }[];
  conflicts: Conflict[];
  conflict_summary: ConflictSummary;
  decisions: Decision[];
  delivery: Delivery | null;
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
  conflict_id: string;
  project_id: string;
  resolver_id: string | null;
  option_index: number | null;
  custom_text: string | null;
  rationale: string;
  apply_actions: Record<string, unknown>[];
  apply_outcome: "pending" | "ok" | "partial" | "failed" | "advisory";
  apply_detail: Record<string, unknown>;
  created_at: string | null;
  applied_at: string | null;
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
