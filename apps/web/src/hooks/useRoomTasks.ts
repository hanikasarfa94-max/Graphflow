"use client";

// useRoomTasks — workbench Tasks panel data source.
//
// Lists the current viewer's personal-scope tasks for this project.
// Personal tasks are owner-only (mirrors the KB tree's personal-items
// rule), so what each user sees here is their own draft surface,
// not a shared queue. Promote-to-plan rides MembraneService.review
// (POST /api/tasks/{id}/promote) — wired in F.2.
//
// Refresh strategy: one-time-on-mount + manual refresh, same as
// useRoomKnowledge. Personal tasks don't fan out via room WS today;
// when manual_task creation gets a candidate kind on the membrane,
// this hook can derive from useRoomTimeline like pendingSuggestions.

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  createPersonalTask,
  fetchPersonalTasks,
  promoteTask,
  type CreatePersonalTaskInput,
  type PersonalTask,
} from "@/lib/api";

// One of "submitted" (membrane request_review or request_clarification —
// awaiting owner) or "promoted" (auto_merge — task already plan-scope).
// We track per-task client-side so the row's button can flip its label
// without a refresh round-trip.
export type PromoteOutcome = "submitted" | "promoted";

export interface UseRoomTasksResult {
  tasks: PersonalTask[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (input: CreatePersonalTaskInput) => Promise<PersonalTask | null>;
  creating: boolean;
  promote: (taskId: string) => Promise<PromoteOutcome | null>;
  // Per-task UI state. `null` for tasks not yet promoted in this
  // session; "submitted" while awaiting owner review; "promoted"
  // after auto_merge (task is gone from this list).
  promoteState: Record<string, PromoteOutcome>;
  promoting: Record<string, boolean>;
}

export function useRoomTasks({
  projectId,
}: {
  projectId: string;
}): UseRoomTasksResult {
  const [tasks, setTasks] = useState<PersonalTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [promoteState, setPromoteState] = useState<
    Record<string, PromoteOutcome>
  >({});
  const [promoting, setPromoting] = useState<Record<string, boolean>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchPersonalTasks(projectId);
      setTasks(r.tasks);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`error ${e.status}`);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError("fetch failed");
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  const create = useCallback(
    async (input: CreatePersonalTaskInput) => {
      setCreating(true);
      setError(null);
      try {
        const r = await createPersonalTask(projectId, input);
        setTasks((prev) => [r.task, ...prev]);
        return r.task;
      } catch (e) {
        if (e instanceof ApiError) {
          setError(`error ${e.status}`);
        } else if (e instanceof Error) {
          setError(e.message);
        } else {
          setError("create failed");
        }
        return null;
      } finally {
        setCreating(false);
      }
    },
    [projectId],
  );

  const promote = useCallback(
    async (taskId: string): Promise<PromoteOutcome | null> => {
      setPromoting((prev) => ({ ...prev, [taskId]: true }));
      setError(null);
      try {
        const r = await promoteTask(taskId);
        // auto_merge → BE returns task with scope='plan'. The personal
        // list no longer owns it; drop locally so the row vanishes.
        if (r.task && !r.deferred) {
          setTasks((prev) => prev.filter((t) => t.id !== taskId));
          setPromoteState((prev) => ({ ...prev, [taskId]: "promoted" }));
          return "promoted";
        }
        // request_review / request_clarification → task stays personal
        // but the suggestion is now in the owner inbox. Keep the row
        // visible so the user can see "in review" status.
        setPromoteState((prev) => ({ ...prev, [taskId]: "submitted" }));
        return "submitted";
      } catch (e) {
        if (e instanceof ApiError) {
          setError(`error ${e.status}`);
        } else if (e instanceof Error) {
          setError(e.message);
        } else {
          setError("promote failed");
        }
        return null;
      } finally {
        setPromoting((prev) => ({ ...prev, [taskId]: false }));
      }
    },
    [],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    tasks,
    loading,
    error,
    refresh,
    create,
    creating,
    promote,
    promoteState,
    promoting,
  };
}
