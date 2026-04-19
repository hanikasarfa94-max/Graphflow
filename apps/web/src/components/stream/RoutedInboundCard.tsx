"use client";

// RoutedInboundCard — Phase Q repurposed.
//
// Originally rendered the full rich-options UI inside the personal stream.
// Per north-star §Q.2, inbound signals must NOT interrupt the personal
// stream; they live in a right-side drawer. This file now has two exports:
//
//   * RoutedInboundCard — compact single-line notification that
//     increments the sidebar badge count. Click opens the drawer.
//   * RoutedInboundBody — reusable options/background/reply surface
//     rendered inside the drawer (and nowhere else).
//
// The original rich-layout code now lives in RoutedInboundBody, parameter-
// ised so the drawer (DrawerSignalDetail) can drive picks/custom replies
// through its own state. The stream no longer calls that body directly.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  getRoutingSignal,
  replyRoutingSignal,
  type PersonalMessage,
  type RoutingOption,
  type RoutingSignal,
} from "@/lib/api";
import { useAppShell } from "@/components/shell/AppShellClient";

import type { StreamMember } from "./types";
import { relativeTime } from "./types";

type StreamProps = {
  message: PersonalMessage;
  memberById: Map<string, StreamMember>;
};

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
  padding: "4px 10px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

// ----- Compact stream-line notification (Phase Q primary export) ----------

/**
 * RoutedInboundCard — inline compact notification rendered in the
 * personal stream when a routed inbound signal arrives. Does NOT open
 * the rich options surface inline. Instead, clicking [Open] pops the
 * sidebar drawer via the AppShell context. Badge count is owned by the
 * shell, so the shell's preloaded + drawer-refreshed count is authoritative;
 * this line just provides a deep-link from the stream into the drawer.
 */
export function RoutedInboundCard({ message, memberById }: StreamProps) {
  const t = useTranslations("personal");
  const shell = useAppShell();

  const sourceName = useMemo(() => {
    const m = memberById.get(message.author_id);
    return (
      m?.display_name ??
      message.author_display_name ??
      message.author_username ??
      m?.username ??
      message.author_id.slice(0, 8)
    );
  }, [memberById, message]);

  return (
    <div
      data-testid="personal-inbound-line"
      data-message-id={message.id}
      style={{
        marginBottom: 8,
        marginLeft: 42,
        padding: "8px 12px",
        background: "var(--wg-surface-raised, #faf8f4)",
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        fontSize: 13,
        color: "var(--wg-ink-soft)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
      }}
    >
      <span>
        <span aria-hidden>🔔</span>{" "}
        <span>{t("inbound.inlineLine", { name: sourceName })}</span>
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
          title={new Date(message.created_at).toLocaleString()}
        >
          {relativeTime(message.created_at)}
        </span>
        <button
          type="button"
          onClick={shell.openInbox}
          data-testid="personal-inbound-open-drawer"
          style={{
            ...primaryBtn,
            padding: "4px 10px",
            fontSize: 11,
          }}
        >
          {t("inbound.openDrawer")}
        </button>
      </span>
    </div>
  );
}

// ----- Drawer-hosted full body (reusable) ---------------------------------

function WeightBar({
  weight,
  prominent,
}: {
  weight: number;
  prominent: boolean;
}) {
  const pct = Math.max(0, Math.min(1, weight)) * 100;
  return (
    <div
      aria-label={`weight ${pct.toFixed(0)}%`}
      style={{ display: "flex", alignItems: "center", gap: 8 }}
    >
      <div
        style={{
          width: 80,
          height: 6,
          background: "var(--wg-line-soft, var(--wg-line))",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: prominent ? "var(--wg-accent)" : "var(--wg-ink-soft)",
          }}
        />
      </div>
      <span
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: prominent ? "var(--wg-accent)" : "var(--wg-ink-soft)",
          fontWeight: 600,
          minWidth: 28,
          textAlign: "right",
        }}
      >
        {pct.toFixed(0)}
      </span>
    </div>
  );
}

function OptionRow({
  option,
  prominent,
  onPick,
  busy,
  anyBusy,
}: {
  option: RoutingOption;
  prominent: boolean;
  onPick: (option: RoutingOption) => void;
  busy: boolean;
  anyBusy: boolean;
}) {
  const t = useTranslations("personal");
  const [expanded, setExpanded] = useState(false);
  const hasBackground = Boolean(option.background && option.background.trim());

  return (
    <div
      data-testid="personal-inbound-option"
      data-option-id={option.id}
      data-prominent={prominent ? "true" : "false"}
      style={{
        padding: prominent ? 12 : 10,
        background: prominent
          ? "var(--wg-accent-soft, #fdf4ec)"
          : "var(--wg-surface-raised, #fff)",
        border: prominent
          ? "1px solid var(--wg-accent-ring, var(--wg-accent))"
          : "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <strong
          style={{
            fontSize: prominent ? 15 : 14,
            color: "var(--wg-ink)",
          }}
        >
          {option.label}
        </strong>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {t("inbound.weight")}
          </span>
          <WeightBar weight={option.weight} prominent={prominent} />
        </div>
      </div>
      {option.reason && (
        <div style={{ fontSize: 12, color: "var(--wg-ink-soft)" }}>
          <strong style={{ color: "var(--wg-ink)" }}>{t("inbound.reason")}: </strong>
          {option.reason}
        </div>
      )}
      {option.tradeoff && (
        <div style={{ fontSize: 12, color: "var(--wg-ink-soft)" }}>
          <strong style={{ color: "var(--wg-ink)" }}>{t("inbound.tradeoff")}: </strong>
          {option.tradeoff}
        </div>
      )}
      {hasBackground && (
        <div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            style={{ ...ghostBtn, padding: "2px 6px", fontSize: 11 }}
          >
            {expanded
              ? t("inbound.hideBackground")
              : `${t("inbound.background")} ▾`}
          </button>
          {expanded && (
            <div
              style={{
                marginTop: 6,
                padding: "6px 10px",
                background: "var(--wg-surface-sunk, #faf8f4)",
                borderRadius: "var(--wg-radius-sm, 4px)",
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                whiteSpace: "pre-wrap",
              }}
            >
              {option.background}
            </div>
          )}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
        <button
          type="button"
          onClick={() => onPick(option)}
          disabled={anyBusy}
          data-testid="personal-inbound-pick-btn"
          style={{
            ...primaryBtn,
            opacity: anyBusy && !busy ? 0.5 : 1,
            cursor: anyBusy ? "progress" : "pointer",
          }}
        >
          {busy ? "…" : t("inbound.pickThis")}
        </button>
      </div>
    </div>
  );
}

/**
 * RoutedInboundBody — the full rich-options surface. Parent owns the
 * `signal` state + the pick/custom callbacks. Used by the drawer
 * (DrawerSignalDetail). Not rendered directly inside the stream any
 * more; see the compact RoutedInboundCard above.
 */
export function RoutedInboundBody({
  signal,
  onPick,
  onCustom,
  error,
}: {
  signal: RoutingSignal;
  onPick: (optionId: string) => void | Promise<void>;
  onCustom: (text: string) => void | Promise<void>;
  error?: string | null;
}) {
  const t = useTranslations("personal");
  const [bgExpanded, setBgExpanded] = useState(false);
  const [customText, setCustomText] = useState("");
  const [pickingOptionId, setPickingOptionId] = useState<string | null>(null);
  const [postingCustom, setPostingCustom] = useState(false);

  const prominentOptionId = useMemo(() => {
    if (signal.options.length === 0) return null;
    let best = signal.options[0];
    for (const o of signal.options) {
      if (o.weight > best.weight) best = o;
    }
    return best.id;
  }, [signal]);

  async function handlePick(opt: RoutingOption) {
    if (pickingOptionId || postingCustom) return;
    setPickingOptionId(opt.id);
    try {
      await onPick(opt.id);
    } finally {
      setPickingOptionId(null);
    }
  }

  async function handleCustom() {
    const text = customText.trim();
    if (!text || pickingOptionId || postingCustom) return;
    setPostingCustom(true);
    try {
      await onCustom(text);
      setCustomText("");
    } finally {
      setPostingCustom(false);
    }
  }

  const isReplied = signal.status !== "pending";
  const pickedLabel =
    signal.reply?.picked_label ??
    (signal.reply?.option_id
      ? signal.options.find((o) => o.id === signal.reply?.option_id)?.label
      : null);
  const anyBusy = pickingOptionId !== null || postingCustom;

  return (
    <div
      data-testid="personal-routed-inbound-body"
      data-signal-id={signal.id}
      data-status={signal.status}
      style={{
        padding: 14,
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderLeft: "3px solid var(--wg-accent)",
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div>
        <div
          style={{
            fontSize: 10,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            textTransform: "uppercase",
            letterSpacing: "0.04em",
            marginBottom: 2,
          }}
        >
          {t("inbound.framing")}
        </div>
        <div
          style={{
            color: "var(--wg-ink)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {signal.framing}
        </div>
      </div>

      {signal.background.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setBgExpanded((v) => !v)}
            aria-expanded={bgExpanded}
            data-testid="personal-inbound-bg-toggle"
            style={ghostBtn}
          >
            {bgExpanded
              ? t("inbound.hideBackground")
              : t("inbound.showBackground", { n: signal.background.length })}
          </button>
          {bgExpanded && (
            <ul
              style={{
                listStyle: "none",
                margin: "6px 0 0",
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              {signal.background.map((b, i) => (
                <li
                  key={i}
                  style={{
                    padding: "6px 10px",
                    background: "var(--wg-surface-sunk, #faf8f4)",
                    borderRadius: "var(--wg-radius-sm, 4px)",
                    fontSize: 12,
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  <span
                    style={{
                      display: "inline-block",
                      marginRight: 6,
                      padding: "1px 6px",
                      background: "var(--wg-ink-faint, #e6e3db)",
                      color: "var(--wg-ink)",
                      borderRadius: 3,
                      fontSize: 10,
                      fontFamily: "var(--wg-font-mono)",
                      textTransform: "uppercase",
                    }}
                  >
                    {b.source}
                  </span>
                  <span style={{ whiteSpace: "pre-wrap" }}>{b.snippet}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {isReplied ? (
        <div
          data-testid="personal-inbound-replied"
          style={{
            padding: "8px 12px",
            background: "var(--wg-ok-soft, #edf7ef)",
            border: "1px solid var(--wg-ok, #2f8f4f)",
            borderRadius: "var(--wg-radius)",
            fontSize: 12,
            color: "var(--wg-ok, #2f8f4f)",
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 600,
          }}
        >
          {pickedLabel
            ? t("inbound.replied", { label: pickedLabel })
            : t("inbound.repliedCustom", {
                snippet: (signal.reply?.custom_text ?? "").slice(0, 80),
              })}
        </div>
      ) : (
        <>
          <div
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {t("inbound.options")}
          </div>
          <div
            style={{ display: "flex", flexDirection: "column", gap: 8 }}
          >
            {signal.options.map((opt) => (
              <OptionRow
                key={opt.id}
                option={opt}
                prominent={opt.id === prominentOptionId}
                onPick={handlePick}
                busy={pickingOptionId === opt.id}
                anyBusy={anyBusy}
              />
            ))}
          </div>

          <div
            style={{
              marginTop: 4,
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            <label
              htmlFor={`inbound-custom-${signal.id}`}
              style={{
                fontSize: 10,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              {t("inbound.customReply")}
            </label>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                id={`inbound-custom-${signal.id}`}
                type="text"
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void handleCustom();
                  }
                }}
                placeholder={t("inbound.customPlaceholder")}
                data-testid="personal-inbound-custom-input"
                disabled={anyBusy}
                style={{
                  flex: 1,
                  padding: "6px 10px",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  fontSize: 13,
                  fontFamily: "var(--wg-font-sans)",
                  background: "#fff",
                }}
              />
              <button
                type="button"
                onClick={() => void handleCustom()}
                disabled={!customText.trim() || anyBusy}
                data-testid="personal-inbound-custom-btn"
                style={{
                  ...primaryBtn,
                  opacity: !customText.trim() || anyBusy ? 0.5 : 1,
                }}
              >
                {t("inbound.sendCustom")}
              </button>
            </div>
          </div>
        </>
      )}

      {error && (
        <div
          role="alert"
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}

// ----- Standalone rich card (kept as legacy escape hatch) ----------------
//
// Still callable (a developer might want the old inline full-card UX
// elsewhere, e.g. /audit views) but no longer wired into the personal
// stream by default. Fetches the signal and wires up pick/custom.
export function RoutedInboundFullCard({
  message,
  memberById,
}: {
  message: PersonalMessage;
  memberById: Map<string, StreamMember>;
}) {
  const t = useTranslations("personal");

  const [signal, setSignal] = useState<RoutingSignal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  const signalId = message.linked_id;

  const load = useCallback(async () => {
    if (!signalId) {
      setError(t("inbound.loadFailed"));
      setLoading(false);
      return;
    }
    try {
      const res = await getRoutingSignal(signalId);
      setSignal(res.signal);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? `error ${e.status}`)
            : `error ${e.status}`,
        );
      } else {
        setError(t("inbound.loadFailed"));
      }
    } finally {
      setLoading(false);
    }
  }, [signalId, t]);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void load();
  }, [load]);

  const sourceName = useMemo(() => {
    if (!signal) return "";
    const m = memberById.get(signal.source_user_id);
    return m?.display_name ?? m?.username ?? signal.source_user_id.slice(0, 8);
  }, [signal, memberById]);

  async function handlePick(optionId: string) {
    if (!signal) return;
    try {
      const res = await replyRoutingSignal(signal.id, { option_id: optionId });
      setSignal(res.signal);
    } catch (e) {
      setError(e instanceof ApiError ? `reply ${e.status}` : "reply failed");
    }
  }

  async function handleCustom(text: string) {
    if (!signal) return;
    try {
      const res = await replyRoutingSignal(signal.id, { custom_text: text });
      setSignal(res.signal);
    } catch (e) {
      setError(e instanceof ApiError ? `reply ${e.status}` : "reply failed");
    }
  }

  if (loading) {
    return (
      <div
        data-testid="personal-routed-inbound-loading"
        style={{
          marginBottom: 12,
          padding: "10px 14px",
          background: "var(--wg-surface-sunk, #faf8f4)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {t("inbound.loading")}
      </div>
    );
  }

  if (!signal) {
    return (
      <div
        role="alert"
        style={{
          marginBottom: 12,
          padding: "10px 14px",
          background: "var(--wg-surface-sunk)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 12,
          color: "var(--wg-accent)",
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {error ?? t("inbound.loadFailed")}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          <strong style={{ color: "var(--wg-accent)" }}>
            {t("inbound.from", { name: sourceName })}
          </strong>
        </span>
        <span title={new Date(message.created_at).toLocaleString()}>
          {relativeTime(message.created_at)}
        </span>
      </div>
      <RoutedInboundBody
        signal={signal}
        onPick={handlePick}
        onCustom={handleCustom}
        error={error}
      />
    </div>
  );
}
