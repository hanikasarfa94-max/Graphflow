"use client";

// StreamView — the v2 project stream renderer.
//
// One full-height vertical timeline of polymorphic cards. Loads the
// existing project messages + suggestions, opens the same WS channel the
// old ChatPane used (`/ws/projects/{id}`), and merges incoming frames into
// a single ordered list keyed by timestamp.
//
// Every signal-chain interaction — Accept / Counter / Escalate / Dismiss —
// goes through the same endpoints and helpers the old ChatPane used, so
// the Moonshot demo chain still crystallizes into a DecisionRow exactly
// the same way.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  acceptSuggestion,
  counterSuggestion,
  dismissSuggestion,
  escalateSuggestion,
  previewPersonalMessage,
  type Decision,
  type IMMessage,
  type IMSuggestion,
  type RehearsalPreview as RehearsalPreviewType,
} from "@/lib/api";

import { Composer, type ComposerHandle } from "./Composer";
import {
  AmbientSignalCard,
  DecisionCard,
  EdgeLLMTurnCard,
  HumanTurnCard,
  SubAgentTurnCard,
} from "./cards";
import { MessageProfilePopover } from "./MessageProfilePopover";
import { RehearsalPreview } from "./RehearsalPreview";
import type { StreamMember } from "./types";
import { VoteGroupCard } from "./VoteGroupCard";

// Structural system-message kinds rendered as dedicated cards in the
// group stream instead of as human chat bubbles. Extend here when new
// team-room runtime-log message kinds land.
const VOTE_GROUP_KINDS = new Set([
  "vote-opened",
  "vote-resolved-approved",
  "vote-resolved-denied",
]);

// WS frames broadcast by the API — shape matches collab.py ws_broadcast calls.
type WsFrame = {
  type: string;
  payload: Record<string, unknown>;
};

type Props = {
  projectId: string;
  currentUserId: string;
  members: StreamMember[];
  streamId?: string; // used for mark-read; optional when caller didn't resolve it
};

// Small helper — derive presence per member. v1: all online if we have no
// signal; falls back to "online" (documented scope note in PLAN-v2 E.3).
function withDefaultPresence(members: StreamMember[]): StreamMember[] {
  return members.map((m) => ({
    ...m,
    presence: m.presence ?? "online",
  }));
}

export function StreamView({ projectId, currentUserId, members, streamId }: Props) {
  const t = useTranslations("stream");

  const [messages, setMessages] = useState<IMMessage[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [loaded, setLoaded] = useState(false);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  const [hasNewBelow, setHasNewBelow] = useState(false);

  // Pre-commit rehearsal state — mirrors PersonalStream. See north-star
  // §pre-commit rehearsal: the edge sub-agent previews how the in-flight
  // draft would be classified (answer / clarify / route_proposal) before
  // the user commits to sending it into the team stream.
  const [preview, setPreview] = useState<RehearsalPreviewType | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewRateLimited, setPreviewRateLimited] = useState(false);

  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // Ref-based cancellation: every onPreview fires a new AbortController
  // and bumps a token. A response that lands after a newer keystroke is
  // dropped so the card never flickers back to a stale classification.
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewTokenRef = useRef(0);
  const mountedRef = useRef(true);
  const composerRef = useRef<ComposerHandle | null>(null);

  const memberList = useMemo(() => withDefaultPresence(members), [members]);
  const memberById = useMemo(() => {
    const m = new Map<string, StreamMember>();
    for (const mem of memberList) m.set(mem.user_id, mem);
    return m;
  }, [memberList]);

  // Track mount so late-arriving preview responses don't setState on an
  // unmounted tree (e.g. user navigates away mid-fetch).
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Abort any in-flight preview on unmount so the browser isn't left
      // holding the request.
      previewAbortRef.current?.abort();
    };
  }, []);

  // Debounce is handled inside Composer; here we only perform the fetch.
  // Each call bumps a token so out-of-order responses are ignored.
  const handlePreview = useCallback(
    async (body: string) => {
      previewAbortRef.current?.abort();
      const controller = new AbortController();
      previewAbortRef.current = controller;
      const myToken = ++previewTokenRef.current;
      setPreviewLoading(true);
      setPreviewRateLimited(false);
      try {
        const res = await previewPersonalMessage(
          projectId,
          body,
          controller.signal,
        );
        if (!mountedRef.current) return;
        if (myToken !== previewTokenRef.current) return;
        setPreview(res.preview ?? null);
      } catch (e) {
        if (!mountedRef.current) return;
        if (myToken !== previewTokenRef.current) return;
        // 429: show muted cooldown hint but keep the last good preview so
        // the card doesn't blink away. Sends are never blocked — preview
        // degrades silently.
        if (e instanceof ApiError && e.status === 429) {
          setPreviewRateLimited(true);
        } else if ((e as { name?: string })?.name !== "AbortError") {
          setPreview(null);
        }
      } finally {
        if (!mountedRef.current) return;
        if (myToken === previewTokenRef.current) {
          setPreviewLoading(false);
        }
      }
    },
    [projectId],
  );

  const handlePreviewClear = useCallback(() => {
    previewAbortRef.current?.abort();
    previewTokenRef.current += 1;
    setPreview(null);
    setPreviewLoading(false);
    setPreviewRateLimited(false);
  }, []);

  // ------------- initial load -------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/messages?limit=100`, {
          credentials: "include",
          cache: "no-store",
        });
        if (!res.ok) {
          setError(`load failed (${res.status})`);
          return;
        }
        const data = (await res.json()) as { messages: IMMessage[] };
        if (!cancelled) setMessages(data.messages ?? []);

        // Pull any crystallized decisions for the project so DecisionCards
        // render on initial load (not only on WS echo). If the endpoint
        // isn't available or fails, we silently fall back to the
        // decision_id-on-suggestion badge path and continue.
        try {
          const dres = await fetch(`/api/projects/${projectId}/decisions`, {
            credentials: "include",
            cache: "no-store",
          });
          if (dres.ok) {
            const dd = (await dres.json()) as {
              decisions?: Decision[];
            };
            if (!cancelled && Array.isArray(dd.decisions)) {
              setDecisions(dd.decisions);
            }
          }
        } catch {
          // non-fatal
        }
      } catch {
        if (!cancelled) setError("load failed");
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // ------------- WS fanout -------------
  useEffect(() => {
    if (typeof window === "undefined") return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/projects/${projectId}`,
    );
    setWsState("connecting");
    ws.onopen = () => setWsState("open");
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("closed");
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as WsFrame;
        if (frame.type === "message") {
          const m = frame.payload as unknown as IMMessage;
          setMessages((prev) =>
            prev.some((x) => x.id === m.id) ? prev : [...prev, m],
          );
        } else if (frame.type === "suggestion") {
          const s = frame.payload as unknown as IMSuggestion;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === s.message_id ? { ...m, suggestion: s } : m,
            ),
          );
        } else if (frame.type === "decision") {
          const d = frame.payload as unknown as Decision;
          setDecisions((prev) =>
            prev.some((x) => x.id === d.id) ? prev : [...prev, d],
          );
          // Also flip the ⚡ on the linked suggestion so the parent message
          // gets the "Decision recorded" badge — ChatPane parity.
          const sourceId = d.source_suggestion_id;
          if (!sourceId) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.suggestion && m.suggestion.id === sourceId
                ? {
                    ...m,
                    suggestion: { ...m.suggestion, decision_id: d.id },
                  }
                : m,
            ),
          );
        }
      } catch {
        // ignore malformed frames
      }
    };
    return () => {
      try {
        ws.close();
      } catch {
        // noop
      }
    };
  }, [projectId]);

  // ------------- auto-scroll logic -------------
  const handleScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const distanceFromBottom =
      el.scrollHeight - (el.scrollTop + el.clientHeight);
    const atBottom = distanceFromBottom < 80;
    setPinnedToBottom(atBottom);
    if (atBottom) setHasNewBelow(false);
  }, []);

  // Scroll to bottom on new card if user was already at bottom, otherwise
  // surface the "↓ new messages" pill.
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    if (pinnedToBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    } else {
      setHasNewBelow(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length, decisions.length]);

  // Initial cursor — newest turn targeted at current user (if any), else bottom.
  const initialFocusedRef = useRef(false);
  useEffect(() => {
    if (!loaded || initialFocusedRef.current) return;
    initialFocusedRef.current = true;
    const targeted = [...messages].reverse().find((m) => {
      const sug = m.suggestion;
      return sug && Array.isArray(sug.targets) && sug.targets.includes(currentUserId);
    });
    if (targeted) {
      const node = scrollerRef.current?.querySelector(
        `[data-message-id="${targeted.id}"]`,
      );
      if (node instanceof HTMLElement) {
        node.scrollIntoView({ block: "center" });
        return;
      }
    }
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [loaded, messages, currentUserId]);

  // Mark-read on focus / load — best-effort.
  useEffect(() => {
    if (!loaded || !streamId) return;
    void fetch(`/api/streams/${streamId}/read`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {
      // no-op
    });
  }, [loaded, streamId]);

  // ------------- signal-chain handlers -------------

  const onAccept = useCallback(async (sug: IMSuggestion) => {
    try {
      await acceptSuggestion(sug.id);
      setMessages((prev) =>
        prev.map((m) =>
          m.suggestion?.id === sug.id
            ? { ...m, suggestion: { ...m.suggestion, status: "accepted" } }
            : m,
        ),
      );
    } catch (e) {
      setError(apiErrText(e, "accept failed"));
    }
  }, []);

  const onDismiss = useCallback(async (sug: IMSuggestion) => {
    try {
      await dismissSuggestion(sug.id);
      setMessages((prev) =>
        prev.map((m) =>
          m.suggestion?.id === sug.id
            ? { ...m, suggestion: { ...m.suggestion, status: "dismissed" } }
            : m,
        ),
      );
    } catch (e) {
      setError(apiErrText(e, "dismiss failed"));
    }
  }, []);

  const onCounter = useCallback(
    async (sug: IMSuggestion, text: string) => {
      try {
        const result = await counterSuggestion(sug.id, text);
        setMessages((prev) =>
          prev.map((m) =>
            m.suggestion?.id === sug.id
              ? { ...m, suggestion: result.original_suggestion }
              : m,
          ),
        );
      } catch (e) {
        setError(apiErrText(e, "counter failed"));
      }
    },
    [],
  );

  const onEscalate = useCallback(async (sug: IMSuggestion) => {
    try {
      const updated = await escalateSuggestion(sug.id);
      setMessages((prev) =>
        prev.map((m) =>
          m.suggestion?.id === sug.id ? { ...m, suggestion: updated } : m,
        ),
      );
    } catch (e) {
      setError(apiErrText(e, "escalate failed"));
    }
  }, []);

  // ------------- compose (optimistic insert) -------------

  const onOptimisticSend = useCallback(
    (optimistic: IMMessage) => {
      setMessages((prev) => [...prev, optimistic]);
    },
    [],
  );

  const onOptimisticError = useCallback((optimisticId: string) => {
    setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
  }, []);

  // ------------- render flow -------------

  // Build a flat render list. Each message becomes 1-2 cards (human turn +
  // optional sub-agent / edge-LLM follow-up). Decisions with a
  // source_suggestion_id we already surfaced via the ⚡ badge are skipped
  // as standalone cards to avoid duplication (the badge is enough — this
  // is the choice called out in E.1).
  const suggestionIdsWithParent = useMemo(() => {
    const s = new Set<string>();
    for (const m of messages) if (m.suggestion) s.add(m.suggestion.id);
    return s;
  }, [messages]);

  const hasMemberStrip = memberList.length > 1;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: hasMemberStrip
          ? "auto auto 1fr auto"
          : "auto 1fr auto",
        height: "calc(100vh - 100px)",
        minHeight: 520,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {/* Header strip — connection state + message count */}
      <div
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          <StatusDot state={wsState} />{" "}
          <span data-testid="ws-status">{wsState}</span>
        </span>
        <span>
          {messages.length} {t("messageCount")}
        </span>
      </div>

      {/* Members strip — compact Phase H affordance. Each non-self member
          exposes a "Message" button that opens (or reuses) the 1:1 DM
          stream and navigates to /streams/{id}. Intentionally minimal —
          the stream timeline remains the primary surface. */}
      {hasMemberStrip && (
        <div
          style={{
            padding: "8px 14px",
            borderBottom: "1px solid var(--wg-line-soft, var(--wg-line))",
            background: "var(--wg-surface-sunk, var(--wg-surface))",
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "center",
          }}
        >
          {memberList
            .filter((m) => m.user_id !== currentUserId)
            .map((m) => (
              <div
                key={m.user_id}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "2px 4px",
                  fontSize: 12,
                  color: "var(--wg-ink-soft)",
                  fontFamily: "var(--wg-font-mono)",
                }}
                data-testid="stream-member-chip"
              >
                <span style={{ color: "var(--wg-ink)" }}>{m.display_name}</span>
                <MessageProfilePopover
                  targetUserId={m.user_id}
                  targetDisplayName={m.display_name}
                  variant="icon"
                />
              </div>
            ))}
        </div>
      )}

      {/* Timeline scroller */}
      <div
        ref={scrollerRef}
        onScroll={handleScroll}
        style={{
          position: "relative",
          overflowY: "auto",
          padding: "14px 14px 4px",
        }}
      >
        {!loaded && (
          <div
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              padding: 24,
            }}
          >
            {t("loading")}
          </div>
        )}
        {loaded && messages.length === 0 && (
          <div
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              padding: 24,
            }}
          >
            {t("empty")}
          </div>
        )}
        {messages.map((m) => {
          // Phase S — vote runtime-log messages get a typed card
          // (VoteGroupCard) instead of the default human-turn bubble.
          // The body is already self-describing; the card adds
          // structure (status palette, class chip, icon, motion).
          if (m.kind && VOTE_GROUP_KINDS.has(m.kind)) {
            return (
              <div key={m.id}>
                <VoteGroupCard message={m} />
              </div>
            );
          }

          const sug = m.suggestion ?? null;
          const author = memberById.get(m.author_id);
          const mine = m.author_id === currentUserId;
          const crystallized = Boolean(sug?.decision_id);
          const counterNote = Boolean(sug?.counter_of_id);
          // Sub-agent cards are rendered when the suggestion makes a
          // proposal (kind !== "none"). "none" suggestions are purely
          // metabolic signal — we don't render them as cards to avoid
          // noise; they still update the graph in the backend.
          const showSubAgent = sug && sug.kind !== "none";
          return (
            <div key={m.id}>
              <HumanTurnCard
                message={m}
                mine={mine}
                author={author}
                crystallized={crystallized}
                counterNote={counterNote}
              />
              {showSubAgent && sug && (
                <SubAgentTurnCard
                  suggestion={sug}
                  onAccept={onAccept}
                  onDismiss={onDismiss}
                  onCounter={onCounter}
                  onEscalate={onEscalate}
                />
              )}
            </div>
          );
        })}

        {/* Decisions that don't trace to a rendered suggestion (e.g. direct
            edits). Rare in v1, but shown for completeness. */}
        {decisions
          .filter(
            (d) =>
              !d.source_suggestion_id ||
              !suggestionIdsWithParent.has(d.source_suggestion_id),
          )
          .map((d) => (
            <DecisionCard
              key={d.id}
              projectId={projectId}
              decision={d}
            />
          ))}

        {/* Scaffolded — left here so the union covers all kinds. No emitter
            in v1; safe to comment out if desired. */}
        {false && (
          <AmbientSignalCard
            label=""
            timestamp={new Date().toISOString()}
          />
        )}

        <div ref={bottomRef} />

        {hasNewBelow && (
          <button
            type="button"
            onClick={() =>
              bottomRef.current?.scrollIntoView({
                behavior: "smooth",
                block: "end",
              })
            }
            style={{
              position: "sticky",
              bottom: 12,
              left: "50%",
              transform: "translateX(-50%)",
              display: "block",
              margin: "0 auto",
              padding: "6px 14px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: 999,
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "var(--wg-font-mono)",
              cursor: "pointer",
              boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            }}
          >
            ↓ {t("newMessagesBelow")}
          </button>
        )}
      </div>

      {/* Composer */}
      <div style={{ borderTop: "1px solid var(--wg-line)", padding: 10 }}>
        {/* Rehearsal preview — rendered above the textarea so the user
            sees how the edge sub-agent would classify their in-flight
            draft before committing. "Send as-is" flushes the composer. */}
        <RehearsalPreview
          preview={preview}
          loading={previewLoading}
          rateLimited={previewRateLimited}
          onSendAsIs={() => composerRef.current?.sendNow()}
        />
        {error && (
          <div
            role="alert"
            style={{
              padding: "6px 10px",
              marginBottom: 6,
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-accent)",
            }}
          >
            {error}
          </div>
        )}
        <Composer
          ref={composerRef}
          projectId={projectId}
          currentUserId={currentUserId}
          onOptimisticSend={onOptimisticSend}
          onOptimisticError={onOptimisticError}
          onError={setError}
          onPreview={handlePreview}
          onPreviewClear={handlePreviewClear}
        />
      </div>
    </div>
  );
}

function StatusDot({ state }: { state: "connecting" | "open" | "closed" }) {
  const color =
    state === "open"
      ? "var(--wg-ok)"
      : state === "connecting"
        ? "var(--wg-amber)"
        : "var(--wg-accent)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginRight: 6,
        verticalAlign: "middle",
      }}
    />
  );
}

function apiErrText(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    if (
      typeof e.body === "object" &&
      e.body &&
      "detail" in e.body &&
      typeof (e.body as { detail?: unknown }).detail === "string"
    ) {
      return (e.body as { detail: string }).detail;
    }
    return `error ${e.status}`;
  }
  return fallback;
}
