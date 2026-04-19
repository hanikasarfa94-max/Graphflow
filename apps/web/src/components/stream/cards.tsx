"use client";

// Stream card components — polymorphic renderers for the v2 stream.
//
// Visual identity mirrors the existing ChatPane.tsx (terracotta accent for
// decisions, amber for escalations, soft surface for everything else). We
// intentionally lean on the same CSS custom properties (`--wg-accent`,
// `--wg-line`, etc.) so the chrome matches the rest of the app and the
// language switcher / audit navigation don't visually clash.
//
// Kind routing: PersonalStream dispatches on message.kind to the right
// card component. These are the kinds this module knows about, exposed
// both for PersonalStream's switch and for any future renderer (e.g. a
// TeamStream rebuild) that wants the same dispatch table:
//   text               → HumanTurnCard (here)
//   edge-answer|clarify → EdgeReplyCard (./EdgeReplyCard)
//   edge-route-proposal → RouteProposalCard (./RouteProposalCard)
//   edge-tool-call     → ToolCallCard (./ToolCallCard) — Phase Q
//   edge-tool-result   → ToolResultCard (./ToolResultCard) — Phase Q
//   routed-inbound     → RoutedInboundCard (compact notification line,
//                         Phase Q corrective; full surface lives in
//                         the sidebar drawer)
//   routed-reply       → RoutedReplyCard (symmetric source-side
//                         affordances, Phase Q corrective)
//   drift-alert        → DriftCard (./DriftCard)
//   membrane-signal    → MembraneCard (./MembraneCard)
//   decision           → DecisionCard (here)
//   ambient            → AmbientSignalCard (here)

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState, type CSSProperties } from "react";

import type { Decision, IMMessage, IMSuggestion } from "@/lib/api";

import {
  attributionFor,
  presenceDotColor,
  relativeTime,
  type StreamMember,
} from "./types";

// ---------- shared button styles (copied from ChatPane — same palette) ----

const primaryBtn: CSSProperties = {
  padding: "6px 12px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};
const ghostBtn: CSSProperties = {
  padding: "6px 12px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};
const amberBtn: CSSProperties = {
  padding: "6px 12px",
  background: "transparent",
  color: "var(--wg-amber)",
  border: "1px solid var(--wg-amber)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

// ---------- small bits ----------

function Avatar({
  name,
  presence,
}: {
  name: string;
  presence?: StreamMember["presence"];
}) {
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div
      aria-hidden
      style={{
        position: "relative",
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
      <span
        style={{
          position: "absolute",
          bottom: -1,
          right: -1,
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: presenceDotColor(presence),
          border: "2px solid var(--wg-surface)",
        }}
      />
    </div>
  );
}

function AuthorHeader({
  name,
  presence,
  timestamp,
  tone = "ink",
}: {
  name: string;
  presence?: StreamMember["presence"];
  timestamp: string;
  tone?: "ink" | "accent";
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
      <Avatar name={name} presence={presence} />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          lineHeight: 1.25,
        }}
      >
        <strong
          style={{
            fontSize: 13,
            color: tone === "accent" ? "var(--wg-accent)" : "var(--wg-ink)",
          }}
        >
          {name}
        </strong>
        <span
          title={new Date(timestamp).toLocaleString()}
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          {relativeTime(timestamp)}
        </span>
      </div>
    </div>
  );
}

// Render @mentions as subtle highlights (ChatPane parity).
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

// Inline image parsing — the composer embeds pasted images as markdown-ish
// `![alt](data:... or url)` tokens. Anything else falls back to plain text.
function renderBodyWithAttachments(body: string): React.ReactNode {
  // Split on the image token so we keep text order.
  const re = /!\[[^\]]*\]\(([^)]+)\)/g;
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(body)) !== null) {
    if (match.index > lastIndex) {
      parts.push(
        <span key={`t-${key++}`}>{renderBody(body.slice(lastIndex, match.index))}</span>,
      );
    }
    parts.push(
      // eslint-disable-next-line @next/next/no-img-element
      <img
        key={`img-${key++}`}
        src={match[1]}
        alt=""
        style={{
          display: "block",
          maxWidth: "100%",
          maxHeight: 320,
          marginTop: 6,
          borderRadius: "var(--wg-radius)",
          border: "1px solid var(--wg-line)",
        }}
      />,
    );
    lastIndex = re.lastIndex;
  }
  if (lastIndex < body.length) {
    parts.push(<span key={`t-${key++}`}>{renderBody(body.slice(lastIndex))}</span>);
  }
  return parts.length > 0 ? parts : renderBody(body);
}

// ---------- HumanTurnCard ----------

export function HumanTurnCard({
  message,
  mine,
  author,
  crystallized,
  counterNote,
}: {
  message: IMMessage;
  mine: boolean;
  author: StreamMember | undefined;
  crystallized: boolean;
  counterNote: boolean;
}) {
  const t = useTranslations("stream");
  const name =
    author?.display_name ??
    message.author_display_name ??
    message.author_username ??
    message.author_id.slice(0, 8);

  return (
    <div
      data-testid="stream-human-card"
      data-message-id={message.id}
      style={{ marginBottom: 12 }}
    >
      <AuthorHeader
        name={name}
        presence={author?.presence}
        timestamp={message.created_at}
        tone={mine ? "accent" : "ink"}
      />
      {counterNote && (
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            marginBottom: 4,
            marginLeft: 42,
          }}
          data-testid="counter-of-note"
        >
          {t("counterNote")}
        </div>
      )}
      <div
        style={{
          marginLeft: 42,
          padding: "8px 12px",
          background: mine ? "#f6efe8" : "var(--wg-surface-raised)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {renderBodyWithAttachments(message.body)}
      </div>
      <div
        style={{
          marginLeft: 42,
          marginTop: 4,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <button
          type="button"
          aria-label={t("actions.react")}
          title={t("actions.react")}
          style={{
            padding: "2px 8px",
            fontSize: 12,
            background: "transparent",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm)",
            color: "var(--wg-ink-soft)",
            cursor: "pointer",
          }}
        >
          +
        </button>
        {crystallized && (
          <span
            data-testid="decision-recorded"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 8px",
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-accent)",
              background: "var(--wg-accent-soft)",
              border: "1px solid var(--wg-accent-ring)",
              borderRadius: "var(--wg-radius-sm)",
              fontWeight: 600,
            }}
          >
            <span aria-hidden>⚡</span> {t("decision.recorded")}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------- EdgeLLMTurnCard ----------

export function EdgeLLMTurnCard({
  message,
  suggestion: _suggestion,
}: {
  message: IMMessage;
  suggestion: IMSuggestion;
}) {
  const t = useTranslations("stream");
  return (
    <div
      data-testid="stream-edge-card"
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "8px 12px",
        background: "var(--wg-surface-sunk)",
        border: "1px solid var(--wg-line-soft)",
        borderLeft: "3px solid var(--wg-ink-faint)",
        borderRadius: "var(--wg-radius)",
        fontSize: 13,
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          marginBottom: 4,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          <span aria-hidden>🧠</span> {t("attribution.edge")}
        </span>
        <span title={new Date(message.created_at).toLocaleString()}>
          {relativeTime(message.created_at)}
        </span>
      </div>
      <div style={{ color: "var(--wg-ink)" }}>{renderBody(message.body)}</div>
    </div>
  );
}

// ---------- SubAgentTurnCard ----------

export function SubAgentTurnCard({
  suggestion,
  onAccept,
  onDismiss,
  onCounter,
  onEscalate,
}: {
  suggestion: IMSuggestion;
  onAccept: (s: IMSuggestion) => void;
  onDismiss: (s: IMSuggestion) => void;
  onCounter: (s: IMSuggestion, text: string) => Promise<void>;
  onEscalate: (s: IMSuggestion) => void;
}) {
  const t = useTranslations("stream");
  const [counterOpen, setCounterOpen] = useState(false);
  const [counterText, setCounterText] = useState("");
  const [sending, setSending] = useState(false);

  const { kind: attrKind } = attributionFor(suggestion);
  const kindColor =
    attrKind === "clarifier"
      ? "var(--wg-amber)"
      : attrKind === "blocker"
        ? "var(--wg-accent)"
        : attrKind === "decision"
          ? "var(--wg-accent)"
          : "var(--wg-ink-soft)";
  const attrIcon =
    attrKind === "clarifier"
      ? "❓"
      : attrKind === "blocker"
        ? "🚧"
        : attrKind === "decision"
          ? "⚖"
          : "🧠";

  const escalationRequested = suggestion.escalation_state === "requested";
  const statusIsResolved = suggestion.status !== "pending";

  async function submitCounter() {
    if (!counterText.trim() || sending) return;
    setSending(true);
    try {
      await onCounter(suggestion, counterText);
      setCounterText("");
      setCounterOpen(false);
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      data-testid="stream-subagent-card"
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: 10,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderLeft: `3px solid ${kindColor}`,
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          letterSpacing: "0.04em",
          color: kindColor,
          marginBottom: 4,
          textTransform: "uppercase",
        }}
      >
        <span>
          <span aria-hidden>{attrIcon}</span> {t(`attribution.${attrKind}`)} ·{" "}
          {(suggestion.confidence * 100).toFixed(0)}%
        </span>
      </div>
      {suggestion.proposal && (
        <>
          <div style={{ fontWeight: 600 }}>
            {t("proposal.label")}: {suggestion.proposal.action}
          </div>
          <div style={{ color: "var(--wg-ink-soft)", marginTop: 2 }}>
            {suggestion.proposal.summary}
          </div>
        </>
      )}
      {!suggestion.proposal && suggestion.targets.length > 0 && (
        <div style={{ color: "var(--wg-ink-soft)" }}>
          {t("proposal.references")}: {suggestion.targets.join(", ")}
        </div>
      )}
      {escalationRequested ? (
        <div
          data-testid="awaiting-sync-badge"
          style={{
            marginTop: 8,
            display: "inline-block",
            padding: "4px 10px",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-amber)",
            background: "var(--wg-amber-soft)",
            borderRadius: "var(--wg-radius-sm)",
            fontWeight: 600,
          }}
        >
          ⚠ {t("status.awaitingSync")}
        </div>
      ) : statusIsResolved ? (
        <div
          style={{
            marginTop: 6,
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            color:
              suggestion.status === "accepted"
                ? "var(--wg-ok)"
                : suggestion.status === "escalated"
                  ? "var(--wg-amber)"
                  : "var(--wg-ink-soft)",
          }}
        >
          {suggestion.status === "accepted" && `✓ ${t("status.accepted")}`}
          {suggestion.status === "dismissed" && `· ${t("status.dismissed")}`}
          {suggestion.status === "countered" && `↳ ${t("status.countered")}`}
          {suggestion.status === "escalated" && `⚠ ${t("status.escalated")}`}
        </div>
      ) : (
        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 6,
            justifyContent: "flex-end",
            flexWrap: "wrap",
          }}
        >
          <button type="button" onClick={() => onDismiss(suggestion)} style={ghostBtn}>
            {t("actions.dismiss")}
          </button>
          <button
            type="button"
            onClick={() => onEscalate(suggestion)}
            style={amberBtn}
            data-testid="escalate-btn"
          >
            {t("actions.escalate")}
          </button>
          <button
            type="button"
            onClick={() => setCounterOpen((v) => !v)}
            style={ghostBtn}
            data-testid="counter-btn"
            aria-expanded={counterOpen}
          >
            {counterOpen ? t("actions.cancel") : t("actions.counter")}
          </button>
          <button type="button" onClick={() => onAccept(suggestion)} style={primaryBtn}>
            {t("actions.accept")}
          </button>
        </div>
      )}
      {counterOpen && !escalationRequested && !statusIsResolved && (
        <div style={{ marginTop: 8 }}>
          <textarea
            value={counterText}
            onChange={(e) => setCounterText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !sending) {
                e.preventDefault();
                submitCounter();
              }
            }}
            placeholder={t("counter.placeholder")}
            rows={3}
            data-testid="counter-textarea"
            style={{
              width: "100%",
              padding: "8px 10px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              fontSize: 13,
              fontFamily: "var(--wg-font-sans)",
              background: "#fff",
              resize: "vertical",
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              marginTop: 6,
            }}
          >
            <button
              type="button"
              onClick={submitCounter}
              disabled={!counterText.trim() || sending}
              data-testid="counter-submit"
              style={{
                ...primaryBtn,
                opacity: !counterText.trim() || sending ? 0.6 : 1,
              }}
            >
              {t("actions.sendCounter")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- DecisionCard ----------

export function DecisionCard({
  projectId,
  decision,
}: {
  projectId: string;
  decision: Decision;
}) {
  const t = useTranslations("stream");
  return (
    <div
      data-testid="stream-decision-card"
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: 10,
        background: "var(--wg-accent-soft)",
        border: "1px solid var(--wg-accent-ring)",
        borderLeft: "3px solid var(--wg-accent)",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-accent)",
          marginBottom: 4,
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
        }}
      >
        <span aria-hidden>⚡</span> {t("decision.recorded")}
      </div>
      <div style={{ color: "var(--wg-ink)", fontWeight: 600 }}>
        {decision.custom_text ?? decision.rationale}
      </div>
      {decision.rationale && decision.custom_text && (
        <div style={{ color: "var(--wg-ink-soft)", marginTop: 2 }}>
          {decision.rationale}
        </div>
      )}
      <div style={{ marginTop: 6 }}>
        <Link
          href={`/projects/${projectId}/nodes/${decision.id}`}
          style={{
            fontSize: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {t("viewLineage")} →
        </Link>
      </div>
    </div>
  );
}

// ---------- AmbientSignalCard ----------

export function AmbientSignalCard({
  label,
  detail,
  timestamp,
}: {
  label: string;
  detail?: string;
  timestamp: string;
}) {
  return (
    <div
      data-testid="stream-ambient-card"
      style={{
        marginBottom: 8,
        marginLeft: 42,
        padding: "6px 10px",
        background: "transparent",
        fontSize: 12,
        color: "var(--wg-ink-soft)",
        fontFamily: "var(--wg-font-mono)",
        display: "flex",
        justifyContent: "space-between",
      }}
    >
      <span>
        · {label}
        {detail ? ` — ${detail}` : ""}
      </span>
      <span title={new Date(timestamp).toLocaleString()}>
        {relativeTime(timestamp)}
      </span>
    </div>
  );
}

// ---------- Phase Q kind routing exports ------------------------------------
//
// Re-exports so PersonalStream (and future stream surfaces) can import
// every card renderer from one module, even though some live in sibling
// files. PersonalStream still does its own switch; this is just the
// centralised catalog.

export { ToolCallCard } from "./ToolCallCard";
export { ToolResultCard } from "./ToolResultCard";
export { RoutedInboundCard } from "./RoutedInboundCard";
export { RoutedReplyCard } from "./RoutedReplyCard";
