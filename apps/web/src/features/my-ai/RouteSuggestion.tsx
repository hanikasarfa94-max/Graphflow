"use client";

// RouteSuggestion — slim Phase-1 disappearing-broker SEND surface.
//
// Replaces the deleted 1.3k-LOC RouteProposalCard. When the edge agent
// returns a *discovery* route_proposal (My-AI composer), this renders a
// minimal inline "Route to {name}?" affordance per target: Send routes
// the ask, Edit reveals the editable B-facing draft (the disclosure
// gate), Dismiss hides it locally. Gated proposals are intentionally
// ignored here (no scrimmage / gated / pre-answer UI). Send posts to the
// canonical POST /api/routing/proposals/{id}/confirm via
// confirmRouteProposal. Semantics per docs/routing-broker-reference.md.
//
// Style note: named CSSProperties consts + CSS variables only (no
// anonymous style={{}} literals, no hex) so the design guard stays green
// without an allowlist entry.

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";
import {
  ApiError,
  acceptRoutingSignal,
  confirmRouteProposal,
  getRoutingSignal,
  type PersonalRouteTarget,
  type RoutingSignal,
} from "@/lib/api";

export interface RouteProposalView {
  routeProposalId: string;
  framing: string;
  targets: PersonalRouteTarget[];
}

// Bounded poll: every 5s, up to ~5 min, plus an immediate fire on
// window focus. Keeps the loop watchable in the demo without a WS
// dependency, and can never run away (capped + stops on terminal state).
const POLL_MS = 5000;
const MAX_POLLS = 60;

// --- pure, testable helpers ------------------------------------------------

// UI phase for the sender-side routed-reply card from a signal status.
export type RoutedPhase = "waiting" | "replied" | "accepted" | "closed";
export function routedPhase(status: string | undefined): RoutedPhase {
  switch (status) {
    case undefined:
    case "pending":
      return "waiting";
    case "replied":
      return "replied";
    case "accepted":
      return "accepted";
    default:
      return "closed"; // declined / expired / unknown
  }
}

// The recipient's reply, as the sender should read it: a picked option
// label wins, else free text, else null (nothing to show yet).
export function replyText(reply: RoutingSignal["reply"]): string | null {
  if (!reply) return null;
  const label = reply.picked_label?.trim();
  if (label) return label;
  const custom = reply.custom_text?.trim();
  if (custom) return custom;
  return null;
}

export function shouldKeepPolling(
  status: string | undefined,
  attempts: number,
  max: number = MAX_POLLS,
): boolean {
  return routedPhase(status) === "waiting" && attempts < max;
}

// Which draft text gets sent for a target: the user's edit wins, else the
// agent's B-facing draft, else the proposal framing (A-voice fallback).
export function resolveDraft(
  edited: string | undefined,
  target: PersonalRouteTarget,
  framing: string,
): string {
  if (edited !== undefined && edited.trim()) return edited.trim();
  if (target.b_facing_draft && target.b_facing_draft.trim()) {
    return target.b_facing_draft.trim();
  }
  return framing.trim();
}

const wrap: CSSProperties = {
  marginTop: 8,
  padding: "10px 12px",
  background: "var(--wg-surface-sunk)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};
const targetRow: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  paddingTop: 8,
};
const rowHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  flexWrap: "wrap",
};
const actions: CSSProperties = { display: "flex", gap: 8, alignItems: "center" };
const draftBox: CSSProperties = {
  width: "100%",
  minHeight: 56,
  padding: 8,
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 13,
  fontFamily: "inherit",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  boxSizing: "border-box",
};

export function RouteSuggestion({ proposal }: { proposal: RouteProposalView }) {
  const t = useTranslations("routeSuggestion");
  const [dismissed, setDismissed] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [sent, setSent] = useState<{ signalId: string; name: string } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  if (dismissed || proposal.targets.length === 0) return null;

  if (sent) {
    return <RoutedReplyInline signalId={sent.signalId} name={sent.name} />;
  }

  async function send(target: PersonalRouteTarget) {
    setBusyId(target.user_id);
    setError(null);
    try {
      const res = await confirmRouteProposal(
        proposal.routeProposalId,
        target.user_id,
        resolveDraft(drafts[target.user_id], target, proposal.framing),
      );
      setSent({ signalId: res.signal_id, name: target.display_name });
    } catch (e) {
      setError(e instanceof ApiError ? t("failed") : t("failed"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div style={wrap} data-testid="route-suggestion">
      <Text variant="caption" muted>
        {t("prompt")}
      </Text>
      {proposal.targets.map((target) => {
        const isEditing = !!editing[target.user_id];
        const busy = busyId === target.user_id;
        return (
          <div key={target.user_id} style={targetRow}>
            <div style={rowHead}>
              <Text>{t("ask", { name: target.display_name })}</Text>
              {target.rationale ? (
                <Text variant="caption" muted>
                  {target.rationale}
                </Text>
              ) : null}
            </div>
            {isEditing ? (
              <textarea
                style={draftBox}
                value={resolveDraft(
                  drafts[target.user_id],
                  target,
                  proposal.framing,
                )}
                disabled={busy}
                placeholder={t("draftPlaceholder", { name: target.display_name })}
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [target.user_id]: e.target.value }))
                }
              />
            ) : null}
            <div style={actions}>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => send(target)}
              >
                {busy ? t("sending") : t("send")}
              </Button>
              <Button
                variant="link"
                onClick={() =>
                  setEditing((s) => ({
                    ...s,
                    [target.user_id]: !s[target.user_id],
                  }))
                }
              >
                {isEditing ? t("hideEdit") : t("edit")}
              </Button>
            </div>
          </div>
        );
      })}
      <div style={actions}>
        <Button variant="link" onClick={() => setDismissed(true)}>
          {t("dismiss")}
        </Button>
      </div>
      {error ? (
        <Text variant="caption" muted>
          {error}
        </Text>
      ) : null}
    </div>
  );
}

// Sender-side close of the loop: after dispatch we hold the signal_id and
// poll for the recipient's reply, then offer "Close the loop" (accept).
// Bounded + stops on terminal status / unmount so it can't run away.
function RoutedReplyInline({
  signalId,
  name,
}: {
  signalId: string;
  name: string;
}) {
  const t = useTranslations("routeSuggestion");
  const [signal, setSignal] = useState<RoutingSignal | null>(null);
  const [closing, setClosing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const attemptsRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const tick = async () => {
      if (cancelled || doneRef.current) return;
      attemptsRef.current += 1;
      try {
        const r = await getRoutingSignal(signalId);
        if (cancelled) return;
        setSignal(r.signal);
        if (routedPhase(r.signal.status) !== "waiting") {
          doneRef.current = true;
          stop();
        } else if (attemptsRef.current >= MAX_POLLS) {
          stop();
        }
      } catch {
        if (attemptsRef.current >= MAX_POLLS) stop();
      }
    };
    void tick(); // immediate
    timer = setInterval(() => void tick(), POLL_MS);
    const onFocus = () => {
      if (!doneRef.current) void tick();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      stop();
      window.removeEventListener("focus", onFocus);
    };
  }, [signalId]);

  const phase = routedPhase(signal?.status);

  if (phase === "waiting") {
    return (
      <div style={wrap} data-testid="route-suggestion">
        <Text variant="caption" muted>
          {t("awaiting", { name })}
        </Text>
      </div>
    );
  }

  if (phase === "replied") {
    const body = replyText(signal?.reply ?? null);
    async function close() {
      setClosing(true);
      setErr(null);
      try {
        const r = await acceptRoutingSignal(signalId);
        setSignal(r.signal);
      } catch {
        setErr(t("failed"));
      } finally {
        setClosing(false);
      }
    }
    return (
      <div style={wrap} data-testid="route-suggestion">
        <Text>{t("replied", { name })}</Text>
        {body ? (
          <Text variant="caption" muted>
            {body}
          </Text>
        ) : null}
        <div style={actions}>
          <Button variant="primary" disabled={closing} onClick={close}>
            {closing ? t("closing") : t("closeLoop")}
          </Button>
        </div>
        {err ? (
          <Text variant="caption" muted>
            {err}
          </Text>
        ) : null}
      </div>
    );
  }

  // accepted / closed
  return (
    <div style={wrap} data-testid="route-suggestion">
      <Text variant="caption" muted>
        {t("closed", { name })}
      </Text>
    </div>
  );
}
