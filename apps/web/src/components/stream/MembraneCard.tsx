"use client";

// MembraneCard — Phase D.
//
// Renders an externally-ingested signal that flowed through the project's
// membrane (vision §5.12) and was routed to the viewer's personal stream.
// Muted styling — this is ambient, not urgent. The card shows:
//
//   * a globe icon + source-kind badge (git / steam / rss / drop / webhook)
//   * short tag chips (competitor, regulatory, etc.)
//   * the LLM-produced summary text
//   * a "View source" link that opens the source_identifier externally
//   * a footer note "Edge routed this to you as [tag]" that makes it
//     explicit the membrane AI (not a teammate) decided to surface this
//
// The body is a JSON blob posted server-side; we parse it here so the
// card renders even if the raw JSON is the only thing we have.

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import type { PersonalMessage } from "@/lib/api";

import { relativeTime,
  formatMessageTime } from "./types";
import { formatIso } from "@/lib/time";

type Props = {
  message: PersonalMessage;
};

type MembraneBody = {
  signal_id?: string;
  summary?: string;
  tags?: string[];
  confidence?: number;
  source_kind?: string;
  source_identifier?: string;
};

function parseBody(body: string): MembraneBody {
  try {
    const parsed = JSON.parse(body) as unknown;
    if (parsed && typeof parsed === "object") {
      return parsed as MembraneBody;
    }
  } catch {
    /* fall through */
  }
  return { summary: body };
}

function sourceBadge(kind: string | undefined): string {
  // Fallback to "source" so we always render something recognizable even
  // for server kinds the frontend hasn't seen before.
  switch (kind) {
    case "git-commit":
      return "git · commit";
    case "git-pr":
      return "git · pr";
    case "steam-review":
      return "steam · review";
    case "steam-forum":
      return "steam · forum";
    case "rss":
      return "rss";
    case "user-drop":
      return "drop";
    case "webhook":
      return "webhook";
    default:
      return kind ?? "external";
  }
}

function isHttpUrl(value: string | undefined): boolean {
  if (!value) return false;
  return value.startsWith("http://") || value.startsWith("https://");
}

const chipStyle: CSSProperties = {
  display: "inline-block",
  padding: "1px 7px",
  marginRight: 4,
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  color: "var(--wg-ink-soft)",
  background: "var(--wg-surface-sunk, #f4f1eb)",
  border: "1px solid var(--wg-line)",
  borderRadius: 999,
};

export function MembraneCard({ message }: Props) {
  const t = useTranslations("membrane");

  const parsed = useMemo(() => parseBody(message.body), [message.body]);
  const summary = parsed.summary ?? message.body;
  const tags = parsed.tags ?? [];
  const sourceKind = parsed.source_kind;
  const sourceIdentifier = parsed.source_identifier;
  const primaryTag = tags.length > 0 ? tags[0] : t("ambient");

  return (
    <div
      data-testid="personal-membrane-card"
      data-message-id={message.id}
      data-signal-id={parsed.signal_id ?? message.linked_id ?? ""}
      data-kind="membrane-signal"
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "10px 14px",
        background: "var(--wg-surface-sunk, #f4f1eb)",
        border: "1px solid var(--wg-line)",
        borderLeft: "3px solid var(--wg-ink-faint)",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
        // Subtle muted opacity so membrane cards don't compete with
        // active decisions / routed asks in the timeline.
        opacity: 0.94,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          marginBottom: 6,
        }}
      >
        <span>
          <span aria-hidden="true" style={{ marginRight: 6 }}>
            🌐
          </span>
          <strong style={{ color: "var(--wg-ink)" }}>{t("attribution")}</strong>
          {" · "}
          <span>{sourceBadge(sourceKind)}</span>
        </span>
        <span title={formatIso(message.created_at)}>
          {formatMessageTime(message.created_at)}
        </span>
      </div>
      {tags.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {tags.map((tag) => (
            <span key={tag} style={chipStyle}>
              {tag}
            </span>
          ))}
        </div>
      )}
      <div
        style={{
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          marginBottom: 6,
        }}
      >
        {summary}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        <span>{t("routedAs", { tag: primaryTag })}</span>
        {isHttpUrl(sourceIdentifier) && (
          <a
            href={sourceIdentifier}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="personal-membrane-source-link"
            style={{ color: "var(--wg-ink-soft)", textDecoration: "underline" }}
          >
            {t("viewSource")} ↗
          </a>
        )}
      </div>
    </div>
  );
}
