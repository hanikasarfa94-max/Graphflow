"use client";

// RoutedInboundDrawer — Phase Q right-slide drawer.
//
// Lists every pending (and recently replied) routed signal targeted at
// the current user. Clicking an item expands the full RoutedInboundCard
// rich-options surface right inside the drawer — no longer injected into
// the personal stream, per north-star §Q.2.
//
// On mount (when opened) we GET /api/routing/inbox?status=pending and
// merge with the preloaded badge count. After the user replies, we keep
// the item briefly so they see the "replied" state but decrement the
// badge. Drawer is fully self-contained — closing just hides the panel.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  getRoutingSignal,
  listGatedInbox,
  listRoutedInbox,
  replyRoutingSignal,
  type GatedInboxItem as GatedInboxItemType,
  type RoutingSignal,
} from "@/lib/api";

import { relativeTime } from "@/components/stream/types";
import { RoutedInboundBody } from "@/components/stream/RoutedInboundCard";
import { GatedInboxItem } from "./GatedInboxItem";

const DRAWER_WIDTH = 480;

export function RoutedInboundDrawer({
  open,
  onClose,
  onCountChange,
}: {
  open: boolean;
  onClose: () => void;
  onCountChange: (n: number | ((prev: number) => number)) => void;
}) {
  const t = useTranslations("inbox");

  const [signals, setSignals] = useState<RoutingSignal[]>([]);
  const [gatedItems, setGatedItems] = useState<GatedInboxItemType[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fire both endpoints in parallel. Routed signals are 1-to-1
      // routes; gated items are (a) sign-offs this user owes as
      // gate-keeper and (b) open votes they're in the pool for.
      // Merge into one drawer badge so the user sees their total
      // workload at a glance.
      const [routed, gated] = await Promise.all([
        listRoutedInbox({ status: "pending", limit: 100 }),
        listGatedInbox({ limit: 100 }).catch(
          () => ({ ok: false, items: [] as GatedInboxItemType[] }),
        ),
      ]);
      setSignals(routed.signals);
      setGatedItems(gated.items);
      onCountChange(routed.signals.length + gated.items.length);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(`load failed (${e.status})`);
      } else {
        setError("load failed");
      }
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  // Close on ESC.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const pendingCount = useMemo(
    () =>
      signals.filter((s) => s.status === "pending").length + gatedItems.length,
    [signals, gatedItems],
  );

  const handleGatedResolved = useCallback(() => {
    // Drop the gated item from the local list + decrement the badge.
    // Keeps UI snappy without a full refetch; the next drawer open
    // pulls fresh state anyway.
    void refresh();
  }, [refresh]);

  const activeSignal = useMemo(
    () => signals.find((s) => s.id === activeId) ?? null,
    [signals, activeId],
  );

  // When the embedded card resolves a signal (pick-option or custom-
  // reply), it hands us back the updated RoutingSignal. We replace the
  // row in-place, decrement the badge count, and collapse the active
  // detail back to the list so the next signal is easy to scan.
  const handleResolved = useCallback(
    (updated: RoutingSignal) => {
      setSignals((prev) =>
        prev.map((s) => (s.id === updated.id ? updated : s)),
      );
      if (updated.status !== "pending") {
        onCountChange((n) => Math.max(0, n - 1));
        // Keep the item visible briefly, but collapse detail view so
        // users can clearly see the next pending item.
        setTimeout(() => setActiveId(null), 600);
      }
    },
    [onCountChange],
  );

  if (!open) return null;

  return (
    <>
      {/* Scrim */}
      <div
        onClick={onClose}
        aria-hidden
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0, 0, 0, 0.16)",
          zIndex: 40,
        }}
      />
      {/* Panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={t("drawerTitle")}
        data-testid="routed-inbox-drawer"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          width: DRAWER_WIDTH,
          maxWidth: "100vw",
          height: "100vh",
          background: "#fff",
          borderLeft: "1px solid var(--wg-line)",
          boxShadow: "-4px 0 18px rgba(0,0,0,0.08)",
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <header
          style={{
            padding: "14px 16px",
            borderBottom: "1px solid var(--wg-line)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
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
                letterSpacing: "0.06em",
              }}
            >
              {t("eyebrow")}
            </div>
            <strong
              style={{
                fontSize: 16,
                color: "var(--wg-ink)",
                display: "block",
                marginTop: 2,
              }}
            >
              {t("drawerTitle")}
              {pendingCount > 0 && (
                <span
                  style={{
                    marginLeft: 8,
                    fontSize: 11,
                    fontFamily: "var(--wg-font-mono)",
                    fontWeight: 600,
                    color: "var(--wg-accent)",
                  }}
                >
                  {pendingCount}
                </span>
              )}
            </strong>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("close")}
            style={{
              background: "transparent",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              padding: "4px 10px",
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </header>

        {/* Body — list + detail */}
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "8px 0",
          }}
        >
          {loading && signals.length === 0 && (
            <div
              style={{
                padding: "20px 16px",
                color: "var(--wg-ink-soft)",
                fontSize: 13,
                fontFamily: "var(--wg-font-mono)",
                textAlign: "center",
              }}
            >
              {t("loading")}
            </div>
          )}
          {error && (
            <div
              role="alert"
              style={{
                margin: "8px 16px",
                padding: "8px 10px",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-accent)",
                background: "var(--wg-accent-soft, #fdf4ec)",
                borderRadius: "var(--wg-radius)",
              }}
            >
              {error}
            </div>
          )}
          {!loading &&
            !error &&
            signals.length === 0 &&
            gatedItems.length === 0 && (
              <div
                data-testid="routed-inbox-empty"
                style={{
                  padding: "32px 16px",
                  textAlign: "center",
                  color: "var(--wg-ink-soft)",
                  fontSize: 13,
                }}
              >
                {t("noPending")}
              </div>
            )}
          {gatedItems.length > 0 && (
            <ul
              data-testid="gated-inbox-list"
              style={{
                listStyle: "none",
                margin: 0,
                padding: "4px 12px 8px",
                display: "flex",
                flexDirection: "column",
                gap: 10,
                borderBottom:
                  signals.length > 0 ? "1px solid var(--wg-line)" : "none",
                marginBottom: signals.length > 0 ? 8 : 0,
                paddingBottom: signals.length > 0 ? 12 : 8,
              }}
            >
              {gatedItems.map((item) => (
                <li key={item.proposal.id}>
                  <GatedInboxItem
                    item={item}
                    onResolved={handleGatedResolved}
                  />
                </li>
              ))}
            </ul>
          )}
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
            }}
          >
            {signals.map((s) => {
              const expanded = s.id === activeId;
              const pending = s.status === "pending";
              return (
                <li
                  key={s.id}
                  data-testid="routed-inbox-item"
                  data-signal-id={s.id}
                  data-status={s.status}
                  style={{
                    borderBottom: "1px solid var(--wg-line)",
                  }}
                >
                  <button
                    type="button"
                    onClick={() =>
                      setActiveId((prev) => (prev === s.id ? null : s.id))
                    }
                    aria-expanded={expanded}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      background: expanded
                        ? "var(--wg-surface-raised, #faf8f4)"
                        : "transparent",
                      border: "none",
                      padding: "10px 16px",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      gap: 4,
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
                          fontSize: 13,
                          fontWeight: 600,
                          color: pending
                            ? "var(--wg-accent)"
                            : "var(--wg-ink-soft)",
                        }}
                      >
                        {pending
                          ? t("pendingLabel")
                          : t("repliedLabel")}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          fontFamily: "var(--wg-font-mono)",
                          color: "var(--wg-ink-soft)",
                        }}
                        title={
                          s.created_at
                            ? new Date(s.created_at).toLocaleString()
                            : ""
                        }
                      >
                        {s.created_at ? relativeTime(s.created_at) : ""}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: 13,
                        color: "var(--wg-ink)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        display: "-webkit-box",
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: "vertical",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {s.framing}
                    </div>
                  </button>
                  {expanded && (
                    <div
                      style={{
                        padding: "4px 12px 14px",
                        background: "var(--wg-surface-sunk, #faf8f4)",
                      }}
                    >
                      <DrawerSignalDetail
                        signal={s}
                        onResolved={handleResolved}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </aside>
    </>
  );
}

// DrawerSignalDetail — renders the full rich-options card inside the
// drawer. We reuse the RoutedInboundBody helper (extracted from the
// existing RoutedInboundCard) so the options UX is identical.
function DrawerSignalDetail({
  signal,
  onResolved,
}: {
  signal: RoutingSignal;
  onResolved: (updated: RoutingSignal) => void;
}) {
  const [local, setLocal] = useState<RoutingSignal>(signal);
  const [error, setError] = useState<string | null>(null);

  // Refresh on expand — in case the preload list is stale (signal was
  // replied in another tab). Non-blocking — we keep the list row data
  // until the fetch lands.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getRoutingSignal(signal.id);
        if (!cancelled) setLocal(res.signal);
      } catch {
        // swallow — the list row is still rendered
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signal.id]);

  async function handlePick(optionId: string) {
    try {
      const res = await replyRoutingSignal(local.id, { option_id: optionId });
      setLocal(res.signal);
      onResolved(res.signal);
    } catch (e) {
      setError(e instanceof ApiError ? `reply ${e.status}` : "reply failed");
    }
  }

  async function handleCustom(text: string) {
    try {
      const res = await replyRoutingSignal(local.id, { custom_text: text });
      setLocal(res.signal);
      onResolved(res.signal);
    } catch (e) {
      setError(e instanceof ApiError ? `reply ${e.status}` : "reply failed");
    }
  }

  return (
    <RoutedInboundBody
      signal={local}
      onPick={handlePick}
      onCustom={handleCustom}
      error={error}
    />
  );
}
