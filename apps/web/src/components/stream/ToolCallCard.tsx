"use client";

// ToolCallCard — Phase Q.
//
// When the edge agent invokes a skill (kb_search, decision_history,
// plan_propose, risk_scan, drift_check, …), the call is persisted as a
// `edge-tool-call` message. This card renders it compact and monospace-
// ish — "🔧 Calling skill: kb_search with {query: "boss 1"}" — expandable
// to show the raw JSON args.
//
// Expected PersonalMessage shape (forward-compat — the backend Phase Q-A
// agent is still landing the schema):
//   * body: short human-readable summary
//   * linked_id: optional run id / call id so the matching ToolResultCard
//     can pair up
//   * Optional tool_call metadata field (skill name + args) — we fall
//     back to parsing body tokens when metadata is missing.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { PersonalMessage } from "@/lib/api";

import { relativeTime,
  formatMessageTime } from "./types";

type ToolCallMetadata = {
  skill?: string;
  args?: Record<string, unknown>;
};

// Pulls skill + args from the message. Accepts either a typed metadata
// field (when the backend attaches one) or parses the body for a
// `[[tool-call]]` marker used by the v1 bridge. Falls back to raw body.
function parseToolCall(
  message: PersonalMessage & { tool_call?: ToolCallMetadata },
): ToolCallMetadata {
  if (message.tool_call) return message.tool_call;
  // Fallback parser: "🔧 kb_search({"query":"boss 1"})" or
  // "tool-call: kb_search {args}".
  const m = message.body.match(
    /(?:🔧\s*|tool[-_]call:\s*)([a-z_][a-z0-9_]*)\s*(?:\(|\{)/i,
  );
  if (!m) return {};
  const skill = m[1];
  // Try to extract a JSON-ish args blob.
  const argsMatch = message.body.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  let args: Record<string, unknown> | undefined;
  if (argsMatch) {
    try {
      const parsed = JSON.parse(argsMatch[1]);
      if (parsed && typeof parsed === "object") {
        args = parsed as Record<string, unknown>;
      }
    } catch {
      // ignore — body was human-prose
    }
  }
  return { skill, args };
}

export function ToolCallCard({
  message,
}: {
  message: PersonalMessage & { tool_call?: ToolCallMetadata };
}) {
  const t = useTranslations("tool");
  const [expanded, setExpanded] = useState(false);

  const { skill, args } = useMemo(() => parseToolCall(message), [message]);
  const argsJson = useMemo(() => {
    if (!args) return null;
    try {
      return JSON.stringify(args, null, 2);
    } catch {
      return null;
    }
  }, [args]);

  const oneLine =
    skill && args
      ? `${skill} ${JSON.stringify(args)}`
      : skill
        ? skill
        : message.body;

  return (
    <div
      data-testid="tool-call-card"
      data-call-id={message.linked_id ?? undefined}
      style={{
        // Flat single-line affordance, no card shell. Sits under the
        // parent agent turn as ambient metadata.
        padding: "2px 8px",
        fontFamily: "var(--wg-font-mono)",
        fontSize: 11,
        color: "var(--wg-ink-faint)",
        marginRight: "20%",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
          }}
          title={oneLine}
        >
          <span aria-hidden>🔧</span>{" "}
          {skill ? (
            <>
              {t("calling")}:{" "}
              <strong style={{ color: "var(--wg-ink)" }}>{skill}</strong>
              {argsJson ? (
                <>
                  {" "}
                  <span style={{ color: "var(--wg-ink-soft)" }}>
                    {args && Object.keys(args).length > 0
                      ? `(${Object.keys(args).join(", ")})`
                      : "()"}
                  </span>
                </>
              ) : null}
            </>
          ) : (
            message.body
          )}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span
            style={{ fontSize: 10, color: "var(--wg-ink-faint)" }}
            title={new Date(message.created_at).toLocaleString()}
          >
            {formatMessageTime(message.created_at)}
          </span>
          {argsJson && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              data-testid="tool-call-expand"
              style={{
                background: "transparent",
                border: "none",
                padding: "0 4px",
                fontSize: 10,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-faint)",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              {expanded ? t("collapse") : t("expand")}
            </button>
          )}
        </span>
      </div>
      {expanded && argsJson && (
        <pre
          data-testid="tool-call-args"
          style={{
            marginTop: 6,
            marginBottom: 0,
            padding: "8px 10px",
            background: "#fff",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            overflow: "auto",
            maxHeight: 240,
          }}
        >
          {argsJson}
        </pre>
      )}
    </div>
  );
}
