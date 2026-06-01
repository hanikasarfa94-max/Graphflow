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

// C1-C: generated-backed (GET /api/tasks response_model=TaskListResponse in
// routers/tasks_global.py, mirroring _serialize_task). Stable names preserved.
// The generated shape is the runtime truth — narrower than the old hand-written
// type, which marked scope_id/project_id/description/assignee_role nullable and
// status as the TaskStatus union; runtime makes those non-null TaskRow columns
// and status a plain string. TaskStatus stays exported as an FE helper union for
// status-comparison call sites.
import type { components } from "@/lib/api-types.gen";

export type TaskRow = components["schemas"]["TaskRow"];

export type TaskListResponse = components["schemas"]["TaskListResponse"];

export interface TaskDetailResponse {
  task: TaskRow;
}
