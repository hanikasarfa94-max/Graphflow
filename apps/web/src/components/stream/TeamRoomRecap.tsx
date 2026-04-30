"use client";

// TeamRoomRecap — Batch F.12 (Gap F from html2 reconstruction plan).
//
// Per html2 line 195: a bottom-anchored "current focus" panel inside
// the team room — a one-glance summary of what the room should be
// thinking about ("Boss-1 怒退率高;Switch 性能预算待确认;...
// 建议下一条消息明确是询问事实还是请求决策。").
//
// The deployed version goes a step beyond the static html2 sketch:
//   * Derived client-side from ProjectState — no LLM call needed.
//   * Animated reveal (drift up + fade) on first paint, with a brief
//     post-mount delay so it doesn't compete with the StreamView's
//     own first-render flicker.
//   * Dismissable per-session per-stream (sessionStorage). Comes back
//     on the next visit, doesn't nag during the current one.
//   * Hides itself if there's nothing to summarize — empty rooms
//     don't get a "current focus is: nothing" panel.
//   * Respects prefers-reduced-motion (drops the entry animation).
//
// Mount: once, inside the team-room page. Position is viewport-fixed
// at bottom-right with a max-width — close enough to html2's
// "absolute inside the chat shell" feel without forcing us into
// StreamView's 720-line internals.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import type { Commitment, ProjectState } from "@/lib/api";

// CSS-side delay before the entry animation starts. Lets the team-room
// chat finish its own first-paint flicker before the recap floats up.
const ENTRY_DELAY_MS = 220;
const ENTRY_DUR_MS = 320;
const EXIT_MS = 200;
// Two paint frames is enough to guarantee the initial opacity:0
// snapshot renders before we toggle to opacity:1 — that's what makes
// the CSS transition fire instead of the browser short-circuiting it.
const PAINT_GUARD_MS = 32;

type Focus = {
  highRiskTitles: string[];
  medRiskCount: number;
  openCommitments: number;
  recentDecisions: number;
  // Suggestion line — the html2 prompt nudge for what kind of
  // message the user should send next.
  suggestionKey: "ask_or_decide" | "follow_up_risk" | "ratify_decision";
};

function deriveFocus(state: ProjectState | null): Focus | null {
  if (!state) return null;

  const openRisks = state.graph.risks.filter((r) => {
    const s = (r.status || "").toLowerCase();
    return s !== "closed" && s !== "resolved";
  });
  const highRiskTitles = openRisks
    .filter((r) => (r.severity || "").toLowerCase() === "high")
    .map((r) => r.title)
    .slice(0, 2);
  const medRiskCount = openRisks.filter(
    (r) => (r.severity || "").toLowerCase() === "medium",
  ).length;

  const openCommitments = (state.commitments || []).filter(
    (c: Commitment) => c.status === "open",
  ).length;

  const recentDecisions = (state.decisions || []).slice(-3).length;

  const totalSignals =
    highRiskTitles.length + medRiskCount + openCommitments + recentDecisions;
  if (totalSignals === 0) return null;

  let suggestionKey: Focus["suggestionKey"] = "ask_or_decide";
  if (highRiskTitles.length > 0) suggestionKey = "follow_up_risk";
  else if (recentDecisions > 0) suggestionKey = "ratify_decision";

  return {
    highRiskTitles,
    medRiskCount,
    openCommitments,
    recentDecisions,
    suggestionKey,
  };
}

function dismissKey(streamKey: string): string {
  return `wg:recap:${streamKey}:dismissed`;
}

function isDismissed(streamKey: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(dismissKey(streamKey)) === "1";
  } catch {
    return false;
  }
}

function markDismissed(streamKey: string): void {
  try {
    window.sessionStorage.setItem(dismissKey(streamKey), "1");
  } catch {
    // private mode etc — non-fatal.
  }
}

export function TeamRoomRecap({
  state,
  streamKey,
}: {
  state: ProjectState | null;
  streamKey: string;
}) {
  const t = useTranslations("stream.recap");
  const focus = useMemo(() => deriveFocus(state), [state]);

  // 4-state lifecycle: idle (not yet mounted) → entering (visible,
  // animating in) → live → exiting (animating out) → idle.
  // sessionStorage is only checked on mount; once dismissed in this
  // session the component immediately goes idle and stays idle.
  const [stage, setStage] = useState<
    "idle" | "entering" | "live" | "exiting"
  >("idle");
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduceMotion(mq.matches);
    const onChange = () => setReduceMotion(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);

  useEffect(() => {
    if (!focus) {
      setStage("idle");
      return;
    }
    if (isDismissed(streamKey)) {
      setStage("idle");
      return;
    }
    // Only kick off the entry animation when we're idle. If we're
    // already live or in-flight and the focus payload simply updates
    // (new risk, dismissed decision), we keep the panel where it is —
    // re-running the reveal would feel like a flicker, not a refresh.
    setStage((cur) => (cur === "idle" ? "entering" : cur));
    const flip = setTimeout(() => {
      setStage((cur) => (cur === "entering" ? "live" : cur));
    }, PAINT_GUARD_MS);
    return () => clearTimeout(flip);
  }, [focus, streamKey]);

  if (stage === "idle" || !focus) return null;

  const handleDismiss = () => {
    markDismissed(streamKey);
    setStage("exiting");
    setTimeout(() => setStage("idle"), EXIT_MS);
  };

  const animatingIn = stage === "entering" && !reduceMotion;
  const animatingOut = stage === "exiting" && !reduceMotion;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="team-room-recap"
      style={{
        position: "fixed",
        right: 32,
        bottom: 96,
        maxWidth: 460,
        minWidth: 320,
        padding: "14px 16px 14px 18px",
        background: "rgba(15, 23, 42, 0.78)",
        color: "#e6ecf7",
        borderRadius: 18,
        border: "1px solid rgba(148, 163, 184, 0.18)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        boxShadow: "0 20px 50px rgba(15, 23, 42, 0.32)",
        display: "grid",
        gridTemplateColumns: "1fr auto",
        alignItems: "start",
        gap: 12,
        zIndex: 30,
        transformOrigin: "bottom right",
        opacity: animatingIn ? 0 : animatingOut ? 0 : 1,
        transform: animatingIn
          ? "translateY(8px) scale(0.985)"
          : animatingOut
            ? "translateY(6px) scale(0.985)"
            : "translateY(0) scale(1)",
        transition: animatingOut
          ? `opacity ${EXIT_MS}ms var(--wg-ease-exit), transform ${EXIT_MS}ms var(--wg-ease-exit)`
          : `opacity ${ENTRY_DUR_MS}ms var(--wg-ease-enter) ${ENTRY_DELAY_MS}ms, transform ${ENTRY_DUR_MS}ms var(--wg-ease-enter) ${ENTRY_DELAY_MS}ms, box-shadow 220ms var(--wg-ease-move)`,
        pointerEvents: animatingOut ? "none" : "auto",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "rgba(186, 200, 224, 0.85)",
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 700,
            marginBottom: 6,
          }}
        >
          {t("kicker")}
        </div>
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            lineHeight: 1.45,
            color: "#f8fafc",
          }}
        >
          {t("title")}
        </div>
        <RecapBody focus={focus} />
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            color: "rgba(202, 213, 232, 0.78)",
            lineHeight: 1.55,
          }}
        >
          {t(`suggestion.${focus.suggestionKey}`)}
        </div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={t("dismiss")}
        title={t("dismiss")}
        data-testid="recap-dismiss"
        style={{
          background: "transparent",
          border: "1px solid rgba(148, 163, 184, 0.25)",
          color: "rgba(226, 232, 240, 0.85)",
          width: 24,
          height: 24,
          borderRadius: "50%",
          cursor: "pointer",
          display: "grid",
          placeItems: "center",
          fontSize: 14,
          lineHeight: 1,
          padding: 0,
        }}
      >
        ×
      </button>
    </div>
  );
}

function RecapBody({ focus }: { focus: Focus }) {
  const t = useTranslations("stream.recap");
  const summary: string[] = [];
  if (focus.highRiskTitles.length > 0) {
    summary.push(...focus.highRiskTitles);
  }
  if (focus.medRiskCount > 0) {
    summary.push(t("chips.medRisks", { n: focus.medRiskCount }));
  }
  if (focus.openCommitments > 0) {
    summary.push(t("chips.commitments", { n: focus.openCommitments }));
  }
  if (focus.recentDecisions > 0) {
    summary.push(t("chips.recentDecisions", { n: focus.recentDecisions }));
  }
  if (summary.length === 0) return null;
  return (
    <div
      style={{
        marginTop: 6,
        fontSize: 13,
        color: "rgba(214, 224, 240, 0.94)",
        lineHeight: 1.55,
      }}
    >
      {summary.join(" · ")}
    </div>
  );
}

