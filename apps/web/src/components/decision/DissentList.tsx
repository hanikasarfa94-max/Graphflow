"use client";

// DissentList — Phase 2.A render surface for a decision's dissents.
//
// Two halves: the list of prior dissents (one row per dissenter, with a
// validation chip) and the composer (toggled Record-dissent button
// reveals an inline textarea + Submit). The composer posts to the dissent
// endpoint and optimistically appends the new row to the list without
// a round-trip to state/. If the POST fails the row is removed + an
// inline error shows.
//
// Visual idiom matches decision-card rows: mono eyebrow labels, subtle
// surface-raised background, an amber/green/gray validation chip sized
// like a status pill.

import { useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import {
  ApiError,
  recordDissent,
  type DissentRecord,
  type DissentValidatedOutcome,
} from "@/lib/api";
import { formatIso } from "@/lib/time";

const MAX_STANCE_CHARS = 500;

type Props = {
  projectId: string;
  decisionId: string;
  initial: DissentRecord[];
  // Whether the logged-in viewer is a project member. Gates the
  // composer — observers still read the list but can't record.
  canRecord: boolean;
};

const eyebrow: CSSProperties = {
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  color: "var(--wg-ink-faint)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  margin: "0 0 10px",
};

const row: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  padding: "10px 12px",
  background: "var(--wg-surface-raised)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};

export function DissentList({
  projectId,
  decisionId,
  initial,
  canRecord,
}: Props) {
  const t = useTranslations("dissent");
  const [items, setItems] = useState<DissentRecord[]>(initial);
  const [composerOpen, setComposerOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const remaining = MAX_STANCE_CHARS - draft.length;

  async function submit() {
    const stance = draft.trim();
    if (!stance || busy) return;
    setBusy(true);
    setErr(null);
    // Optimistic placeholder — real id arrives in the response and
    // replaces this row.
    const tempId = `__pending_${Date.now()}`;
    const optimistic: DissentRecord = {
      id: tempId,
      decision_id: decisionId,
      dissenter_user_id: "me",
      dissenter_display_name: t("youLabel"),
      stance_text: stance,
      created_at: new Date().toISOString(),
      validated_by_outcome: null,
      outcome_evidence_ids: [],
    };
    setItems((prev) => [...prev, optimistic]);
    try {
      const { dissent } = await recordDissent(projectId, decisionId, stance);
      setItems((prev) =>
        prev.map((d) => (d.id === tempId ? dissent : d)).filter(
          // Dedup in case the server replaces an earlier stance from
          // the same viewer — the upsert path returns the existing id.
          (d, i, arr) => arr.findIndex((x) => x.id === d.id) === i,
        ),
      );
      setDraft("");
      setComposerOpen(false);
    } catch (e) {
      setItems((prev) => prev.filter((d) => d.id !== tempId));
      if (e instanceof ApiError) {
        setErr(t("errorPrefix") + " " + String(e.body ?? e.status));
      } else {
        setErr(t("errorGeneric"));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ marginTop: 28 }}>
      <h3 style={eyebrow}>{t("sectionTitle")}</h3>

      {items.length === 0 ? (
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink-faint)",
            padding: "8px 12px",
            fontStyle: "italic",
          }}
        >
          {t("empty")}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((d) => (
            <DissentRow key={d.id} dissent={d} />
          ))}
        </div>
      )}

      {canRecord && !composerOpen ? (
        <Button
          variant="ghost"
          onClick={() => {
            setComposerOpen(true);
            setErr(null);
          }}
          style={{ marginTop: 12 }}
        >
          + {t("recordButton")}
        </Button>
      ) : null}

      {canRecord && composerOpen ? (
        <div
          style={{
            marginTop: 12,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, MAX_STANCE_CHARS))}
            rows={3}
            maxLength={MAX_STANCE_CHARS}
            placeholder={t("composerPlaceholder")}
            disabled={busy}
            style={{
              width: "100%",
              padding: "8px 10px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              background: "var(--wg-surface)",
              color: "var(--wg-ink)",
              fontSize: 13,
              fontFamily: "var(--wg-font-sans)",
              resize: "vertical",
              boxSizing: "border-box",
            }}
          />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 10,
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontFamily: "var(--wg-font-mono)",
                color:
                  remaining < 50 ? "var(--wg-amber)" : "var(--wg-ink-faint)",
              }}
            >
              {remaining}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <Button
                variant="ghost"
                onClick={() => {
                  setComposerOpen(false);
                  setDraft("");
                  setErr(null);
                }}
                disabled={busy}
              >
                {t("cancel")}
              </Button>
              <Button
                variant="primary"
                onClick={submit}
                disabled={busy || draft.trim().length === 0}
              >
                {busy ? t("submitting") : t("submit")}
              </Button>
            </div>
          </div>
          {err ? (
            <div
              style={{
                fontSize: 12,
                color: "var(--wg-amber)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {err}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function DissentRow({ dissent }: { dissent: DissentRecord }) {
  const t = useTranslations("dissent");
  return (
    <div style={row}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
        }}
      >
        <div
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink)",
            fontWeight: 500,
          }}
        >
          {dissent.dissenter_display_name || dissent.dissenter_user_id.slice(0, 8)}
        </div>
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}
        >
          <ValidationChip outcome={dissent.validated_by_outcome} t={t} />
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
            }}
          >
            {formatWhen(dissent.created_at)}
          </span>
        </div>
      </div>
      <div
        style={{
          fontSize: 13,
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          lineHeight: 1.55,
        }}
      >
        {dissent.stance_text}
      </div>
    </div>
  );
}

function ValidationChip({
  outcome,
  t,
}: {
  outcome: DissentValidatedOutcome;
  t: (k: string) => string;
}) {
  if (outcome === null) return null;
  const [bg, fg, label] = chipStyle(outcome, t);
  return (
    <span
      style={{
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        padding: "2px 7px",
        borderRadius: 10,
        background: bg,
        color: fg,
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function chipStyle(
  outcome: Exclude<DissentValidatedOutcome, null>,
  t: (k: string) => string,
): [string, string, string] {
  // House signal-color rule (2026-04-21 pass):
  //   supported → sage (--wg-ok), refuted → amber, still_open → neutral.
  // Previously used undefined `--wg-green*` tokens with ad-hoc hex
  // fallbacks; now maps onto the real palette.
  switch (outcome) {
    case "supported":
      return [
        "var(--wg-ok-soft)",
        "var(--wg-ok)",
        t("chip.supported"),
      ];
    case "refuted":
      return [
        "var(--wg-amber-soft)",
        "var(--wg-amber)",
        t("chip.refuted"),
      ];
    case "still_open":
    default:
      return [
        "var(--wg-line-soft)",
        "var(--wg-ink-faint)",
        t("chip.stillOpen"),
      ];
  }
}

function formatWhen(iso: string): string {
  try {
    return formatIso(iso);
  } catch {
    return iso;
  }
}
