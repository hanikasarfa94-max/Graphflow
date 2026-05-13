// Feature-scoped types for the global Tasks surface (v0.6.2).
//
// Phase D scaffold (2026-05-13). These mirror the wire contract in
// graphflow_handoff_v062/API_CONTRACT.md §Tasks +
// graphflow_handoff_v062/schemas.graphflow.json (TaskStatus,
// TaskRecognitionPolicy). Phase D.2 will move the authoritative
// definitions into `@/lib/tasks` and this file will re-export.
//
// Doctrine surface — TaskRecognitionPolicy "none" is rejected at the
// API boundary on /promote (see apps/api/.../tasks_global.py:292). On
// the wire we still receive it for tasks that never had a candidate
// stage (owner-direct-create); the UI renders it as "no team gate."

// ── Enum mirrors (schemas.graphflow.json) ───────────────────────────

export type TaskRecognitionPolicy =
  | "none"
  | "assignee_accept"
  | "project_owner_confirm"
  | "flow_required"
  | "review_required";

// Full lifecycle. The Tasks surface groups rows by status in this
// order — see STATUS_GROUP_ORDER in TaskList.tsx.
export type TaskStatus =
  | "personal_draft"
  | "candidate"
  | "confirmation_pending"
  | "accepted_personal"
  | "team_confirmed"
  | "in_progress"
  | "blocked"
  | "waiting_for_feedback"
  | "ready_for_review"
  | "done"
  | "archived";

// ── List view selector ──────────────────────────────────────────────

export type TaskView = "my_tasks" | "all";

// ── Task row shape (mirrors _serialize_task in tasks_global.py) ─────

export interface TaskRow {
  id: string;
  scope_id: string; // v0.6.2 alias for project_id
  project_id: string;
  title: string;
  description: string | null;
  scope: string; // "personal" | "plan" (carrier-level)
  status: TaskStatus;
  owner_user_id: string;
  // v0.6.2 contract attaches a recognition policy per task. The B.1
  // wire shape doesn't carry it yet — D.2 widens TaskRow. We thread it
  // through the mock so the UI can render the badge end-to-end.
  recognition_policy: TaskRecognitionPolicy;
  // Display-only assignee surface. The B.1 row exposes
  // `assignee_role`; D.2 widens to a typed assignee object.
  assignee_display_name: string;
  assignee_id?: string;
  scope_label: string; // human-readable project label for the scope chip
  requirement_id: string | null;
  source_message_id: string | null;
  estimate_hours: number | null;
  created_at: string | null;
  // Inline updated_at so list rendering can sort newest-first without a
  // separate fetch. B.2 wire shape will carry this natively.
  updated_at?: string | null;
}

// ── Task detail (drawer / detail page) ──────────────────────────────

export interface TaskRelatedItem {
  kind: "doc" | "conversation" | "topic" | "task" | "decision" | "node";
  id: string;
  label: string;
  // Stable target URL — the link layer must NOT construct /projects/...
  // URLs (Phase A.4 cutover). Use /tasks/, /nodes/, /decisions/, /docs/.
  href: string;
}

export interface TaskEvidenceSource {
  kind: "conversation_message" | "document" | "flow_response";
  id: string;
  excerpt: string;
  author: string;
  timestamp: string;
}

export interface TaskAIAssistance {
  // Proposal-only per API_CONTRACT.md §"AI Assistance" — never
  // state-changing. Each entry is a button label + a hint string.
  label: string;
  hint: string;
}

export interface TaskDetail extends TaskRow {
  // Right-rail spine sections (schemas.graphflow.json §RightRailSpine).
  context_summary: string;
  related_work: TaskRelatedItem[];
  evidence_sources: TaskEvidenceSource[];
  ai_assistance: TaskAIAssistance[];
  // Primary action — the sticky CTA footer in the right rail. Per
  // FRONTEND_IMPLEMENTATION.md §"AI Assistance": "Sticky CTA footer
  // performs state-changing actions."
  primary_action_label: string;
}
