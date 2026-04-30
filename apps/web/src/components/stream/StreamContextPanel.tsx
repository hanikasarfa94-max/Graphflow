"use client";

// StreamContextPanel — Batch F.11 (Gap D from html2 reconstruction plan).
//
// Per html2 lines 184-186: a "上下文口径" toggle on the chat surface that
// reveals which sources Edge consults when answering. Without this lever
// users can't see — let alone change — what's in the agent's context,
// which leaks every time a surprising answer comes back.
//
// Mounted in BOTH PersonalStream (my thread) and StreamView (team room)
// via the `actions` slot of StreamCompactToolbar. Scope is persisted in
// localStorage keyed by `stream:{streamKey}:scope` so toggles survive
// reloads. Other components (the message sender) can read the latest
// scope via getStreamScope() or listen to the `workgraph:stream-scope`
// window event for live updates.
//
// Defaults track the html2 spec:
//   graph  = on   — project graph is the trustable canonical context
//   kb     = on   — KB items + decisions, the second-most-trusted layer
//   dms    = off  — private messages stay out of agent context by
//                   default to avoid permission contamination across
//                   the room
//   audit  = off  — audit log is verbose; opt in only when explaining
//                   causation
//
// Backend wiring (sending the scope on message-send) is intentionally a
// follow-up: the panel saves + broadcasts, but the existing
// PersonalStream / Composer flows do not yet read these flags. When
// they do, listen on the event below and include `scope` in the
// `/api/streams/.../messages` POST body.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

const SCOPE_KEYS = ["graph", "kb", "dms", "audit"] as const;
export type ScopeKey = (typeof SCOPE_KEYS)[number];
export type StreamScope = Record<ScopeKey, boolean>;

const DEFAULT_SCOPE: StreamScope = {
  graph: true,
  kb: true,
  dms: false,
  audit: false,
};

const STORAGE_PREFIX = "stream:";
const SCOPE_EVENT = "workgraph:stream-scope";

function storageKey(streamKey: string): string {
  return `${STORAGE_PREFIX}${streamKey}:scope`;
}

export function getStreamScope(streamKey: string): StreamScope {
  if (typeof window === "undefined") return { ...DEFAULT_SCOPE };
  try {
    const raw = window.localStorage.getItem(storageKey(streamKey));
    if (!raw) return { ...DEFAULT_SCOPE };
    const parsed = JSON.parse(raw) as Partial<StreamScope>;
    return { ...DEFAULT_SCOPE, ...parsed };
  } catch {
    return { ...DEFAULT_SCOPE };
  }
}

function saveStreamScope(streamKey: string, scope: StreamScope): void {
  try {
    window.localStorage.setItem(storageKey(streamKey), JSON.stringify(scope));
  } catch {
    // Quota exceeded / private mode — non-fatal.
  }
}

export function StreamContextPanel({ streamKey }: { streamKey: string }) {
  const t = useTranslations("stream.contextPanel");
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<StreamScope>(DEFAULT_SCOPE);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setScope(getStreamScope(streamKey));
    setHydrated(true);
  }, [streamKey]);

  const toggle = (k: ScopeKey) => {
    setScope((prev) => {
      const next = { ...prev, [k]: !prev[k] };
      saveStreamScope(streamKey, next);
      window.dispatchEvent(
        new CustomEvent(SCOPE_EVENT, {
          detail: { streamKey, scope: next },
        }),
      );
      return next;
    });
  };

  const enabledCount = SCOPE_KEYS.filter((k) => scope[k]).length;
  const buttonLabel = hydrated
    ? t("buttonCount", { n: enabledCount, total: SCOPE_KEYS.length })
    : t("buttonLoading");

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        data-testid="stream-context-button"
        title={t("hint")}
        style={{
          height: 28,
          padding: "0 12px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          fontWeight: 600,
          color: open ? "var(--wg-accent)" : "var(--wg-ink-soft)",
          background: open ? "var(--wg-accent-soft)" : "var(--wg-surface)",
          border: `1px solid ${open ? "var(--wg-accent)" : "var(--wg-line)"}`,
          borderRadius: 999,
          cursor: "pointer",
          transition: "background 140ms, color 140ms, border-color 140ms",
        }}
      >
        {t("buttonLabel")} · {buttonLabel}
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label={t("title")}
          data-testid="stream-context-panel"
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 6px)",
            width: 320,
            background: "var(--wg-surface)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-md)",
            boxShadow: "var(--wg-shadow-lg)",
            padding: 14,
            zIndex: 20,
          }}
        >
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--wg-accent)",
              fontWeight: 700,
              fontFamily: "var(--wg-font-mono)",
              marginBottom: 6,
            }}
          >
            {t("kicker")}
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--wg-ink)",
              marginBottom: 4,
            }}
          >
            {t("title")}
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--wg-ink-soft)",
              lineHeight: 1.5,
              marginBottom: 12,
            }}
          >
            {t("subtitle")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {SCOPE_KEYS.map((k) => (
              <ScopeRow
                key={k}
                label={t(`source.${k}.label`)}
                hint={t(`source.${k}.hint`)}
                enabled={scope[k]}
                onToggle={() => toggle(k)}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ScopeRow({
  label,
  hint,
  enabled,
  onToggle,
}: {
  label: string;
  hint: string;
  enabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={enabled}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 12,
        alignItems: "center",
        padding: "10px 12px",
        background: enabled ? "var(--wg-accent-soft)" : "var(--wg-surface-sunk)",
        border: `1px solid ${enabled ? "var(--wg-accent-ring)" : "var(--wg-line)"}`,
        borderRadius: "var(--wg-radius-sm)",
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "inherit",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--wg-ink)",
            marginBottom: 2,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            lineHeight: 1.45,
          }}
        >
          {hint}
        </div>
      </div>
      <span
        aria-hidden
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          fontWeight: 700,
          color: enabled ? "var(--wg-accent)" : "var(--wg-ink-faint)",
          padding: "3px 8px",
          background: "var(--wg-surface)",
          border: `1px solid ${enabled ? "var(--wg-accent)" : "var(--wg-line)"}`,
          borderRadius: 999,
          letterSpacing: "0.04em",
        }}
      >
        {enabled ? "ON" : "OFF"}
      </span>
    </button>
  );
}

export const STREAM_SCOPE_EVENT = SCOPE_EVENT;
