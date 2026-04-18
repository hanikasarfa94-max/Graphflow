"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Suggestion = {
  id: string;
  message_id: string;
  kind: "none" | "tag" | "decision" | "blocker";
  confidence: number;
  targets: string[];
  proposal: {
    action: string;
    summary: string;
    detail: Record<string, unknown>;
  } | null;
  reasoning: string;
  status: "pending" | "accepted" | "dismissed";
};

type Message = {
  id: string;
  project_id: string;
  author_id: string;
  author_username?: string;
  author_display_name?: string;
  body: string;
  created_at: string;
  suggestion?: Suggestion | null;
};

type WsFrame = {
  type: string;
  payload: Record<string, unknown>;
};

export function ChatPane({
  projectId,
  currentUserId,
}: {
  projectId: string;
  currentUserId: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [composer, setComposer] = useState("");
  const [posting, setPosting] = useState(false);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await fetch(
        `/api/projects/${projectId}/messages?limit=100`,
        { credentials: "include", cache: "no-store" },
      );
      if (!res.ok) {
        setError(`load failed (${res.status})`);
        return;
      }
      const data = await res.json();
      if (!cancelled) setMessages(data.messages ?? []);
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // WebSocket fanout.
  useEffect(() => {
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
          const m = frame.payload as unknown as Message;
          setMessages((prev) => {
            if (prev.some((x) => x.id === m.id)) return prev;
            return [...prev, m];
          });
        } else if (frame.type === "suggestion") {
          const s = frame.payload as unknown as Suggestion;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === s.message_id ? { ...m, suggestion: s } : m,
            ),
          );
        }
      } catch {
        // Ignore malformed frames.
      }
    };
    return () => ws.close();
  }, [projectId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  async function postMessage() {
    const body = composer.trim();
    if (!body || posting) return;
    setPosting(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
        credentials: "include",
      });
      if (!res.ok) {
        if (res.status === 429) {
          setError("slow down — rate limited");
        } else {
          const j = await res.json().catch(() => ({}));
          setError(j.detail ?? `error ${res.status}`);
        }
        return;
      }
      setComposer("");
      // WS echo will append; no optimistic insert needed.
    } finally {
      setPosting(false);
    }
  }

  const actOnSuggestion = useCallback(
    async (suggestion: Suggestion, action: "accept" | "dismiss") => {
      const res = await fetch(
        `/api/im_suggestions/${suggestion.id}/${action}`,
        { method: "POST", credentials: "include" },
      );
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      const nextStatus = action === "accept" ? "accepted" : "dismissed";
      setMessages((prev) =>
        prev.map((m) =>
          m.suggestion?.id === suggestion.id
            ? { ...m, suggestion: { ...m.suggestion, status: nextStatus } }
            : m,
        ),
      );
    },
    [],
  );

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr auto",
        height: 640,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
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
        <span>{messages.length} messages</span>
      </div>

      <div style={{ overflowY: "auto", padding: "14px 14px 4px" }}>
        {messages.map((m) => (
          <MessageRow
            key={m.id}
            message={m}
            mine={m.author_id === currentUserId}
            onAccept={(s) => actOnSuggestion(s, "accept")}
            onDismiss={(s) => actOnSuggestion(s, "dismiss")}
          />
        ))}
        {messages.length === 0 && (
          <div
            style={{
              color: "var(--wg-ink-soft)",
              fontSize: 13,
              textAlign: "center",
              padding: 24,
            }}
          >
            No messages yet — kick things off below.
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={{ borderTop: "1px solid var(--wg-line)", padding: 10 }}>
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
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={composer}
            onChange={(e) => setComposer(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                postMessage();
              }
            }}
            placeholder="Send a message… use @username to tag"
            style={{
              flex: 1,
              padding: "10px 12px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              fontSize: 14,
              fontFamily: "var(--wg-font-sans)",
              background: "var(--wg-surface)",
            }}
          />
          <button
            type="button"
            onClick={postMessage}
            disabled={!composer.trim() || posting}
            style={{
              padding: "8px 16px",
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
              opacity: !composer.trim() || posting ? 0.6 : 1,
            }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageRow({
  message,
  mine,
  onAccept,
  onDismiss,
}: {
  message: Message;
  mine: boolean;
  onAccept: (s: Suggestion) => void;
  onDismiss: (s: Suggestion) => void;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          fontFamily: "var(--wg-font-mono)",
          marginBottom: 2,
        }}
      >
        <strong
          style={{ color: mine ? "var(--wg-accent)" : "var(--wg-ink)" }}
        >
          {message.author_display_name ??
            message.author_username ??
            message.author_id.slice(0, 8)}
        </strong>
        <span style={{ marginLeft: 6 }}>
          {new Date(message.created_at).toLocaleTimeString()}
        </span>
      </div>
      <div
        style={{
          padding: "8px 12px",
          background: mine ? "#f6efe8" : "var(--wg-surface)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {renderBody(message.body)}
      </div>
      {message.suggestion &&
        message.suggestion.kind !== "none" &&
        message.suggestion.status === "pending" && (
          <SuggestionCard
            suggestion={message.suggestion}
            onAccept={onAccept}
            onDismiss={onDismiss}
          />
        )}
      {message.suggestion?.status === "accepted" && (
        <div style={suggestionStatusStyle("#7ab87a")}>
          ✓ suggestion accepted
        </div>
      )}
      {message.suggestion?.status === "dismissed" && (
        <div style={suggestionStatusStyle("var(--wg-ink-soft)")}>
          · suggestion dismissed
        </div>
      )}
    </div>
  );
}

function SuggestionCard({
  suggestion,
  onAccept,
  onDismiss,
}: {
  suggestion: Suggestion;
  onAccept: (s: Suggestion) => void;
  onDismiss: (s: Suggestion) => void;
}) {
  const kindColor = {
    tag: "#c7a44a",
    decision: "#4a7ac7",
    blocker: "var(--wg-accent)",
    none: "var(--wg-ink-soft)",
  }[suggestion.kind];
  return (
    <div
      style={{
        marginTop: 6,
        padding: 10,
        borderLeft: `3px solid ${kindColor}`,
        background: "#fafaf7",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: kindColor,
          marginBottom: 4,
        }}
      >
        {suggestion.kind} · {(suggestion.confidence * 100).toFixed(0)}%
        confidence
      </div>
      {suggestion.proposal && (
        <>
          <div style={{ fontWeight: 600 }}>
            Proposed: {suggestion.proposal.action}
          </div>
          <div style={{ color: "var(--wg-ink-soft)", marginTop: 2 }}>
            {suggestion.proposal.summary}
          </div>
        </>
      )}
      {!suggestion.proposal && suggestion.targets.length > 0 && (
        <div style={{ color: "var(--wg-ink-soft)" }}>
          references: {suggestion.targets.join(", ")}
        </div>
      )}
      <div
        style={{ marginTop: 8, display: "flex", gap: 6, justifyContent: "flex-end" }}
      >
        <button
          type="button"
          onClick={() => onDismiss(suggestion)}
          style={ghostBtn}
        >
          Dismiss
        </button>
        <button
          type="button"
          onClick={() => onAccept(suggestion)}
          style={primaryBtn}
        >
          Accept
        </button>
      </div>
    </div>
  );
}

function StatusDot({ state }: { state: "connecting" | "open" | "closed" }) {
  const color =
    state === "open"
      ? "#7ab87a"
      : state === "connecting"
        ? "#c7a44a"
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

// Render @mentions as subtle highlights.
function renderBody(body: string): React.ReactNode {
  const parts = body.split(/(@[A-Za-z0-9_-]{3,32})/g);
  return parts.map((part, idx) =>
    /^@[A-Za-z0-9_-]{3,32}$/.test(part) ? (
      <span
        key={idx}
        style={{
          color: "var(--wg-accent)",
          fontWeight: 600,
          background: "#f6efe8",
          padding: "1px 4px",
          borderRadius: 3,
        }}
      >
        {part}
      </span>
    ) : (
      <span key={idx}>{part}</span>
    ),
  );
}

function suggestionStatusStyle(color: string): React.CSSProperties {
  return {
    marginTop: 4,
    fontSize: 11,
    fontFamily: "var(--wg-font-mono)",
    color,
  };
}

const primaryBtn: React.CSSProperties = {
  padding: "6px 12px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};
const ghostBtn: React.CSSProperties = {
  padding: "6px 12px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};
