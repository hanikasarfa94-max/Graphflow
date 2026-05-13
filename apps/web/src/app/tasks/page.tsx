// /tasks — global task index.
//
// Phase D scaffold (2026-05-13). Replaces the Phase A.1 placeholder
// stub with the real Tasks feature body. Tasks are global; the
// scope_id query param filters to a project.
//
// API surface (Phase B + D.2):
//   GET  /api/tasks?scope_id=...&view=my_tasks|all
//   POST /api/tasks/candidates
//   POST /api/tasks/:id/promote   (requires TaskRecognitionPolicy)
//
// TaskRecognitionPolicy enum (schemas.graphflow.json):
//   "none" | "assignee_accept" | "project_owner_confirm"
//   | "flow_required" | "review_required"
//
// TaskStatus enum (full lifecycle): personal_draft → candidate →
// confirmation_pending → accepted_personal → team_confirmed → in_progress
// → blocked → waiting_for_feedback → ready_for_review → done → archived

import { Tasks } from "@/features/tasks/Tasks";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function TasksIndexPage() {
  await requireUser("/tasks");
  return <Tasks />;
}
