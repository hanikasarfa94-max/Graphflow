"use client";

// Phase H — DM stream renderer.
//
// 1:1 DM surface. Shares visual language with StreamView (avatars,
// bubbles, same CSS tokens). Messages persist via stream-scoped
// endpoints:
//   * POST /api/streams/{id}/messages
//   * GET  /api/streams/{id}/messages
//
// Live delivery via `/ws/streams/{stream_id}` (Phase O). Initial list
// loads once on mount; subsequent messages arrive as WS `message` frames
// and merge by id. Reconnect with 1s → 10s exponential backoff on drop.
//
// LLM is PASSIVE in DMs for v1 (no suggestion fetch, no edge-LLM cards,
// no signal-chain decorations).

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { extractApiErrorDetail, type IMMessage } from "@/lib/api";

import type { StreamMember } from "./types";
import { relativeTime,
  formatMessageTime,
  MESSAGE_BODY_MAX_LENGTH } from "./types";
import { formatIso } from "@/lib/time";

type Props = {
  streamId: string;
  currentUserId: string;
  members: StreamMember[];
};

// A minimal author header identical in feel to cards.tsx but without the
// presence dot gymnastics — kept local so we don't edit cards.tsx.
function Avatar({ name }: { name: string }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div
      aria-hidden
      style={{
        width: 32,
        height: 32,
        borderRadius: "50%",
        background: "#e6e3db",
        color: "var(--wg-ink-soft)",
        fontWeight: 600,
        fontSize: 13,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {initial}
    </div>
  );
}

export function DMStream({ streamId, currentUserId, members }: Props) {
  const tDm = useTranslations("dm");
  const tStream = useTranslations("stream");

  const other =
    members.find((m) => m.user_id !== currentUserId) ?? members[0] ?? null;
  const otherName = other?.display_name ?? other?.username ?? "";

  const [messages, setMessages] = useState<IMMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const loadMessages = useCallback(async () => {
    if (!streamId) return;
    try {
      const r = await fetch(`/api/streams/${streamId}/messages`, {
        credentials: "include",
      });
      if (!r.ok) return;
      const data = (await r.json()) as { messages: IMMessage[] };
      setMessages((prev) => {
        // Merge by id so WS-delivered rows that arrived mid-load aren't lost.
        const byId = new Map<string, IMMessage>();
        for (const m of prev) byId.set(m.id, m);
        for (const m of data.messages) {
          byId.set(m.id, {
            ...m,
            project_id: m.project_id ?? "",
            suggestion: null,
          });
        }
        return Array.from(byId.values()).sort(
          (a, b) =>
            new Date(a.created_at).getTime() -
            new Date(b.created_at).getTime(),
        );
      });
    } catch {
      // network blip — WS will deliver future frames
    }
  }, [streamId]);

  // Initial load on mount. WS handles live delivery — no polling.
  useEffect(() => {
    void loadMessages();
  }, [loadMessages]);

  // WS live delivery for the DM stream. Mirrors PersonalStream logic:
  // connect on mount, reconnect with 1s → 10s backoff on drop, close on
  // unmount. Frames are `{type: "message", payload: IMMessage-like}`.
  useEffect(() => {
    if (!streamId || typeof window === "undefined") return;
    let closed = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = 1000;
    const MAX_BACKOFF = 10_000;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(
        `${proto}//${window.location.host}/ws/streams/${streamId}`,
      );
      ws.onopen = () => {
        backoff = 1000;
      };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data) as {
            type: string;
            payload: Record<string, unknown>;
          };
          if (frame.type !== "message") return;
          const m = frame.payload as unknown as IMMessage;
          setMessages((prev) => {
            if (prev.some((x) => x.id === m.id)) return prev;
            const next: IMMessage = {
              ...m,
              project_id: m.project_id ?? "",
              suggestion: null,
            };
            // Race fix: when the WS frame for our own send arrives
            // BEFORE the POST response, the optimistic local-* row
            // is still in state. Naive append would land the same
            // message twice (once as local-*, once as the real id),
            // and the POST response's map would then no-op because
            // the local-* id is already gone after a later refresh —
            // but in the meantime the user sees their message twice.
            // If the incoming message is ours, swap it into the
            // first matching optimistic placeholder by body.
            if (m.author_id === currentUserId) {
              const idx = prev.findIndex(
                (x) => x.id.startsWith("local-") && x.body === m.body,
              );
              if (idx !== -1) {
                const updated = [...prev];
                updated[idx] = next;
                return updated;
              }
            }
            return [...prev, next];
          });
        } catch {
          // ignore malformed frames
        }
      };
      const reconnect = () => {
        if (closed) return;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
          backoff = Math.min(backoff * 2, MAX_BACKOFF);
          connect();
        }, backoff);
      };
      ws.onclose = reconnect;
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          // noop
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
        // noop
      }
    };
  }, [streamId]);

  // Mark-read — keeps unread counts in the nav honest.
  useEffect(() => {
    if (!streamId) return;
    void fetch(`/api/streams/${streamId}/read`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {});
  }, [streamId, messages.length]);

  // Scroll pin on new messages.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, []);

  async function send() {
    const body = draft.trim();
    if (!body || posting) return;
    setPosting(true);
    setError(null);
    const optimisticId = `local-${crypto.randomUUID()}`;
    const optimistic: IMMessage = {
      id: optimisticId,
      project_id: "",
      author_id: currentUserId,
      body,
      created_at: new Date().toISOString(),
      suggestion: null,
    };
    setMessages((prev) => [...prev, optimistic]);
    setDraft("");
    requestAnimationFrame(autosize);
    try {
      const r = await fetch(`/api/streams/${streamId}/messages`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      if (r.ok) {
        const posted = (await r.json()) as IMMessage & { ok: true };
        setMessages((prev) =>
          prev.map((m) =>
            m.id === optimisticId
              ? { ...posted, project_id: posted.project_id ?? "", suggestion: null }
              : m,
          ),
        );
      } else {
        // Roll back optimistic + tell the user what happened. Previously
        // the failure was silent — message vanished, no signal to retry.
        setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
        setDraft(body);
        let parsedBody: unknown = null;
        try {
          parsedBody = await r.json();
        } catch {
          /* non-JSON body */
        }
        if (r.status === 422 && body.length > MESSAGE_BODY_MAX_LENGTH) {
          setError(
            tStream("composer.tooLong", { max: MESSAGE_BODY_MAX_LENGTH }),
          );
        } else {
          setError(extractApiErrorDetail(parsedBody) ?? `error ${r.status}`);
        }
      }
    } catch {
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
      setDraft(body);
      setError("send failed");
    } finally {
      setPosting(false);
    }
  }

  const memberById = new Map<string, StreamMember>();
  for (const m of members) memberById.set(m.user_id, m);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr auto",
        height: "calc(100vh - 200px)",
        minHeight: 520,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {/* Header — avatar + name of the other participant */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        {otherName ? <Avatar name={otherName} /> : null}
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.25 }}>
          <strong style={{ fontSize: 14, color: "var(--wg-ink)" }}>
            {otherName || tDm("title")}
          </strong>
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {otherName ? tDm("with", { name: otherName }) : tDm("title")}
          </span>
        </div>
      </div>

      {/* Timeline */}
      <div
        ref={scrollerRef}
        style={{
          overflowY: "auto",
          padding: "14px 16px 4px",
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              padding: 32,
            }}
          >
            {tDm("empty")}
          </div>
        )}
        {messages.map((m) => {
          const mine = m.author_id === currentUserId;
          const author = memberById.get(m.author_id);
          const name =
            author?.display_name ??
            author?.username ??
            m.author_id.slice(0, 8);
          return (
            <div
              key={m.id}
              data-testid="dm-message"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: mine ? "flex-end" : "flex-start",
                marginBottom: 12,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 4,
                  flexDirection: mine ? "row-reverse" : "row",
                }}
              >
                <Avatar name={name} />
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    lineHeight: 1.25,
                    textAlign: mine ? "right" : "left",
                  }}
                >
                  <strong
                    style={{
                      fontSize: 13,
                      color: mine ? "var(--wg-accent)" : "var(--wg-ink)",
                    }}
                  >
                    {name}
                  </strong>
                  <span
                    title={formatIso(m.created_at)}
                    style={{
                      fontSize: 11,
                      fontFamily: "var(--wg-font-mono)",
                      color: "var(--wg-ink-soft)",
                    }}
                  >
                    {formatMessageTime(m.created_at)}
                  </span>
                </div>
              </div>
              <div
                style={{
                  maxWidth: "72%",
                  padding: "8px 12px",
                  background: mine ? "#f6efe8" : "var(--wg-surface-raised)",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  fontSize: 14,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {m.body}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {error && (
        <div
          role="alert"
          data-testid="dm-error"
          style={{
            padding: "6px 12px",
            margin: "0 10px",
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
            borderTop: "1px solid var(--wg-line)",
          }}
        >
          {error}
        </div>
      )}
      {/* Composer */}
      <div
        style={{
          borderTop: "1px solid var(--wg-line)",
          padding: 10,
          display: "flex",
          gap: 8,
          alignItems: "flex-end",
        }}
      >
        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            autosize();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={
            otherName
              ? tDm("composer.placeholder", { name: otherName })
              : tStream("composer.placeholder")
          }
          rows={1}
          maxLength={MESSAGE_BODY_MAX_LENGTH}
          data-testid="dm-composer"
          style={{
            flex: 1,
            padding: "10px 12px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontFamily: "var(--wg-font-sans)",
            background: "var(--wg-surface)",
            resize: "none",
            lineHeight: "20px",
            maxHeight: 180,
            minHeight: 40,
            overflowY: "auto",
          }}
        />
        {draft.length >= MESSAGE_BODY_MAX_LENGTH * 0.9 && (
          <span
            data-testid="dm-composer-char-count"
            style={{
              alignSelf: "flex-end",
              marginBottom: 8,
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color:
                draft.length >= MESSAGE_BODY_MAX_LENGTH
                  ? "var(--wg-accent)"
                  : "var(--wg-ink-faint)",
              whiteSpace: "nowrap",
            }}
          >
            {tStream("composer.charCount", {
              count: draft.length,
              max: MESSAGE_BODY_MAX_LENGTH,
            })}
          </span>
        )}
        <button
          type="button"
          onClick={() => void send()}
          disabled={!draft.trim() || posting}
          data-testid="dm-send-btn"
          style={{
            padding: "10px 18px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            opacity: !draft.trim() || posting ? 0.6 : 1,
          }}
        >
          {tStream("actions.send")}
        </button>
      </div>
    </div>
  );
}
