// Feature-scoped types for the global Tasks surface (v0.6.2).
//
// Phase RW-7 (2026-05-13): shapes pruned to match the live wire from
// _serialize_task in apps/api/.../tasks_global.py. The Phase D scaffold
// types had fabricated fields (recognition_policy, assignee_display_name,
// scope_label) that the BE doesn't emit yet; carrying them would make
// the FE look more capable than it is. Removed.

export type TaskRecognitionPolicy =
  | "none"
  | "assignee_accept"
  | "project_owner_confirm"
  | "flow_required"
  | "review_required";

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
  | "archived"
  | "pending"
  | (string & {});

export type TaskView = "my_tasks" | "all";

export interface TaskRow {
  id: string;
  scope_id: string | null;
  project_id: string | null;
  title: string;
  description: string | null;
  scope: string;
  status: TaskStatus;
  owner_user_id: string | null;
  requirement_id: string | null;
  source_message_id: string | null;
  assignee_role: string | null;
  estimate_hours: number | null;
  created_at: string | null;
}

export interface TaskListResponse {
  tasks: TaskRow[];
  scope_id: string | null;
  view: TaskView;
}

export interface TaskDetailResponse {
  task: TaskRow;
}
