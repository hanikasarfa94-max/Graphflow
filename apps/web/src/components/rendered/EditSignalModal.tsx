"use client";

// Modal that interrupts a Save on a rendered-doc edit when the client
// heuristic classifies the change as anything other than a silent
// prose polish. See docs/north-star.md §"Direct edits are signals,
// not silent state-mutations": the prompt IS the feature. If we let
// semantic / structural / new-content edits through silently, the
// graph stops being a trusted source of truth.
//
// Three actions per kind; each action becomes a `signalAction` event.
// v1 wiring is a console.log — v2 wires to the edit-signal backend
// (TODO below the action handler). The save itself proceeds in all
// action cases except `cancel`; the classification + chosen action
// are captured as metadata.

import { useTranslations } from "next-intl";
import { useEffect } from "react";

import type { EditKind, EditSignal } from "@/lib/editSignal";

// Action keys per kind. The modal renders one button per entry, pulling
// label text from `render.editSignal.kinds.<kind>.actions.<key>`.
// Deliberately kept to 2-3 actions per kind — more than that turns the
// ceremony into a form.
export type EditSignalAction =
  // prose_polish (only shown on low-confidence polish; high-confidence
  // skips the modal entirely)
  | "save_as_polish"
  // semantic_reversal
  | "crystallize_superseding"
  | "discard"
  // new_content
  | "record_decision"
  | "record_risk"
  | "keep_as_prose"
  // structural_change
  | "cascade_downstream"
  | "this_line_only"
  // shared — always available
  | "cancel";

export type EditSignalResult = {
  action: EditSignalAction;
  signal: EditSignal;
};

export function EditSignalModal({
  open,
  signal,
  before,
  after,
  onResolve,
}: {
  open: boolean;
  signal: EditSignal | null;
  before: string;
  after: string;
  // Called with `null` on cancel (so the caller knows not to save).
  // Called with {action, signal} otherwise; caller is responsible for
  // actually saving and for forwarding the event to the backend once
  // v2 ships.
  onResolve: (result: EditSignalResult | null) => void;
}) {
  const t = useTranslations();

  // Esc-to-cancel + focus trap-lite. We don't pull in a full trap dep;
  // instead we autofocus the first action button, which is what the
  // keyboard user wants in 95% of cases (confirm-the-default).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onResolve(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onResolve]);

  if (!open || !signal) return null;

  const kind = signal.kind;
  const actions = ACTION_KEYS[kind];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-signal-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onResolve(null);
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20, 16, 10, 0.42)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        zIndex: 1000,
      }}
    >
      <div
        style={{
          width: "min(560px, 100%)",
          background: "var(--wg-paper, #fff)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius, 4px)",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          boxShadow: "0 10px 40px rgba(0,0,0,0.12)",
          color: "var(--wg-ink)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <h2
            id="edit-signal-title"
            style={{
              fontSize: 18,
              fontWeight: 600,
              margin: 0,
              letterSpacing: "-0.01em",
            }}
          >
            {t("render.editSignal.title")}
          </h2>
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {t(`render.editSignal.kinds.${kind}.label`)} ·{" "}
            {Math.round(signal.confidence * 100)}%
          </span>
        </div>

        <p
          style={{
            margin: 0,
            fontSize: 14,
            lineHeight: 1.55,
            color: "var(--wg-ink)",
          }}
        >
          {t(`render.editSignal.kinds.${kind}.prompt`)}
        </p>

        <DiffPreview before={before} after={after} />

        {signal.matchedSignals.length > 0 ? (
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {t("render.editSignal.signals")}:{" "}
            {signal.matchedSignals.slice(0, 5).join(" · ")}
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            flexWrap: "wrap",
            marginTop: 4,
          }}
        >
          <button
            type="button"
            onClick={() => onResolve(null)}
            style={secondaryButton}
          >
            {t("render.editSignal.cancel")}
          </button>
          {actions.map((action, idx) => (
            <button
              key={action}
              type="button"
              // The final action is the "recommended" path — render as
              // the accent-filled button. The rest are secondary.
              // (The recommended action per kind is curated in
              // ACTION_KEYS below.)
              autoFocus={idx === actions.length - 1}
              onClick={() => onResolve({ action, signal })}
              style={idx === actions.length - 1 ? primaryButton : secondaryButton}
            >
              {t(`render.editSignal.kinds.${kind}.actions.${action}`)}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// A tiny before/after preview. We show the last ~240 chars of each so
// the user sees the affected region without the full section spilling
// the dialog. A real diff view is v2 work — this is "enough to confirm
// what you just typed."
function DiffPreview({ before, after }: { before: string; after: string }) {
  const snippet = (s: string) =>
    s.length > 240 ? "…" + s.slice(s.length - 240) : s;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        maxHeight: 180,
        overflow: "auto",
        border: "1px solid var(--wg-line-soft, #e6ebf1)",
        borderRadius: 4,
        padding: 10,
        background: "var(--wg-surface, #f8fafc)",
        fontFamily: "var(--wg-font-mono, ui-monospace, monospace)",
        fontSize: 12,
        lineHeight: 1.45,
      }}
    >
      <div style={{ color: "var(--wg-ink-soft)", opacity: 0.8 }}>
        − {snippet(before) || "(empty)"}
      </div>
      <div style={{ color: "var(--wg-ink)" }}>
        + {snippet(after) || "(empty)"}
      </div>
    </div>
  );
}

// Per-kind ordered action list. Last entry is the recommended path and
// is highlighted in the UI; see button rendering above. Order matters.
const ACTION_KEYS: Record<EditKind, EditSignalAction[]> = {
  prose_polish: ["save_as_polish"],
  semantic_reversal: ["discard", "crystallize_superseding"],
  new_content: ["keep_as_prose", "record_risk", "record_decision"],
  structural_change: ["this_line_only", "cascade_downstream"],
};

const primaryButton: React.CSSProperties = {
  padding: "8px 16px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius, 4px)",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

const secondaryButton: React.CSSProperties = {
  padding: "8px 14px",
  background: "transparent",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius, 4px)",
  fontSize: 13,
  cursor: "pointer",
  color: "var(--wg-ink)",
};
