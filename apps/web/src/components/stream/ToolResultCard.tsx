"use client";

// ToolResultCard — Phase Q.
//
// Renders the output of a `edge-tool-result` message. Collapsed by
// default showing "✓ N results" or "⚠ error". Expand → shows formatted
// result based on shape:
//
//   * KB search     — list of {title, snippet, id} rows
//   * Decisions     — list of {headline, rationale, id} rows
//   * Risks         — list of {title, severity, id} rows
//   * Unknown       — pretty-printed JSON
//
// Expected PersonalMessage shape (forward-compat):
//   * body: short summary — often "3 results" / "ok" / "error: <msg>"
//   * tool_result: { ok: bool, skill?: string, data?: unknown, error?: string }
//   * linked_id: matching call id
//
// If no structured tool_result field, we attempt a best-effort JSON parse
// of the message body.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { PersonalMessage } from "@/lib/api";

import { relativeTime } from "./types";

type ToolResult = {
  ok?: boolean;
  skill?: string;
  data?: unknown;
  error?: string;
  count?: number;
};

function parseResult(
  message: PersonalMessage & { tool_result?: ToolResult },
): ToolResult {
  if (message.tool_result) return message.tool_result;
  // Best-effort JSON parse of the body as fallback.
  try {
    const parsed = JSON.parse(message.body);
    if (parsed && typeof parsed === "object") {
      return parsed as ToolResult;
    }
  } catch {
    // not JSON — probably a short human summary like "ok: 3 results"
  }
  // Heuristic: treat "error" in the body as an error result.
  const lower = message.body.toLowerCase();
  if (lower.startsWith("error") || lower.startsWith("⚠")) {
    return { ok: false, error: message.body };
  }
  return { ok: true, data: message.body };
}

// Row shape guards for intelligent rendering.
function isKbItem(x: unknown): x is { title: string; snippet?: string; id?: string } {
  return (
    typeof x === "object" &&
    x !== null &&
    "title" in x &&
    typeof (x as Record<string, unknown>).title === "string"
  );
}

function isDecision(
  x: unknown,
): x is { headline?: string; rationale?: string; id?: string } {
  return (
    typeof x === "object" &&
    x !== null &&
    ("headline" in x || "rationale" in x)
  );
}

function isRisk(
  x: unknown,
): x is { title?: string; severity?: string; id?: string } {
  return (
    typeof x === "object" &&
    x !== null &&
    "severity" in x
  );
}

function FormattedResult({ data }: { data: unknown }) {
  // Array of rows — try to format each by shape.
  if (Array.isArray(data)) {
    if (data.length === 0) {
      return (
        <em style={{ color: "var(--wg-ink-soft)" }}>(empty)</em>
      );
    }
    return (
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {data.map((row, i) => {
          // KB item
          if (isKbItem(row)) {
            const r = row as { title: string; snippet?: string; id?: string };
            return (
              <li
                key={i}
                style={{
                  padding: "6px 10px",
                  background: "#fff",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius-sm, 4px)",
                }}
              >
                <strong
                  style={{ fontSize: 12, color: "var(--wg-ink)" }}
                >
                  {r.title}
                </strong>
                {r.snippet && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--wg-ink-soft)",
                      marginTop: 2,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {r.snippet}
                  </div>
                )}
              </li>
            );
          }
          if (isDecision(row)) {
            const r = row as {
              headline?: string;
              rationale?: string;
              id?: string;
            };
            return (
              <li
                key={i}
                style={{
                  padding: "6px 10px",
                  background: "var(--wg-accent-soft, #fdf4ec)",
                  border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
                  borderRadius: "var(--wg-radius-sm, 4px)",
                }}
              >
                <strong style={{ fontSize: 12, color: "var(--wg-accent)" }}>
                  ⚡ {r.headline ?? r.rationale ?? "(decision)"}
                </strong>
                {r.rationale && r.headline && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--wg-ink-soft)",
                      marginTop: 2,
                    }}
                  >
                    {r.rationale}
                  </div>
                )}
              </li>
            );
          }
          if (isRisk(row)) {
            const r = row as {
              title?: string;
              severity?: string;
              id?: string;
            };
            return (
              <li
                key={i}
                style={{
                  padding: "6px 10px",
                  background: "var(--wg-amber-soft, #fef5df)",
                  border: "1px solid var(--wg-amber, #c58b00)",
                  borderRadius: "var(--wg-radius-sm, 4px)",
                  display: "flex",
                  justifyContent: "space-between",
                }}
              >
                <strong style={{ fontSize: 12, color: "var(--wg-ink)" }}>
                  {r.title ?? "(risk)"}
                </strong>
                {r.severity && (
                  <span
                    style={{
                      fontSize: 11,
                      fontFamily: "var(--wg-font-mono)",
                      color: "var(--wg-amber, #c58b00)",
                      textTransform: "uppercase",
                    }}
                  >
                    {r.severity}
                  </span>
                )}
              </li>
            );
          }
          // Unknown row — JSON dump.
          return (
            <li
              key={i}
              style={{
                padding: "6px 10px",
                background: "#fff",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius-sm, 4px)",
                fontFamily: "var(--wg-font-mono)",
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {JSON.stringify(row)}
            </li>
          );
        })}
      </ul>
    );
  }
  if (typeof data === "string") {
    return (
      <div
        style={{
          whiteSpace: "pre-wrap",
          fontSize: 12,
          color: "var(--wg-ink)",
        }}
      >
        {data}
      </div>
    );
  }
  return (
    <pre
      style={{
        margin: 0,
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
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function ToolResultCard({
  message,
}: {
  message: PersonalMessage & { tool_result?: ToolResult };
}) {
  const t = useTranslations("tool");
  const [expanded, setExpanded] = useState(false);

  const result = useMemo(() => parseResult(message), [message]);
  const ok = result.ok !== false && !result.error;

  const count = useMemo(() => {
    if (typeof result.count === "number") return result.count;
    if (Array.isArray(result.data)) return result.data.length;
    return null;
  }, [result]);

  const summary = ok
    ? count !== null
      ? t("resultCount", { n: count })
      : t("resultOk")
    : t("error");

  return (
    <div
      data-testid="tool-result-card"
      data-call-id={message.linked_id ?? undefined}
      data-ok={ok ? "true" : "false"}
      style={{
        marginBottom: 8,
        marginLeft: 42,
        padding: "8px 12px",
        background: "var(--wg-surface-sunk, #faf8f4)",
        border: "1px solid var(--wg-line)",
        borderLeft: ok
          ? "3px solid var(--wg-ok, #2f8f4f)"
          : "3px solid var(--wg-accent)",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontFamily: "var(--wg-font-mono)",
        fontSize: 12,
        color: "var(--wg-ink-soft)",
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
            flex: 1,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          <span aria-hidden>{ok ? "✓" : "⚠"}</span>{" "}
          <strong
            style={{
              color: ok ? "var(--wg-ok, #2f8f4f)" : "var(--wg-accent)",
            }}
          >
            {summary}
          </strong>
          {result.skill && (
            <span style={{ marginLeft: 6, color: "var(--wg-ink-soft)" }}>
              · {result.skill}
            </span>
          )}
          {!ok && result.error && (
            <span style={{ marginLeft: 6, color: "var(--wg-ink-soft)" }}>
              · {result.error}
            </span>
          )}
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span
            style={{ fontSize: 11, color: "var(--wg-ink-soft)" }}
            title={new Date(message.created_at).toLocaleString()}
          >
            {relativeTime(message.created_at)}
          </span>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            data-testid="tool-result-expand"
            style={{
              background: "transparent",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              padding: "2px 6px",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              cursor: "pointer",
            }}
          >
            {expanded ? t("collapse") : t("expand")}
          </button>
        </span>
      </div>
      {expanded && (
        <div
          data-testid="tool-result-body"
          style={{ marginTop: 8, fontFamily: "var(--wg-font-sans)" }}
        >
          {ok ? (
            <FormattedResult data={result.data ?? null} />
          ) : (
            <div
              style={{
                fontSize: 12,
                color: "var(--wg-accent)",
                whiteSpace: "pre-wrap",
              }}
            >
              {result.error ?? message.body}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
