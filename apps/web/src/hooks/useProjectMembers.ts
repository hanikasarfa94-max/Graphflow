"use client";

// useProjectMembers — workbench Skills panel data source.
//
// Lightweight fetch of /api/projects/{id}/members. Distinct from
// useRoomMembers (which derives from a room's member list) — Skills
// projects across the whole project, not one room. Members are the
// canonical "who works on this cell" surface; per-room scoping is
// orthogonal.

import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchProjectMembers, type ProjectMember } from "@/lib/api";

export interface UseProjectMembersResult {
  members: ProjectMember[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useProjectMembers({
  projectId,
}: {
  projectId: string;
}): UseProjectMembersResult {
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchProjectMembers(projectId);
      setMembers(r);
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

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { members, loading, error, refresh };
}
