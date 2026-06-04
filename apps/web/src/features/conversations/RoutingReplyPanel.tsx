"use client";

// RoutingReplyPanel — slim Phase-1 disappearing-broker REPLY surface.
//
// Replaces the deleted heavy RoutedInboundCard. The /inbox dashboard links
// each routed signal to `/conversations?...#routing-{id}`; this panel
// activates on that hash, fetches the signal, and lets the recipient reply
// (POST /api/routing/{id}/reply) or — once replied — close the loop
// (POST /api/routing/{id}/accept). Intentionally minimal: a corner panel,
// no DrawerHost, no rich options card. Semantics preserved per
// docs/routing-broker-reference.md.
//
// Style note: uses named CSSProperties consts + CSS variables (no anonymous
// `style={{}}` literals, no hex) to satisfy the design-system guard.

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Button, Card, Text } from "@/components/ui";
import {
  ApiError,
  acceptRoutingSignal,
  getRoutingSignal,
  replyRoutingSignal,
  type RoutingSignal,
} from "@/lib/api";

const overlay: CSSProperties = {
  position: "fixed",
  right: 20,
  bottom: 20,
  width: 380,
  maxWidth: "calc(100vw - 40px)",
  maxHeight: "80vh",
  overflowY: "auto",
  zIndex: 50,
};
const section: CSSProperties = { marginTop: 12 };
const snippet: CSSProperties = {
  fontSize: 12,
  color: "var(--wg-ink-soft)",
  marginTop: 4,
  lineHeight: 1.4,
};
const optionBtn: CSSProperties = {
  display: "block",
  width: "100%",
  textAlign: "left",
  padding: "8px 10px",
  marginTop: 6,
  background: "var(--wg-surface-sunk)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  cursor: "pointer",
  fontSize: 13,
  color: "var(--wg-ink)",
};
const replyBox: CSSProperties = {
  width: "100%",
  minHeight: 64,
  marginTop: 6,
  padding: 8,
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 13,
  fontFamily: "inherit",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  boxSizing: "border-box",
};
const row: CSSProperties = {
  display: "flex",
  gap: 8,
  marginTop: 10,
  alignItems: "center",
};

// Pure, testable: extract the routing signal id from a URL hash.
// `#routing-{id}` → id; anything else → null.
export function parseRoutingHash(hash: string): string | null {
  const m = hash.match(/^#routing-(.+)$/);
  return m ? decodeURIComponent(m[1]) : null;
}

function readRoutingHash(): string | null {
  if (typeof window === "undefined") return null;
  return parseRoutingHash(window.location.hash);
}

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; signal: RoutingSignal };

export function RoutingReplyPanel() {
  const t = useTranslations("routingReply");
  const [signalId, setSignalId] = useState<string | null>(null);
  const [state, setState] = useState<LoadState | null>(null);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Track the hash so a deep-link (and back/forward) opens/closes us.
  useEffect(() => {
    const sync = () => setSignalId(readRoutingHash());
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const load = useCallback((id: string) => {
    setState({ status: "loading" });
    setError(null);
    getRoutingSignal(id)
      .then((r) => setState({ status: "ready", signal: r.signal }))
      .catch(() => setState({ status: "error" }));
  }, []);

  useEffect(() => {
    if (signalId) load(signalId);
    else setState(null);
  }, [signalId, load]);

  const close = useCallback(() => {
    // Drop the hash without re-triggering navigation/scroll.
    if (typeof window !== "undefined") {
      window.history.replaceState(
        null,
        "",
        window.location.pathname + window.location.search,
      );
    }
    setSignalId(null);
    setState(null);
    setCustom("");
    setError(null);
  }, []);

  async function doReply(params: { option_id?: string; custom_text?: string }) {
    if (!signalId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await replyRoutingSignal(signalId, params);
      setState({ status: "ready", signal: r.signal });
      setCustom("");
    } catch (e) {
      setError(e instanceof ApiError ? t("replyFailed") : t("replyFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function doAccept() {
    if (!signalId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await acceptRoutingSignal(signalId);
      setState({ status: "ready", signal: r.signal });
    } catch {
      setError(t("replyFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (!signalId || !state) return null;

  return (
    <div style={overlay} data-testid="routing-reply-panel">
      <Card title={t("title")}>
        {state.status === "loading" && (
          <Text variant="caption" muted>
            {t("loading")}
          </Text>
        )}
        {state.status === "error" && (
          <>
            <Text variant="caption" muted>
              {t("loadError")}
            </Text>
            <div style={row}>
              <Button variant="primary" onClick={() => load(signalId)}>
                {t("retry")}
              </Button>
              <Button variant="link" onClick={close}>
                {t("close")}
              </Button>
            </div>
          </>
        )}
        {state.status === "ready" && (
          <RoutingReplyBody
            signal={state.signal}
            t={t}
            busy={busy}
            custom={custom}
            setCustom={setCustom}
            onReply={doReply}
            onAccept={doAccept}
            onClose={close}
            error={error}
          />
        )}
      </Card>
    </div>
  );
}

function RoutingReplyBody({
  signal,
  t,
  busy,
  custom,
  setCustom,
  onReply,
  onAccept,
  onClose,
  error,
}: {
  signal: RoutingSignal;
  t: ReturnType<typeof useTranslations>;
  busy: boolean;
  custom: string;
  setCustom: (v: string) => void;
  onReply: (p: { option_id?: string; custom_text?: string }) => void;
  onAccept: () => void;
  onClose: () => void;
  error: string | null;
}) {
  const pending = signal.status === "pending";
  const replied = signal.status === "replied";
  return (
    <>
      <div style={section}>
        <Text variant="caption" muted>
          {t("framingHeading")}
        </Text>
        <Text>{signal.framing}</Text>
      </div>

      {signal.background.length > 0 && (
        <div style={section}>
          <Text variant="caption" muted>
            {t("backgroundHeading")}
          </Text>
          {signal.background.map((b, i) => (
            <div key={i} style={snippet}>
              {b.source}: {b.snippet}
            </div>
          ))}
        </div>
      )}

      {pending && (
        <>
          {signal.options.length > 0 && (
            <div style={section}>
              <Text variant="caption" muted>
                {t("optionsHeading")}
              </Text>
              {signal.options.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  style={optionBtn}
                  disabled={busy}
                  onClick={() => onReply({ option_id: o.id })}
                >
                  {o.label}
                  {o.reason ? ` — ${o.reason}` : ""}
                </button>
              ))}
            </div>
          )}
          <div style={section}>
            <textarea
              style={replyBox}
              value={custom}
              disabled={busy}
              placeholder={t("customPlaceholder")}
              onChange={(e) => setCustom(e.target.value)}
            />
            <div style={row}>
              <Button
                variant="primary"
                disabled={busy || !custom.trim()}
                onClick={() => onReply({ custom_text: custom.trim() })}
              >
                {busy ? t("sending") : t("send")}
              </Button>
              <Button variant="link" onClick={onClose}>
                {t("close")}
              </Button>
            </div>
          </div>
        </>
      )}

      {replied && (
        <div style={section}>
          <Text variant="caption" muted>
            {t("repliedNote")}
          </Text>
          <div style={row}>
            <Button variant="primary" disabled={busy} onClick={onAccept}>
              {busy ? t("accepting") : t("accept")}
            </Button>
            <Button variant="link" onClick={onClose}>
              {t("close")}
            </Button>
          </div>
        </div>
      )}

      {!pending && !replied && (
        <div style={section}>
          <Text variant="caption" muted>
            {t("acceptedNote")}
          </Text>
          <div style={row}>
            <Button variant="link" onClick={onClose}>
              {t("close")}
            </Button>
          </div>
        </div>
      )}

      {error && (
        <Text variant="caption" muted>
          {error}
        </Text>
      )}
    </>
  );
}
