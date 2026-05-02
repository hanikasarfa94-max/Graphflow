"use client";

// AgentTimeline — Phase 2 message renderer for the v-next shell.
//
// Plain message list driven by the stream's id, NOT by a project id.
// Reuses the existing /api/streams/{id}/messages endpoint and the
// /ws/streams/{id} channel for live updates. Polymorphic-card dispatch
// (DriftCard / EdgeReplyCard / RouteProposalCard / etc. in the existing
// PersonalStream component) is deferred to Phase 3 — Phase 2's job is
// to make the v-next shell USABLE: messages render, composer posts.
//
// When the active stream is a per-project personal stream or a room,
// the user can still navigate to the legacy surface (which has the
// full polymorphic dispatch) via a "View full surface" link in the
// flowHead. Phase 3 lifts that dispatch into v-next directly.

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  listStreamMessages,
  type StreamMessage,
  type User,
} from "@/lib/api";

import styles from "./AgentTimeline.module.css";

interface Props {
  streamId: string;
  user: User;
}

export function AgentTimeline({ streamId, user }: Props) {
  const t = useTranslations("shellVNext");
  const [messages, setMessages] = useState<StreamMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Initial fetch on stream change.
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

  // WS subscribe for live updates. Dual-namespace per HE 767:
  // /ws/streams/{stream_id} is the per-stream channel.
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

  // Auto-scroll to bottom on new messages.
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
        <Message key={m.id} message={m} currentUserId={user.id} />
      ))}
    </div>
  );
}

function Message({
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
