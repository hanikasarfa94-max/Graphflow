"use client";

// PersonalStream — Phase N primary renderer.
//
// Default view at `/projects/[id]` → the user's private conversation with
// their sub-agent, scoped to this project (north-star §"Primary surface
// after rebuild"). Messages are polymorphic cards dispatched off
// `kind`:
//
//   text               → HumanTurnCard (reused from Phase E)
//   edge-answer        → EdgeReplyCard (warm-beige variant)
//   edge-clarify       → EdgeReplyCard (amber variant)
//   edge-thinking      → EdgeReplyCard (soft variant)
//   edge-route-proposal→ RouteProposalCard (Ask [name] buttons)
//   routed-inbound     → RoutedInboundCard (rich options core UX)
//   routed-reply       → RoutedReplyCard (framed reply + DM link)
//   unknown            → plain text fallback (forward-compat)
//
// Live delivery via `/ws/streams/{stream_id}`. The initial list is still
// fetched via `/api/personal/{id}/messages` on mount (which returns the
// stream_id we need for the WS URL); after that every backend-side
// post_message / post_system_message broadcasts a
// `{"type": "message", "payload": {...}}` frame on the stream channel
// and we merge by id. On disconnect we reconnect with 1s exponential
// backoff (capped at 10s). No polling.
//
// Composer POSTs to /api/personal/{id}/post; the response may include an
// `edge_response` we insert optimistically; the WS frame for that same
// row then arrives and reconciles to the canonical id.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  edgeKindToMessageKind,
  listPersonalMessages,
  postPersonalMessage,
  previewPersonalMessage,
  type IMMessage,
  type PersonalMessage,
  type RehearsalPreview as RehearsalPreviewType,
} from "@/lib/api";

import { HumanTurnCard } from "./cards";
import { DriftCard } from "./DriftCard";
import { EdgeReplyCard } from "./EdgeReplyCard";
import { MembraneCard } from "./MembraneCard";
import { RehearsalPreview } from "./RehearsalPreview";
import { RouteProposalCard } from "./RouteProposalCard";
import { RoutedInboundCard } from "./RoutedInboundCard";
import { RoutedReplyCard } from "./RoutedReplyCard";
import { ToolCallCard } from "./ToolCallCard";
import { ToolResultCard } from "./ToolResultCard";
import type { StreamMember } from "./types";
import { relativeTime } from "./types";

type Props = {
  projectId: string;
  currentUserId: string;
  members: StreamMember[];
};

// WS reconnect backoff — 1s, 2s, 4s, 8s, capped at 10s. Matches
// what a future RemoteStream service would want from a client.
const WS_BACKOFF_BASE_MS = 1000;
const WS_BACKOFF_MAX_MS = 10_000;
// Pre-commit rehearsal (vision.md §5.3): fire a preview once typing has
// paused for this long. Matches PREVIEW_MIN_BODY_LENGTH on the server;
// shorter drafts short-circuit server-side with kind="silent_preview".
const PREVIEW_DEBOUNCE_MS = 1000;
const PREVIEW_MIN_BODY_LENGTH = 10;

// Adapter — HumanTurnCard was designed around IMMessage (Phase E team stream
// shape). PersonalMessage is close enough that we lightly shim for reuse.
function toIMMessageShape(m: PersonalMessage): IMMessage {
  return {
    id: m.id,
    project_id: m.project_id ?? "",
    author_id: m.author_id,
    author_username: m.author_username ?? undefined,
    author_display_name: m.author_display_name ?? undefined,
    body: m.body,
    created_at: m.created_at,
    suggestion: null,
  };
}

// Merge policy: prefer the server-fetched row (canonical id), but keep any
// pending optimistic ids the server doesn't know about yet. Deduping is by
// id; optimistic ids are prefixed "pending-".
function mergeMessages(
  existing: PersonalMessage[],
  incoming: PersonalMessage[],
): PersonalMessage[] {
  const byId = new Map<string, PersonalMessage>();
  for (const m of existing) byId.set(m.id, m);
  for (const m of incoming) byId.set(m.id, m); // server wins
  const merged = Array.from(byId.values());
  merged.sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();
    return ta - tb;
  });
  return merged;
}

export function PersonalStream({ projectId, currentUserId, members }: Props) {
  const t = useTranslations("personal");
  const tStream = useTranslations("stream");

  const [messages, setMessages] = useState<PersonalMessage[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [streamId, setStreamId] = useState<string | null>(null);

  // Pre-commit rehearsal state. `preview` is the last successful preview
  // response; `previewLoading` gates the "thinking…" spinner;
  // `previewRateLimited` gates the cooldown hint. On draft change these
  // reset so a prior preview doesn't linger against unrelated text.
  const [preview, setPreview] = useState<RehearsalPreviewType | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewRateLimited, setPreviewRateLimited] = useState(false);

  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const mountedRef = useRef(true);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewTokenRef = useRef(0);

  const memberById = useMemo(() => {
    const m = new Map<string, StreamMember>();
    for (const mem of members) m.set(mem.user_id, mem);
    return m;
  }, [members]);

  const refresh = useCallback(async () => {
    try {
      const { stream_id, messages: rows } = await listPersonalMessages(
        projectId,
      );
      if (!mountedRef.current) return;
      setMessages((prev) => mergeMessages(prev, rows ?? []));
      if (stream_id) setStreamId(stream_id);
      setError(null);
    } catch (e) {
      if (!mountedRef.current) return;
      // Only surface the error on the initial load; reconnect errors are
      // silent to avoid blink-noise when the network hiccups.
      if (!loaded) {
        if (e instanceof ApiError) {
          setError(`load failed (${e.status})`);
        } else {
          setError("load failed");
        }
      }
    } finally {
      if (mountedRef.current && !loaded) setLoaded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Initial load — no polling; WS delivers subsequent messages.
  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  // WS live delivery. Connect once we know the stream_id (returned by
  // the initial GET). Reconnect with 1s → 10s exponential backoff.
  useEffect(() => {
    if (!streamId || typeof window === "undefined") return;
    let closed = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let backoff = WS_BACKOFF_BASE_MS;

    const connect = () => {
      if (closed) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(
        `${proto}//${window.location.host}/ws/streams/${streamId}`,
      );
      ws.onopen = () => {
        backoff = WS_BACKOFF_BASE_MS; // reset after a successful connect
      };
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data) as {
            type: string;
            payload: Record<string, unknown>;
          };
          if (frame.type !== "message") return;
          // Cast through PersonalMessage — backend post_system_message
          // shape is a superset of the list_messages shape we render.
          const m = frame.payload as unknown as PersonalMessage;
          setMessages((prev) => mergeMessages(prev, [m]));
        } catch {
          // ignore malformed frames
        }
      };
      const scheduleReconnect = () => {
        if (closed) return;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
          backoff = Math.min(backoff * 2, WS_BACKOFF_MAX_MS);
          connect();
        }, backoff);
      };
      ws.onclose = scheduleReconnect;
      ws.onerror = () => {
        // Let onclose handle reconnect; calling close here avoids
        // piling up multiple timers.
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

  // Pin to bottom on new rows.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  // Pre-commit rehearsal debounce. Mirrors the server-side guard: we
  // short-circuit on <PREVIEW_MIN_BODY_LENGTH and back off on 429 without
  // blocking sends. The token pattern (previewTokenRef) protects against
  // stale previews arriving out-of-order and overwriting the current one.
  useEffect(() => {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
    // Cancel any in-flight fetch whenever the draft changes — even if it
    // lands first, we wouldn't want it painting over a newer one.
    if (previewAbortRef.current) {
      previewAbortRef.current.abort();
      previewAbortRef.current = null;
    }

    const trimmed = draft.trim();
    if (trimmed.length < PREVIEW_MIN_BODY_LENGTH) {
      // Clear preview state when draft shrinks below threshold so the
      // last "edge would route to X" doesn't linger.
      if (preview !== null) setPreview(null);
      if (previewLoading) setPreviewLoading(false);
      if (previewRateLimited) setPreviewRateLimited(false);
      return;
    }

    previewTimerRef.current = setTimeout(async () => {
      const myToken = ++previewTokenRef.current;
      const controller = new AbortController();
      previewAbortRef.current = controller;
      setPreviewLoading(true);
      setPreviewRateLimited(false);
      try {
        const res = await previewPersonalMessage(
          projectId,
          trimmed,
          controller.signal,
        );
        if (!mountedRef.current) return;
        // Drop if a newer keystroke has since fired.
        if (myToken !== previewTokenRef.current) return;
        setPreview(res.preview ?? null);
      } catch (e) {
        if (!mountedRef.current) return;
        if (myToken !== previewTokenRef.current) return;
        if (e instanceof ApiError && e.status === 429) {
          // Rate-limited: show cooldown hint but keep the last good
          // preview so the card doesn't blink. Composer send is NOT
          // blocked — preview failure degrades silently.
          setPreviewRateLimited(true);
        } else {
          // Any other error: clear preview; do NOT surface as a send
          // error (the composer stays functional).
          setPreview(null);
        }
      } finally {
        if (!mountedRef.current) return;
        if (myToken === previewTokenRef.current) {
          setPreviewLoading(false);
        }
      }
    }, PREVIEW_DEBOUNCE_MS);

    return () => {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
        previewTimerRef.current = null;
      }
    };
    // preview/previewLoading/previewRateLimited intentionally excluded —
    // we only want to re-fire on draft changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, projectId]);

  const autosize = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, []);

  const handleFollowUp = useCallback(
    (prefill: string) => {
      setDraft((prev) => (prev ? `${prev} ${prefill}` : prefill));
      requestAnimationFrame(() => {
        autosize();
        taRef.current?.focus();
      });
    },
    [autosize],
  );

  async function send() {
    const body = draft.trim();
    if (!body || posting) return;
    setPosting(true);
    setError(null);

    const optimisticId = `pending-${crypto.randomUUID()}`;
    const optimistic: PersonalMessage = {
      id: optimisticId,
      stream_id: "",
      project_id: projectId,
      author_id: currentUserId,
      body,
      kind: "text",
      linked_id: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setDraft("");
    // Clear preview state — the draft just shipped. Keeps the rehearsal
    // card from lingering over the now-empty composer.
    setPreview(null);
    setPreviewLoading(false);
    setPreviewRateLimited(false);
    requestAnimationFrame(autosize);

    try {
      const res = await postPersonalMessage(projectId, body);
      // Replace optimistic row with the real id from the server. Also
      // drop any row that already has the real id — the WS frame may
      // have landed during the POST round-trip, in which case mapping
      // without removing the duplicate would leave two rows with the
      // same id (React key warning + visual duplicate).
      setMessages((prev) => {
        const serverRowAlreadyPresent = prev.some(
          (m) => m.id === res.message_id,
        );
        if (serverRowAlreadyPresent) {
          return prev.filter((m) => m.id !== optimisticId);
        }
        return prev.map((m) =>
          m.id === optimisticId ? { ...m, id: res.message_id } : m,
        );
      });
      // If the backend shipped a synchronous edge response, insert it so
      // the user sees it immediately — polling will reconcile. The edge
      // response kind is the EdgeAgent response kind ("answer" / "clarify"
      // / "route_proposal" / "silence"); convert to the stored message
      // kind when it has a stream representation.
      const edgeResp = res.edge_response;
      if (edgeResp && edgeResp.kind !== "silence" && edgeResp.body !== null) {
        const messageKind = edgeKindToMessageKind(edgeResp.kind);
        if (messageKind) {
          const optimisticEdgeId =
            edgeResp.reply_message_id ??
            edgeResp.route_proposal_id ??
            `pending-edge-${crypto.randomUUID()}`;
          const edge: PersonalMessage = {
            id: optimisticEdgeId,
            stream_id: "",
            project_id: projectId,
            author_id: "edge-agent-system",
            body: edgeResp.body,
            kind: messageKind,
            linked_id: null,
            created_at: new Date().toISOString(),
            ...(edgeResp.kind === "route_proposal"
              ? {
                  route_proposal: {
                    framing: edgeResp.body,
                    targets: edgeResp.targets ?? [],
                    background: [],
                    status: "pending",
                  },
                }
              : {}),
          };
          // Must dedup: the WS `message` frame for this same server-side
          // row may have ALREADY landed (edge_response.reply_message_id
          // is the real persisted id, and the backend broadcasts the
          // stream frame during post_system_message before the POST
          // response unwinds). Plain [...prev, edge] was producing
          // duplicate React keys when that race hit.
          setMessages((prev) => mergeMessages(prev, [edge]));
        }
      }
      // Trigger a refresh so poll-lag doesn't delay the server-truth.
      void refresh();
    } catch (e) {
      // Roll back optimistic row and restore draft.
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
      setDraft(body);
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? `error ${e.status}`)
            : `error ${e.status}`;
        setError(detail);
      } else {
        setError("send failed");
      }
    } finally {
      setPosting(false);
    }
  }

  function renderCard(m: PersonalMessage) {
    const mine = m.author_id === currentUserId;
    const author = memberById.get(m.author_id);
    const isOptimistic = m.id.startsWith("pending-");
    switch (m.kind) {
      case "text":
        return (
          <div key={m.id} data-optimistic={isOptimistic ? "true" : undefined}>
            <HumanTurnCard
              message={toIMMessageShape(m)}
              mine={mine}
              author={author}
              crystallized={false}
              counterNote={false}
            />
          </div>
        );
      case "edge-answer":
      case "edge-clarify":
      case "edge-thinking":
        return (
          <EdgeReplyCard
            key={m.id}
            message={m}
            onFollowUp={handleFollowUp}
          />
        );
      case "edge-route-proposal":
        return (
          <RouteProposalCard
            key={m.id}
            message={m}
            onConfirmed={() => void refresh()}
          />
        );
      case "routed-inbound":
        // Phase Q §Q.2 — NOT rendered as a full rich card inline. A
        // compact notification line + sidebar drawer badge is the new
        // shape. RoutedInboundCard is now the compact line; the rich
        // options surface lives in RoutedInboundDrawer.
        return (
          <RoutedInboundCard
            key={m.id}
            message={m}
            memberById={memberById}
          />
        );
      case "edge-tool-call":
        return <ToolCallCard key={m.id} message={m} />;
      case "edge-tool-result":
        return <ToolResultCard key={m.id} message={m} />;
      case "routed-reply":
      case "edge-reply-frame":
        // edge-reply-frame is the source-side framed reply card emitted
        // by PersonalStreamService.handle_reply. routed-reply is the raw
        // RoutingService.reply mirror — either one should render the
        // same rich reply card because both reference a RoutedSignalRow.
        return (
          <RoutedReplyCard
            key={m.id}
            message={m}
            memberById={memberById}
            onFollowUp={handleFollowUp}
          />
        );
      case "drift-alert":
        // vision.md §5.8. The edge agent flagged divergence between
        // committed thesis/decisions and recent execution; DriftService
        // fanned the alert into each affected user's personal stream.
        return (
          <DriftCard
            key={m.id}
            message={m}
            onDiscuss={handleFollowUp}
          />
        );
      case "membrane-signal":
        // vision.md §5.12. The membrane classifier ingested an external
        // signal (git commit, steam review, rss item, forwarded link)
        // and routed it here because this viewer's slice is relevant.
        // Rendered muted — ambient, not urgent.
        return <MembraneCard key={m.id} message={m} />;
      case "edge-route-confirmed":
        // Ambient "✓ asked X" follow-up posted after a successful route
        // confirm. Keep it compact so it doesn't compete with the real
        // reply card when that lands.
        return (
          <div
            key={m.id}
            data-testid="personal-route-confirmed"
            style={{
              marginBottom: 8,
              marginLeft: 42,
              padding: "4px 10px",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ok, #2f8f4f)",
              display: "flex",
              justifyContent: "space-between",
            }}
          >
            <span>{m.body}</span>
            <span title={new Date(m.created_at).toLocaleString()}>
              {relativeTime(m.created_at)}
            </span>
          </div>
        );
      default:
        // Forward-compat: unknown kinds render as plain text so a new
        // backend kind never crashes the surface.
        return (
          <div
            key={m.id}
            data-testid="personal-unknown-card"
            data-kind={m.kind}
            style={{
              marginBottom: 12,
              marginLeft: 42,
              padding: "8px 12px",
              background: "var(--wg-surface-raised)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              color: "var(--wg-ink-soft)",
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
                marginBottom: 4,
                display: "flex",
                justifyContent: "space-between",
              }}
            >
              <span>{m.kind}</span>
              <span>{relativeTime(m.created_at)}</span>
            </div>
            <div style={{ whiteSpace: "pre-wrap", color: "var(--wg-ink)" }}>
              {m.body}
            </div>
          </div>
        );
    }
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "1fr auto",
        height: "calc(100vh - 100px)",
        minHeight: 520,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {/* Phase Q — removed inline stream header. Sidebar + project strip
          already identify the context; count is visible as scrollbar +
          empty-state. Reclaims ~45px of vertical chrome. */}

      {/* Timeline */}
      <div
        ref={scrollerRef}
        style={{
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
            data-testid="personal-empty"
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              padding: 32,
              whiteSpace: "pre-wrap",
            }}
          >
            {t("empty")}
          </div>
        )}
        {messages.map(renderCard)}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div style={{ borderTop: "1px solid var(--wg-line)", padding: 10 }}>
        {/* Pre-commit rehearsal (vision.md §5.3) — debounced preview of
            how the edge agent would classify the in-flight draft. Shown
            inline above the composer so users see the routing proposal
            before committing. */}
        <RehearsalPreview
          preview={preview}
          loading={previewLoading}
          rateLimited={previewRateLimited}
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
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
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
            placeholder={t("composer.placeholder")}
            rows={1}
            data-testid="personal-composer"
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
          <button
            type="button"
            onClick={() => void send()}
            disabled={!draft.trim() || posting}
            data-testid="personal-send-btn"
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
            {t("composer.send")}
          </button>
        </div>
      </div>
    </div>
  );
}
