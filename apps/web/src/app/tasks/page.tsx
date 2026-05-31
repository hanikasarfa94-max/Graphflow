// /tasks — global task index.
//
// Phase RW-7 (2026-05-13): server-side fetches the live GET /api/tasks
// endpoint twice — once per view tab — and threads both payloads
// plus the user's active scope into the client feature. The Phase D
// useTasks mock is gone; no fabricated tasks, owners, or recognition
// policies survive in the rendered surface.

import { Tasks } from "@/features/tasks/Tasks";
import type { TaskListResponse } from "@/features/tasks/types";
import { requireUser, serverFetch } from "@/lib/auth";
import type { ActiveScope } from "@/lib/api";

export const dynamic = "force-dynamic";

async function loadActiveScope(): Promise<ActiveScope> {
  try {
    return await serverFetch<ActiveScope>("/api/user/active-scope");
  } catch {
    return { scope_id: null, scope_mode: "no_focus", updated_at: null };
  }
}

async function loadTasks(
  view: "my_tasks" | "all",
  scope_id: string | null,
): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  params.set("view", view);
  if (scope_id) params.set("scope_id", scope_id);
  try {
    return await serverFetch<TaskListResponse>(
      `/api/tasks?${params.toString()}`,
    );
  } catch {
    return { tasks: [], scope_id, view };
  }
}

export default async function TasksIndexPage() {
  await requireUser("/tasks");
  const active = await loadActiveScope();
  const scope_id =
    active.scope_mode === "current_focus" && active.scope_id
      ? active.scope_id
      : null;

  const [myTasks, allTasks] = await Promise.all([
    loadTasks("my_tasks", scope_id),
    loadTasks("all", scope_id),
  ]);

  return <Tasks myTasks={myTasks} allTasks={allTasks} scopeId={scope_id} />;
}
