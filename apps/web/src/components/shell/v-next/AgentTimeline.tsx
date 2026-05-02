"use client";

// AgentTimeline — v-next message renderer with polymorphic kind dispatch.
//
// Drives off /api/streams/{id}/messages + /ws/streams/{id}. Renders the
// same card vocabulary the legacy PersonalStream uses (DriftCard /
// EdgeReplyCard / RouteProposalCard / RoutedInboundCard / RoutedReplyCard
// / GatedProposalPendingCard / SilentConsensusCard / SlaCard / MembraneCard
// / ToolCallCard / ToolResultCard) so the v-next shell is functionally
// at parity with the project-scoped surface — not just a plain bubble
// fallback.
//
// Cards that take a `projectId` prop only render when the stream is
// project-anchored (`m.project_id` is set). On the global 通用 Agent
// stream those rows fall through to the plain-text bubble; the kinds
// that emit there are 'text' / 'edge-*' anyway.
//
// We treat StreamMessage as a structural subtype of PersonalMessage —
// the fields the cards read (`id`, `kind`, `body`, `linked_id`,
// `created_at`, `author_id`, `author_username`) are all present. Optional
// fields the cards consume (`route_proposal`, `claims`) are absent on
// stream-id-fetched rows; the cards already handle missing metadata
// gracefully by rendering the body verbatim.

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  listStreamMessages,
  type PersonalMessage,
  type StreamMessage,
  type User,
} from "@/lib/api";

import { DriftCard } from "@/components/stream/DriftCard";
import { EdgeReplyCard } from "@/components/stream/EdgeReplyCard";
import { GatedProposalPendingCard } from "@/components/stream/GatedProposalPendingCard";
import { MembraneCard } from "@/components/stream/MembraneCard";
import { RoutedInboundCard } from "@/components/stream/RoutedInboundCard";
import { RoutedReplyCard } from "@/components/stream/RoutedReplyCard";
import { RouteProposalCard } from "@/components/stream/RouteProposalCard";
import { SilentConsensusCard } from "@/components/stream/SilentConsensusCard";
import { SlaCard } from "@/components/stream/SlaCard";
import { ToolCallCard } from "@/components/stream/ToolCallCard";
import { ToolResultCard } from "@/components/stream/ToolResultCard";
import type { StreamMember } from "@/components/stream/types";

import styles from "./AgentTimeline.module.css";

interface Props {
  streamId: string;
  user: User;
}

// Shape adapter — StreamMessage already has every field the cards
// require, but TypeScript wants the explicit cast since `kind` is
// `string` on StreamMessage and `PersonalMessageKind` (a union with
// fallback `string`) on PersonalMessage. The fallback in the union
// keeps the cast type-safe.
function toPersonal(m: StreamMessage): PersonalMessage {
  return m as unknown as PersonalMessage;
}

export function AgentTimeline({ streamId, user }: Props) {
  const t = useTranslations("shellVNext");
  const [messages, setMessages] = useState<StreamMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // memberById fed to the cards that group multi-author rows. We don't
  // have member rows for every stream (the streams endpoint doesn't
  // currently include them on each message), so the cards get an empty
  // map and fall back to author_username on the row.
  const memberById = new Map<string, StreamMember>();

  const refresh = () => {
    listStreamMessages(streamId, { limit: 100 })
      .then((res) => setMessages(res.messages))
      .catch(() => {
        // Non-fatal — the refresh callback is best-effort. The next WS
        // frame or initial fetch will reconverge.
      });
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listStreamMessages(streamId, { limit: 100 })
      .then((res) => {
        if (cancelled) return;
        setMessages(res.messages);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? `Failed to load messages (${err.status})`
            : "Failed to load messages.",
        );
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [streamId]);

  useEffect(() => {
    const wsProtocol =
      typeof window !== "undefined" && window.location.protocol === "https:"
        ? "wss"
        : "ws";
    const wsUrl = `${wsProtocol}://${typeof window !== "undefined" ? window.location.host : ""}/ws/streams/${streamId}`;
    let ws: WebSocket | null = null;
    let backoff = 1000;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        return;
      }
      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data);
          if (frame?.type === "message" && frame.payload) {
            setMessages((prev) => {
              if (prev.some((m) => m.id === frame.payload.id)) return prev;
              return [...prev, frame.payload as StreamMessage];
            });
          }
        } catch {
          // Ignore malformed frames.
        }
      };
      ws.onopen = () => {
        backoff = 1000;
      };
      ws.onclose = () => {
        if (cancelled) return;
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 10_000);
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [streamId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  if (loading) {
    return (
      <div className={styles.empty} data-testid="vnext-timeline-loading">
        {t("timelineLoading")}
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.error} data-testid="vnext-timeline-error">
        {error}
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className={styles.empty} data-testid="vnext-timeline-empty">
        {t("timelineEmpty")}
      </div>
    );
  }

  return (
    <div
      className={styles.messages}
      ref={scrollRef}
      data-testid="vnext-timeline"
    >
      {messages.map((m) => (
        <Row
          key={m.id}
          message={m}
          currentUserId={user.id}
          memberById={memberById}
          onRefresh={refresh}
        />
      ))}
    </div>
  );
}

function Row({
  message,
  currentUserId,
  memberById,
  onRefresh,
}: {
  message: StreamMessage;
  currentUserId: string;
  memberById: Map<string, StreamMember>;
  onRefresh: () => void;
}) {
  const projectId = message.project_id;
  const personal = toPersonal(message);

  switch (message.kind) {
    case "edge-answer":
    case "edge-clarify":
    case "edge-thinking":
      // EdgeReplyCard reads body + kind; doesn't need project context.
      return (
        <EdgeReplyCard
          message={personal}
          projectId={projectId ?? ""}
          onFollowUp={() => undefined}
        />
      );

    case "edge-route-proposal":
      // Project-only — needs projectId for the confirm callback. On
      // global / DM streams this kind shouldn't appear; if it does,
      // fall back to the bubble.
      if (!projectId) {
        return <Bubble message={message} currentUserId={currentUserId} />;
      }
      return (
        <RouteProposalCard
          message={personal}
          projectId={projectId}
          onConfirmed={onRefresh}
        />
      );

    case "gated-proposal-pending":
      return (
        <GatedProposalPendingCard
          message={personal}
          memberById={memberById}
        />
      );

    case "gated-proposal-resolved":
      return (
        <div
          className={styles.ambient}
          data-testid="vnext-gated-proposal-resolved"
          data-proposal-id={message.linked_id ?? undefined}
        >
          ✓ {message.body}
        </div>
      );

    case "routed-inbound":
      return (
        <RoutedInboundCard message={personal} memberById={memberById} />
      );

    case "edge-tool-call":
      return <ToolCallCard message={personal} />;

    case "edge-tool-result":
      return <ToolResultCard message={personal} />;

    case "routed-reply":
    case "edge-reply-frame":
      return (
        <RoutedReplyCard
          message={personal}
          memberById={memberById}
          onFollowUp={() => undefined}
        />
      );

    case "drift-alert":
      return <DriftCard message={personal} onDiscuss={() => undefined} />;

    case "sla-alert":
      return <SlaCard message={personal} />;

    case "membrane-signal":
      return <MembraneCard message={personal} />;

    case "silent-consensus-proposal":
      // Project-only — same fallback as edge-route-proposal.
      if (!projectId) {
        return <Bubble message={message} currentUserId={currentUserId} />;
      }
      return (
        <SilentConsensusCard
          message={personal}
          projectId={projectId}
          onResolved={onRefresh}
        />
      );

    case "edge-route-confirmed":
      return (
        <div
          className={styles.ambient}
          data-testid="vnext-route-confirmed"
        >
          {message.body}
        </div>
      );

    case "text":
    default:
      // Forward-compat: unknown kinds render as plain text. Matches
      // PersonalStream's default branch — a new backend kind never
      // crashes the surface.
      return <Bubble message={message} currentUserId={currentUserId} />;
  }
}

function Bubble({
  message,
  currentUserId,
}: {
  message: StreamMessage;
  currentUserId: string;
}) {
  const isMine = message.author_id === currentUserId;
  const time = formatTime(message.created_at);

  if (isMine) {
    return (
      <div className={`${styles.msg} ${styles.right}`}>
        <div>
          <div className={styles.bubble}>{message.body}</div>
          <div className={`${styles.time} ${styles.timeRight}`}>{time}</div>
        </div>
        <div className={styles.avatarMine}>
          {(message.author_username ?? "?").charAt(0).toUpperCase()}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.msg}>
      <div className={styles.avatar}>
        {(message.author_username ?? "?").charAt(0).toUpperCase()}
      </div>
      <div>
        <div className={styles.bubble}>
          <div className={styles.name}>{message.author_username ?? "?"}</div>
          {message.body}
        </div>
        <div className={styles.time}>{time}</div>
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  } catch {
    return "";
  }
}
