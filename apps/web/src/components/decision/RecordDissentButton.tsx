"use client";

// RecordDissentButton — compact toggle + inline composer for a
// decision card on the audit list. Unlike the full DissentList on
// the node detail page, this variant shows only the write surface
// (the lineage view is the home for the read list).

import { useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { ApiError, recordDissent } from "@/lib/api";

const MAX_STANCE_CHARS = 500;

type Props = {
  projectId: string;
  decisionId: string;
};

const linkBtn: CSSProperties = {
  padding: 0,
  background: "transparent",
  color: "var(--wg-accent)",
  border: "none",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
  textDecoration: "none",
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

export function RecordDissentButton({ projectId, decisionId }: Props) {
  const t = useTranslations("dissent");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    const stance = draft.trim();
    if (!stance || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await recordDissent(projectId, decisionId, stance);
      setDone(true);
      setOpen(false);
      setDraft("");
    } catch (e) {
      if (e instanceof ApiError) {
        setErr(t("errorPrefix") + " " + String(e.body ?? e.status));
      } else {
        setErr(t("errorGeneric"));
      }
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <span
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
        }}
      >
        {t("recorded")}
      </span>
    );
  }

  if (!open) {
    return (
      <button type="button" style={linkBtn} onClick={() => setOpen(true)}>
        + {t("recordButton")}
      </button>
    );
  }

  const remaining = MAX_STANCE_CHARS - draft.length;

  return (
    <div
      style={{
        marginTop: 8,
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
              remaining < 50 ? "var(--wg-amber, #c58b00)" : "var(--wg-ink-faint)",
          }}
        >
          {remaining}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            style={ghostBtn}
            onClick={() => {
              setOpen(false);
              setDraft("");
              setErr(null);
            }}
            disabled={busy}
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            style={primaryBtn}
            onClick={submit}
            disabled={busy || draft.trim().length === 0}
          >
            {busy ? t("submitting") : t("submit")}
          </button>
        </div>
      </div>
      {err ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--wg-amber, #c58b00)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {err}
        </div>
      ) : null}
    </div>
  );
}
