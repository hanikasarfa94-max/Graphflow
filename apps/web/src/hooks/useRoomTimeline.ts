"use client";

// useRoomTimeline — single source of truth for the room view's
// projection model.
//
// One canonical entity, multiple projections:
//   * RoomStreamTimeline reads `items` chronologically.
//   * RoomWorkbench `Requests` panel derives from
//     items.filter(i => i.kind === 'im_suggestion' && i.status === 'pending').
//   * Future workbench panels (decisions, tasks, knowledge) derive
//     similarly. No separate hooks, no duplicate state.
//
// Updates flow over /ws/streams/{roomId} as a single discriminated
// `RoomTimelineEvent` union (upsert / update / delete by entity ref).
// The reducer is one switch over `event.type`.
//
// Connection lifecycle mirrors DMStream/PersonalStream: exponential
// backoff reconnect on close, optimistic insert reconciles when the
// real upsert arrives.

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

import {
  api,
  ApiError,
  getRoomTimeline,
  type RoomTimelineEvent,
  type TimelineItem,
} from "@/lib/api";

interface State {
  items: TimelineItem[];
  loading: boolean;
  error: string | null;
}

type Action =
  | { type: "snapshot"; items: TimelineItem[] }
  | { type: "ws_event"; event: RoomTimelineEvent }
  | { type: "optimistic_insert"; item: TimelineItem }
  | { type: "optimistic_remove"; kind: TimelineItem["kind"]; id: string }
  | { type: "error"; message: string }
  | { type: "loading" };

function entityKey(item: TimelineItem): string {
  return `${item.kind}:${item.id}`;
}

function chronoSort(a: TimelineItem, b: TimelineItem): number {
  const ta = a.created_at ?? "";
  const tb = b.created_at ?? "";
  if (ta < tb) return -1;
  if (ta > tb) return 1;
  // Stable tiebreak by kind so a message renders above its derived
  // suggestion if both share an exact instant.
  const orderA =
    a.kind === "message" ? 0 : a.kind === "im_suggestion" ? 1 : 2;
  const orderB =
    b.kind === "message" ? 0 : b.kind === "im_suggestion" ? 1 : 2;
  return orderA - orderB;
}

function applyEvent(prev: TimelineItem[], event: RoomTimelineEvent): TimelineItem[] {
  if (event.type === "timeline.upsert") {
    const item = event.item;
    const idx = prev.findIndex(
      (it) => it.kind === item.kind && it.id === item.id,
    );
    if (idx === -1) {
      return [...prev, item].sort(chronoSort);
    }
    const next = [...prev];
    next[idx] = item;
    return next.sort(chronoSort);
  }
  if (event.type === "timeline.update") {
    return prev.map((it) =>
      it.kind === event.kind && it.id === event.id
        ? ({ ...it, ...event.patch } as TimelineItem)
        : it,
    );
  }
  // timeline.delete
  return prev.filter((it) => !(it.kind === event.kind && it.id === event.id));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: null };
    case "snapshot":
      return {
        items: [...action.items].sort(chronoSort),
        loading: false,
        error: null,
      };
    case "ws_event":
      return { ...state, items: applyEvent(state.items, action.event) };
    case "optimistic_insert":
      return {
        ...state,
        items: [...state.items, action.item].sort(chronoSort),
      };
    case "optimistic_remove":
      return {
        ...state,
        items: state.items.filter(
          (it) => !(it.kind === action.kind && it.id === action.id),
        ),
      };
    case "error":
      return { ...state, error: action.message, loading: false };
    default:
      return state;
  }
}

export interface UseRoomTimelineResult {
  items: TimelineItem[];
  loading: boolean;
  error: string | null;
  optimisticInsert: (item: TimelineItem) => void;
  removeOptimistic: (kind: TimelineItem["kind"], id: string) => void;
  // Workbench-derived projections — same source, derived state. Memoized
  // so panels only re-render when their slice changes.
  pendingSuggestions: TimelineItem[];
  decisions: TimelineItem[];
  // Server actions (reuse existing IM-suggestion routes — accept/dismiss
  // emit RoomTimelineEvents on the WS so the reducer reconciles).
  accept: (suggestionId: string) => Promise<void>;
  dismiss: (suggestionId: string) => Promise<void>;
}

export function useRoomTimeline({
  projectId,
  roomId,
}: {
  projectId: string;
  roomId: string;
}): UseRoomTimelineResult {
  const [state, dispatch] = useReducer(reducer, {
    items: [],
    loading: true,
    error: null,
  });
  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  // Snapshot fetch.
  useEffect(() => {
    let cancelled = false;
    dispatch({ type: "loading" });
    void getRoomTimeline(projectId, roomId)
      .then((snap) => {
        if (cancelled) return;
        dispatch({ type: "snapshot", items: snap.items });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError
            ? `error ${err.status}`
            : err instanceof Error
              ? err.message
              : "fetch failed";
        dispatch({ type: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, roomId]);

  // WS subscribe with exponential-backoff reconnect (mirrors DMStream).
  useEffect(() => {
    if (typeof window === "undefined") return;
    let closed = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 1000;
    const MAX_BACKOFF = 10_000;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(
        `${proto}//${window.location.host}/ws/streams/${roomId}`,
      );
      ws.onopen = () => {
        backoff = 1000;
      };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data) as RoomTimelineEvent;
          // Defensive: only apply frames carrying our discriminator.
          if (
            frame.type === "timeline.upsert" ||
            frame.type === "timeline.update" ||
            frame.type === "timeline.delete"
          ) {
            dispatchRef.current({ type: "ws_event", event: frame });
          }
        } catch {
          /* ignore non-JSON / non-timeline frames */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        reconnectTimer = setTimeout(() => {
          backoff = Math.min(backoff * 2, MAX_BACKOFF);
          connect();
        }, backoff);
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* swallow */
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try {
        ws?.close();
      } catch {
        /* swallow */
      }
    };
  }, [roomId]);

  const optimisticInsert = useCallback((item: TimelineItem) => {
    dispatchRef.current({ type: "optimistic_insert", item });
  }, []);

  const removeOptimistic = useCallback(
    (kind: TimelineItem["kind"], id: string) => {
      dispatchRef.current({ type: "optimistic_remove", kind, id });
    },
    [],
  );

  // Server actions — fire-and-forget. WS reconciles the visible state.
  const accept = useCallback(async (suggestionId: string) => {
    await api(`/api/im_suggestions/${suggestionId}/accept`, {
      method: "POST",
    });
  }, []);
  const dismiss = useCallback(async (suggestionId: string) => {
    await api(`/api/im_suggestions/${suggestionId}/dismiss`, {
      method: "POST",
    });
  }, []);

  // Derived projections — same source, memoized slices. Panels re-render
  // only when their slice changes, not on every other-kind upsert.
  const pendingSuggestions = useMemo(
    () =>
      state.items.filter(
        (it) => it.kind === "im_suggestion" && it.status === "pending",
      ),
    [state.items],
  );
  const decisions = useMemo(
    () => state.items.filter((it) => it.kind === "decision"),
    [state.items],
  );

  return {
    items: state.items,
    loading: state.loading,
    error: state.error,
    optimisticInsert,
    removeOptimistic,
    pendingSuggestions,
    decisions,
    accept,
    dismiss,
  };
}
