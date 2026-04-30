"use client";

// useRoomKnowledge — workbench Knowledge panel data source.
//
// Surfaces the project's group-scope KB items so the panel can
// project the team's structured memory next to the inline timeline.
// Scope-narrowing (per-room) is intentionally NOT applied — knowledge
// is shared across the cell (per the projection thesis: cell is the
// memory boundary). Future iteration could intersect with
// ScopeTierPills selection.
//
// Refresh strategy: simple manual refresh + one-time-on-mount fetch.
// KB items don't fan out via the room WS today (no kb crystallization
// in this slice), so polling is the cheapest correct path. Once
// `propose_wiki_entry` skill outputs flow through the timeline event
// shape, this hook can derive from useRoomTimeline like
// pendingSuggestions does.

import { useCallback, useEffect, useState } from "react";

import { ApiError, listProjectKb, type KbItem } from "@/lib/api";

export interface UseRoomKnowledgeResult {
  items: KbItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const DEFAULT_LIMIT = 20;

export function useRoomKnowledge({
  projectId,
}: {
  projectId: string;
}): UseRoomKnowledgeResult {
  const [items, setItems] = useState<KbItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listProjectKb(projectId, { limit: DEFAULT_LIMIT });
      setItems(r.items);
    } catch (e) {
      // 404 means the listing endpoint isn't shipped yet (per its
      // docstring) — render empty state, not an error.
      if (e instanceof ApiError && e.status === 404) {
        setItems([]);
      } else if (e instanceof ApiError) {
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

  return { items, loading, error, refresh };
}
