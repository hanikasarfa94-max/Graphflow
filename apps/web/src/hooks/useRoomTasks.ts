"use client";

// useRoomTasks — workbench Tasks panel data source.
//
// Lists the current viewer's personal-scope tasks for this project.
// Personal tasks are owner-only (mirrors the KB tree's personal-items
// rule), so what each user sees here is their own draft surface,
// not a shared queue. Promote-to-plan rides MembraneService.review
// (POST /api/tasks/{id}/promote) — out of scope this slice.
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
  type CreatePersonalTaskInput,
  type PersonalTask,
} from "@/lib/api";

export interface UseRoomTasksResult {
  tasks: PersonalTask[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  create: (input: CreatePersonalTaskInput) => Promise<PersonalTask | null>;
  creating: boolean;
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

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { tasks, loading, error, refresh, create, creating };
}
