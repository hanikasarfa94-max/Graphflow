"use client";

// RoutedReplyCard — Phase Q symmetric source-side surface.
//
// Rendered in the source's personal stream when the routed target replied
// (north-star §Q.4). Previously this card only had an Accept button — that
// was a bug. The source must get the full symmetric surface:
//
//   * Accept           — mark the loop closed, optionally crystallize
//   * Counter-back     — more info / different framing; dispatches a new
//                        routed signal back to the same target, keyed to
//                        the prior signal as parent
//   * Escalate         — request sync; flagged to the stream
//   * Reply custom     — free-form follow-up, same backend path as
//                        counter-back but framed as "follow-up"
//
// Acceptance is a LOCAL visual state in v1 (no backend /accept endpoint on
// RoutingSignal yet — the signal is already in `replied` state from the
// target's POST /reply). Counter-back + Reply custom route through
// POST /api/routing/dispatch with parent_signal_id carried as a background
// snippet. Escalate is v1-scaffolded: posts a follow-up to the composer
// so the source can type and send an escalation in-stream.

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  acceptRoutingSignal,
  createDMStream,
  dispatchCounterBack,
  getRoutingSignal,
  type PersonalMessage,
  type RoutingSignal,
} from "@/lib/api";

import { CitedClaimList } from "./CitedClaimList";
import type { StreamMember } from "./types";
import { relativeTime,
  formatMessageTime } from "./types";

type Props = {
  message: PersonalMessage;
  memberById: Map<string, StreamMember>;
  onFollowUp?: (prefill: string) => void;
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
  padding: "6px 12px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 12,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

const amberBtn: CSSProperties = {
  padding: "6px 12px",
  background: "transparent",
  color: "var(--wg-amber, #c58b00)",
  border: "1px solid var(--wg-amber, #c58b00)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

type ActionMode = null | "counter" | "custom";

export function RoutedReplyCard({ message, memberById, onFollowUp }: Props) {
  const t = useTranslations("personal");

  const [signal, setSignal] = useState<RoutingSignal | null>(null);
  const [dmHref, setDmHref] = useState<string | null>(null);
  const [mode, setMode] = useState<ActionMode>(null);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [optimisticAccept, setLocallyAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  const signalId = message.linked_id;
  // Server-confirmed acceptance OR an in-flight optimistic click. The
  // server side wins when both exist (e.g. a refresh after the click).
  const isAccepted = signal?.status === "accepted" || optimisticAccept;

  const load = useCallback(async () => {
    if (!signalId) return;
    try {
      const res = await getRoutingSignal(signalId);
      setSignal(res.signal);
    } catch {
      // Non-fatal — the body fallback still renders.
    }
  }, [signalId]);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void load();
  }, [load]);

  const targetName = useMemo(() => {
    if (!signal) return "";
    const m = memberById.get(signal.target_user_id);
    return m?.display_name ?? m?.username ?? signal.target_user_id.slice(0, 8);
  }, [signal, memberById]);

  const pickedLabel = useMemo(() => {
    if (!signal) return null;
    if (signal.reply?.picked_label) return signal.reply.picked_label;
    if (signal.reply?.option_id) {
      return (
        signal.options.find((o) => o.id === signal.reply?.option_id)?.label ??
        null
      );
    }
    return null;
  }, [signal]);

  const customText = signal?.reply?.custom_text ?? null;

  async function openDM() {
    if (!signal) return;
    try {
      const res = await createDMStream(signal.target_user_id);
      if (res.ok && res.stream?.id) {
        setDmHref(`/streams/${res.stream.id}`);
        if (typeof window !== "undefined") {
          window.location.href = `/streams/${res.stream.id}`;
        }
      }
    } catch {
      // swallow — link is optional
    }
  }

  // Accept — persists status='accepted' on the signal so a refresh
  // doesn't reopen the button. Optimistic UI flips first; on backend
  // failure we revert + surface the error so the click isn't lost.
  async function handleAccept() {
    if (!signalId || posting) return;
    if (signal?.status === "accepted") return;
    setLocallyAccepted(true);
    setError(null);
    if (onFollowUp) {
      const snippet = pickedLabel ?? customText?.slice(0, 40) ?? "";
      onFollowUp(
        t("reply.acceptPrefill", { name: targetName || "", snippet }),
      );
    }
    setPosting(true);
    try {
      const res = await acceptRoutingSignal(signalId);
      if (res.signal) setSignal(res.signal);
    } catch (e) {
      setLocallyAccepted(false);
      setError(
        e instanceof ApiError ? `accept ${e.status}` : "accept failed",
      );
    } finally {
      setPosting(false);
    }
  }

  // Escalate — v1: prefill the composer so the user types the escalation
  // framing and sends in-stream. No backend primitive for escalating a
  // RoutingSignal yet; this keeps parity with the stream-level Escalate
  // gesture.
  function handleEscalate() {
    if (!onFollowUp) return;
    onFollowUp(t("reply.escalatePrefill", { name: targetName || "" }));
  }

  // Counter-back — dispatch a fresh RoutedSignal to the same target,
  // carrying the parent signal id as lineage. This IS the backend path:
  // POST /api/routing/dispatch with a background snippet pointing back
  // at the prior signal.
  async function submitCounter() {
    if (!signal || !draft.trim() || posting) return;
    setPosting(true);
    setError(null);
    try {
      await dispatchCounterBack({
        target_user_id: signal.target_user_id,
        project_id: signal.project_id,
        framing: draft.trim(),
        parent_signal_id: signal.id,
      });
      setDraft("");
      setMode(null);
      // Visual ack — the newly dispatched signal will show up as its own
      // turn shortly via WS; until then we display an inline "sent" note.
      if (onFollowUp) {
        onFollowUp(
          t("reply.counterSentPrefill", { name: targetName || "" }),
        );
      }
    } catch (e) {
      setError(
        e instanceof ApiError ? `dispatch ${e.status}` : "dispatch failed",
      );
    } finally {
      setPosting(false);
    }
  }

  // Reply custom — same backend path as counter-back; different framing
  // prefix so target sees "follow-up" context.
  async function submitCustom() {
    if (!signal || !draft.trim() || posting) return;
    setPosting(true);
    setError(null);
    try {
      await dispatchCounterBack({
        target_user_id: signal.target_user_id,
        project_id: signal.project_id,
        framing: `${t("reply.customFramingPrefix")} ${draft.trim()}`,
        parent_signal_id: signal.id,
      });
      setDraft("");
      setMode(null);
    } catch (e) {
      setError(
        e instanceof ApiError ? `dispatch ${e.status}` : "dispatch failed",
      );
    } finally {
      setPosting(false);
    }
  }

  return (
    <div
      data-testid="personal-routed-reply"
      data-message-id={message.id}
      data-signal-id={signal?.id}
      style={{
        // Lightened: sunk surface, no hard accent border. Still a card
        // because it carries action buttons (Accept / Counter / Escalate).
        padding: "10px 12px",
        marginRight: "20%",
        background: "var(--wg-surface-sunk, #faf8f4)",
        border: "1px solid var(--wg-line-soft, var(--wg-line))",
        borderRadius: "var(--wg-radius)",
        fontSize: 13,
        display: "flex",
        flexDirection: "column",
        gap: 6,
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
        }}
      >
        <span>
          <strong style={{ color: "var(--wg-accent)" }}>
            {t("reply.header", { name: targetName || "…" })}
          </strong>
        </span>
        <span title={new Date(message.created_at).toLocaleString()}>
          {formatMessageTime(message.created_at)}
        </span>
      </div>

      <div
        style={{
          color: message.uncited === true ? "var(--wg-ink-faint)" : "var(--wg-ink)",
          fontStyle: message.uncited === true ? "italic" : "normal",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {pickedLabel ? (
          <>
            <strong>{pickedLabel}</strong>
            {customText && (
              <div style={{ color: "var(--wg-ink-soft)", marginTop: 4 }}>
                {customText}
              </div>
            )}
          </>
        ) : customText ? (
          customText
        ) : (
          message.body
        )}
      </div>

      {message.claims && message.claims.length > 0 && (
        <CitedClaimList
          projectId={message.project_id ?? ""}
          claims={message.claims}
        />
      )}

      {isAccepted ? (
        <div
          data-testid="personal-reply-accepted"
          style={{
            padding: "6px 10px",
            background: "var(--wg-ok-soft, #edf7ef)",
            border: "1px solid var(--wg-ok, #2f8f4f)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ok, #2f8f4f)",
            fontWeight: 600,
          }}
        >
          ✓ {t("reply.acceptedLocal")}
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
            marginTop: 4,
          }}
          data-testid="personal-reply-actions"
        >
          <button
            type="button"
            onClick={handleAccept}
            data-testid="personal-reply-accept-btn"
            data-action-hint="accept"
            style={primaryBtn}
          >
            {t("reply.acceptAction")}
          </button>
          <button
            type="button"
            onClick={() => {
              setMode((m) => (m === "counter" ? null : "counter"));
              setDraft("");
              setError(null);
            }}
            data-testid="personal-reply-counter-btn"
            data-action-hint="counter_back"
            style={ghostBtn}
            aria-expanded={mode === "counter"}
          >
            {mode === "counter"
              ? t("reply.cancel")
              : t("reply.counterBackAction")}
          </button>
          <button
            type="button"
            onClick={handleEscalate}
            data-testid="personal-reply-escalate-btn"
            data-action-hint="escalate"
            style={amberBtn}
          >
            {t("reply.escalateAction")}
          </button>
          <button
            type="button"
            onClick={() => {
              setMode((m) => (m === "custom" ? null : "custom"));
              setDraft("");
              setError(null);
            }}
            data-testid="personal-reply-custom-btn"
            data-action-hint="reply_custom"
            style={ghostBtn}
            aria-expanded={mode === "custom"}
          >
            {mode === "custom"
              ? t("reply.cancel")
              : t("reply.replyCustomAction")}
          </button>
        </div>
      )}

      {mode !== null && !isAccepted && (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 6 }}>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                if (mode === "counter") void submitCounter();
                else void submitCustom();
              }
            }}
            rows={3}
            placeholder={
              mode === "counter"
                ? t("reply.counterPlaceholder")
                : t("reply.customPlaceholder")
            }
            data-testid="personal-reply-textarea"
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
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={() => {
                if (mode === "counter") void submitCounter();
                else void submitCustom();
              }}
              disabled={!draft.trim() || posting}
              data-testid="personal-reply-submit-btn"
              style={{
                ...primaryBtn,
                opacity: !draft.trim() || posting ? 0.5 : 1,
              }}
            >
              {posting ? t("reply.sending") : t("reply.send")}
            </button>
          </div>
        </div>
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

      {signal && (
        <div style={{ marginTop: 4 }}>
          {dmHref ? (
            <a
              href={dmHref}
              style={{
                ...ghostBtn,
                textDecoration: "none",
                display: "inline-block",
              }}
            >
              {t("reply.viewInDM")}
            </a>
          ) : (
            <button
              type="button"
              onClick={() => void openDM()}
              data-testid="personal-reply-dm-link"
              style={ghostBtn}
            >
              {t("reply.viewInDM")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
