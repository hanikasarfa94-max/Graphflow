"use client";

// PersonalStream — primary chat-stream renderer.
//
// Default view at `/projects/[id]` → the user's private conversation with
// their sub-agent, scoped to this project (north-star §"Primary surface
// after rebuild"). Layout language is iMessage / ChatGPT / Claude:
//
//   * user-origin text     → right-aligned bubble, accent-soft tint
//   * other-user text      → left-aligned bubble, raised surface
//   * agent turns (edge-*) → left-aligned flat flowing prose (no card)
//   * tool call / result   → flat single-line affordance under parent
//   * structural events    → lightened card (sunk surface, no hard accent
//                            border) because they carry actions or are
//                            genuinely distinct from a conversation turn
//
// Dispatch by `kind`:
//   text               → inline bubble (this file)
//   edge-answer        → EdgeReplyCard (flat prose)
//   edge-clarify       → EdgeReplyCard (flat prose, amber chip)
//   edge-thinking      → EdgeReplyCard (flat prose, muted chip)
//   edge-route-proposal→ RouteProposalCard (lightened card)
//   routed-inbound     → RoutedInboundCard (lightened compact line)
//   routed-reply       → RoutedReplyCard (lightened card)
//   edge-tool-call     → ToolCallCard (flat single-line)
//   edge-tool-result   → ToolResultCard (flat single-line)
//   drift/sla/membrane → their existing cards (structurally distinct)
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

import { Button } from "@/components/ui";
import {
  ApiError,
  edgeKindToMessageKind,
  listPersonalMessages,
  postPersonalMessage,
  previewPersonalMessage,
  type PersonalMessage,
  type RehearsalPreview as RehearsalPreviewType,
} from "@/lib/api";

import { SkillDeclarationBanner } from "@/components/onboarding/SkillDeclarationBanner";

import { DriftCard } from "./DriftCard";
import { SlaCard } from "./SlaCard";
import { EdgeReplyCard } from "./EdgeReplyCard";
import { MembraneCard } from "./MembraneCard";
import { RehearsalPreview } from "./RehearsalPreview";
import { RouteProposalCard } from "./RouteProposalCard";
import { GatedProposalPendingCard } from "./GatedProposalPendingCard";
import { RoutedInboundCard } from "./RoutedInboundCard";
import { RoutedReplyCard } from "./RoutedReplyCard";
import { SilentConsensusCard } from "./SilentConsensusCard";
import { ToolCallCard } from "./ToolCallCard";
import { ToolResultCard } from "./ToolResultCard";
import type { StreamMember } from "./types";
import { relativeTime } from "./types";

type Props = {
  projectId: string;
  currentUserId: string;
  members: StreamMember[];
  // QA finding #9b — optional so non-breaking; falls back to the project
  // id prefix when the caller can't supply the human title.
  projectTitle?: string;
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

// Author "lane" for the chat-stream layout.
//   * "mine"   — the viewer's bubble, right-aligned
//   * "human"  — another real user, left-aligned bubble
//   * "agent"  — the sub-agent (edge/tool turns), left-aligned flat prose
// Structural events (route-proposal, routed-inbound, routed-reply, etc.)
// are also left-aligned but render as lightened cards; the lane helper
// lumps them under "agent" for spacing purposes.
type Lane = "mine" | "human" | "agent";

function laneOf(m: PersonalMessage, viewerId: string): Lane {
  if (m.kind === "text") {
    return m.author_id === viewerId ? "mine" : "human";
  }
  return "agent";
}

// Chat-style author avatar — initial + presence dot. Only rendered for
// left-side human bubbles when the previous turn was NOT from the same
// author (iMessage pattern). Intentionally compact (20px) so the flow
// stays dense.
function MiniAvatar({ name }: { name: string }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <span
      aria-hidden
      style={{
        display: "inline-flex",
        width: 20,
        height: 20,
        borderRadius: "50%",
        background: "var(--wg-line)",
        color: "var(--wg-ink-soft)",
        fontWeight: 600,
        fontSize: 11,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {initial}
    </span>
  );
}

// Merge policy: prefer the server-fetched row (canonical id), but keep any
// pending optimistic ids the server doesn't know about yet. Deduping is by
// id; optimistic ids are prefixed "pending-".
//
// Extra dedupe pass for routed-reply / edge-reply-frame: the backend posts
// BOTH kinds into the source's stream (RoutingService.reply writes the
// "routed-reply" summary line, PersonalStreamService.handle_reply writes
// the richer "edge-reply-frame" card), each with different ids but the
// same `linked_id` (signal id). Both render as RoutedReplyCard, so
// rendering both shows the card twice. When we see both for the same
// signal, keep edge-reply-frame (richer, claims attached) and drop the
// routed-reply row.
const REPLY_CARD_KINDS = new Set(["routed-reply", "edge-reply-frame"]);

function dedupeReplyCards(merged: PersonalMessage[]): PersonalMessage[] {
  // Group by (kind-family, linked_id). Keep edge-reply-frame over
  // routed-reply when both exist for the same signal.
  const frameBySignal = new Map<string, PersonalMessage>();
  for (const m of merged) {
    if (m.kind === "edge-reply-frame" && m.linked_id) {
      frameBySignal.set(m.linked_id, m);
    }
  }
  if (frameBySignal.size === 0) return merged;
  return merged.filter((m) => {
    if (
      m.kind === "routed-reply" &&
      m.linked_id &&
      frameBySignal.has(m.linked_id)
    ) {
      return false;
    }
    return true;
  });
}

function mergeMessages(
  existing: PersonalMessage[],
  incoming: PersonalMessage[],
  currentUserId?: string,
): PersonalMessage[] {
  // Race fix: an incoming WS message authored by the current user
  // might arrive while a `pending-*` optimistic placeholder is still
  // in state (post send → WS broadcast wins the network race against
  // the POST response). Naive merge would land BOTH the pending and
  // the real id, then the POST response's swap leaves a duplicate.
  // Drop pendings whose body matches an incoming row from the same
  // author before merging.
  let cleaned = existing;
  if (currentUserId) {
    const incomingMineByBody = new Set(
      incoming
        .filter((m) => m.author_id === currentUserId)
        .map((m) => m.body),
    );
    if (incomingMineByBody.size > 0) {
      cleaned = existing.filter(
        (m) =>
          !(
            m.id.startsWith("pending-") &&
            m.author_id === currentUserId &&
            incomingMineByBody.has(m.body)
          ),
      );
    }
  }
  const byId = new Map<string, PersonalMessage>();
  for (const m of cleaned) byId.set(m.id, m);
  for (const m of incoming) byId.set(m.id, m); // server wins
  const merged = Array.from(byId.values());
  merged.sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();
    return ta - tb;
  });
  // Keep the set of kinds limited to routed-reply / edge-reply-frame —
  // do not accidentally dedupe other linked-id-carrying kinds like
  // edge-route-confirmed.
  const needsReplyDedupe = merged.some((m) => REPLY_CARD_KINDS.has(m.kind));
  return needsReplyDedupe ? dedupeReplyCards(merged) : merged;
}

export function PersonalStream({
  projectId,
  currentUserId,
  members,
  projectTitle,
}: Props) {
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
      setMessages((prev) => mergeMessages(prev, rows ?? [], currentUserId));
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
          setMessages((prev) => mergeMessages(prev, [m], currentUserId));
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
            claims: edgeResp.claims,
            uncited: edgeResp.uncited,
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
          setMessages((prev) => mergeMessages(prev, [edge], currentUserId));
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

  function renderCard(m: PersonalMessage, prev: PersonalMessage | null) {
    const mine = m.author_id === currentUserId;
    const author = memberById.get(m.author_id);
    const isOptimistic = m.id.startsWith("pending-");

    // Spacing: tight gap (4px) when the previous turn is from the same
    // "lane" (consecutive agent turns or consecutive same-user bubbles);
    // 14px at lane boundaries. This is the iMessage stacking rule.
    const lane = laneOf(m, currentUserId);
    const prevLane = prev ? laneOf(prev, currentUserId) : null;
    const sameAuthor =
      !!prev &&
      prev.author_id === m.author_id &&
      prevLane === lane;
    const marginTop = prev == null ? 0 : sameAuthor ? 4 : 14;

    // Agent turn is a "continuation" only when the immediately prior
    // message was from the same agent author on the agent lane. That
    // suppresses the attribution chip so stacked turns read as one
    // response.
    const agentContinuation =
      lane === "agent" &&
      prevLane === "agent" &&
      prev?.author_id === m.author_id;

    const wrap = (inner: React.ReactNode, extra?: React.CSSProperties) => (
      <div
        key={m.id}
        data-optimistic={isOptimistic ? "true" : undefined}
        data-lane={lane}
        style={{ marginTop, ...extra }}
      >
        {inner}
      </div>
    );

    switch (m.kind) {
      case "text": {
        // Chat-style bubble: mine on the right, others on the left.
        const name =
          author?.display_name ??
          m.author_display_name ??
          m.author_username ??
          m.author_id.slice(0, 8);
        // Show avatar + name only when the previous row was from a
        // different author (iMessage stacking).
        const showHeader = !mine && !sameAuthor;
        const bubble = (
          <div
            data-testid="stream-human-card"
            data-message-id={m.id}
            data-mine={mine ? "true" : "false"}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: mine ? "flex-end" : "flex-start",
              gap: 2,
            }}
          >
            {showHeader && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 11,
                  color: "var(--wg-ink-soft)",
                  fontFamily: "var(--wg-font-mono)",
                  marginBottom: 2,
                }}
              >
                <MiniAvatar name={name} />
                <strong style={{ color: "var(--wg-ink)", fontWeight: 600 }}>
                  {name}
                </strong>
              </div>
            )}
            <div
              style={{
                maxWidth: "70%",
                padding: "8px 12px",
                background: mine
                  ? "var(--wg-accent-soft)"
                  : "var(--wg-surface-raised)",
                border: mine
                  ? "1px solid var(--wg-accent-ring, var(--wg-line))"
                  : "1px solid var(--wg-line)",
                // Classic speech-bubble asymmetry: small corner on the
                // author's side so the bubble "points" at them.
                borderRadius: mine
                  ? "14px 14px 4px 14px"
                  : "14px 14px 14px 4px",
                fontSize: "var(--wg-fs-body)",
                lineHeight: 1.45,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                color: "var(--wg-ink)",
              }}
            >
              {m.body}
            </div>
            <span
              title={new Date(m.created_at).toLocaleString()}
              style={{
                fontSize: 10,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-faint)",
                padding: mine ? "0 4px 0 0" : "0 0 0 4px",
              }}
            >
              {relativeTime(m.created_at)}
            </span>
          </div>
        );
        return wrap(bubble);
      }
      case "edge-answer":
      case "edge-clarify":
      case "edge-thinking":
        return wrap(
          <EdgeReplyCard
            message={m}
            projectId={projectId}
            onFollowUp={handleFollowUp}
            continuation={agentContinuation}
          />,
        );
      case "edge-route-proposal":
        return wrap(
          <RouteProposalCard
            message={m}
            projectId={projectId}
            onConfirmed={() => void refresh()}
          />,
        );
      case "gated-proposal-pending":
        // Migration 0014 — gate-keeper sees a pending approval card in
        // their personal stream. Approve/deny actions happen inline;
        // resolution event lands as a separate 'gated-proposal-resolved'
        // card in the proposer's stream.
        return wrap(
          <GatedProposalPendingCard message={m} memberById={memberById} />,
        );
      case "gated-proposal-resolved":
        // Compact ambient line in the proposer's stream — the
        // approve/deny card lived in the gate-keeper's stream; on this
        // side we just echo the outcome. The body already carries the
        // human-readable text ("Your scope_cut proposal was approved").
        return wrap(
          <div
            data-testid="personal-gated-proposal-resolved"
            data-proposal-id={m.linked_id ?? undefined}
            style={{
              padding: "2px 8px",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ok)",
              marginLeft: 42,
            }}
          >
            ✓ {m.body}
          </div>,
        );
      case "routed-inbound":
        // Phase Q §Q.2 — NOT rendered as a full rich card inline. A
        // compact notification line + sidebar drawer badge is the new
        // shape. RoutedInboundCard is now the compact line; the rich
        // options surface lives in RoutedInboundDrawer.
        return wrap(
          <RoutedInboundCard message={m} memberById={memberById} />,
        );
      case "edge-tool-call":
        return wrap(<ToolCallCard message={m} />);
      case "edge-tool-result":
        return wrap(<ToolResultCard message={m} />);
      case "routed-reply":
      case "edge-reply-frame":
        // edge-reply-frame is the source-side framed reply card emitted
        // by PersonalStreamService.handle_reply. routed-reply is the raw
        // RoutingService.reply mirror — either one should render the
        // same rich reply card because both reference a RoutedSignalRow.
        return wrap(
          <RoutedReplyCard
            message={m}
            memberById={memberById}
            onFollowUp={handleFollowUp}
          />,
        );
      case "drift-alert":
        // vision.md §5.8. The edge agent flagged divergence between
        // committed thesis/decisions and recent execution; DriftService
        // fanned the alert into each affected user's personal stream.
        return wrap(<DriftCard message={m} onDiscuss={handleFollowUp} />);
      case "sla-alert":
        // Sprint 2b. SlaService fired because a commitment the viewer
        // owns crossed DUE-SOON or OVERDUE band. Body is a JSON
        // payload the card parses to render band + headline +
        // target_date + humanized "due in 4h" / "overdue 2d".
        return wrap(<SlaCard message={m} />);
      case "membrane-signal":
        // vision.md §5.12. The membrane classifier ingested an external
        // signal (git commit, steam review, rss item, forwarded link)
        // and routed it here because this viewer's slice is relevant.
        // Rendered muted — ambient, not urgent.
        return wrap(<MembraneCard message={m} />);
      case "silent-consensus-proposal":
        // Phase 1.A — behavioral-agreement proposal emitted by the
        // silent-consensus scanner. Rendered as a lightened card
        // (sunk surface) with member chips + ratify / reject.
        return wrap(
          <SilentConsensusCard
            message={m}
            projectId={projectId}
            onResolved={() => void refresh()}
          />,
        );
      case "edge-route-confirmed":
        // Ambient "✓ asked X" follow-up posted after a successful route
        // confirm. Keep it compact so it doesn't compete with the real
        // reply card when that lands.
        return wrap(
          <div
            data-testid="personal-route-confirmed"
            style={{
              padding: "2px 8px",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ok, #2f8f4f)",
              display: "flex",
              justifyContent: "space-between",
              marginRight: "20%",
            }}
          >
            <span>{m.body}</span>
            <span title={new Date(m.created_at).toLocaleString()}>
              {relativeTime(m.created_at)}
            </span>
          </div>,
        );
      default:
        // Forward-compat: unknown kinds render as plain text so a new
        // backend kind never crashes the surface.
        return wrap(
          <div
            data-testid="personal-unknown-card"
            data-kind={m.kind}
            style={{
              padding: "8px 12px",
              background: "var(--wg-surface-sunk, var(--wg-surface-raised))",
              border: "1px solid var(--wg-line-soft, var(--wg-line))",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              color: "var(--wg-ink-soft)",
              marginRight: "20%",
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
          </div>,
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
        background: "var(--wg-surface-raised)",
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
        {/* QA finding #9b — first-time skill declaration banner.
            Inline soft banner at the top of the stream; self-hides when
            declared_abilities is non-empty or the user dismisses it. */}
        <SkillDeclarationBanner
          projectId={projectId}
          projectTitle={projectTitle ?? projectId.slice(0, 8)}
          userId={currentUserId}
        />
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
        {messages.map((m, idx) =>
          renderCard(m, idx > 0 ? messages[idx - 1] : null),
        )}
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
          <Button
            variant="primary"
            onClick={() => void send()}
            disabled={!draft.trim() || posting}
            data-testid="personal-send-btn"
            style={{ padding: "10px 18px" }}
          >
            {t("composer.send")}
          </Button>
        </div>
      </div>
    </div>
  );
}
