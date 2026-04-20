"use client";

// CommitModal — Sprint 2a.
//
// Minimal create-commitment UX. Opened from the "+ Commit" button in
// the graph's top strip. Fields:
//   * headline (required, 3..500 chars)
//   * target_date (optional, datetime-local input)
//   * metric (optional, free-form in v1)
//
// On submit: POST /api/projects/{id}/commitments, then call the
// parent's onCreated callback so it can refetch the project state and
// pick the new commitment up in the graph.

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { createCommitment, type Commitment } from "@/lib/api";

interface Props {
  projectId: string;
  onClose: () => void;
  onCreated: (commitment: Commitment) => void;
}

export function CommitModal({ projectId, onClose, onCreated }: Props) {
  const t = useTranslations("graph.commit");
  const [headline, setHeadline] = useState("");
  const [targetDate, setTargetDate] = useState(""); // datetime-local
  const [metric, setMetric] = useState("");
  // sla: "" (none) | "86400" | "259200" | "604800" | "1209600"
  //      (none / 1d / 3d / 7d / 14d)
  const [sla, setSla] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headlineRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    headlineRef.current?.focus();
  }, []);

  const onEsc = useCallback(
    (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && !submitting) onClose();
    },
    [onClose, submitting],
  );
  useEffect(() => {
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onEsc]);

  const canSubmit = headline.trim().length >= 3 && !submitting;

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      // datetime-local produces "YYYY-MM-DDTHH:MM" (local time, no
      // zone). Convert to ISO with Z so the server stores UTC without
      // silently misinterpreting the wall clock as UTC.
      let isoTarget: string | undefined = undefined;
      if (targetDate) {
        const d = new Date(targetDate);
        if (!isNaN(d.valueOf())) isoTarget = d.toISOString();
      }
      const slaSeconds =
        sla && Number.isFinite(parseInt(sla, 10))
          ? parseInt(sla, 10)
          : undefined;
      const { commitment } = await createCommitment(projectId, {
        headline: headline.trim(),
        target_date: isoTarget,
        metric: metric.trim() || undefined,
        sla_window_seconds: slaSeconds,
      });
      onCreated(commitment);
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : t("errorGeneric"),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="commit-modal-title"
      onMouseDown={(ev) => {
        if (ev.target === ev.currentTarget && !submitting) onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(20,16,10,0.42)",
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: "min(440px, calc(100% - 24px))",
          background: "var(--wg-surface-raised, #fff)",
          border: "1px solid var(--wg-line)",
          borderRadius: 8,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
        }}
      >
        <div>
          <h2
            id="commit-modal-title"
            style={{
              margin: 0,
              fontSize: 16,
              fontWeight: 600,
              color: "var(--wg-ink)",
            }}
          >
            {t("title")}
          </h2>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 12,
              color: "var(--wg-ink-soft)",
              lineHeight: 1.45,
            }}
          >
            {t("subtitle")}
          </p>
        </div>

        <label
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {t("headlineLabel")}
          </span>
          <input
            ref={headlineRef}
            value={headline}
            onChange={(ev) => setHeadline(ev.target.value)}
            placeholder={t("headlinePlaceholder")}
            maxLength={500}
            required
            style={{
              padding: "8px 10px",
              fontSize: 14,
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              background: "var(--wg-surface, #fff)",
              fontFamily: "var(--wg-font-sans)",
            }}
          />
        </label>

        <label
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {t("targetDateLabel")}
          </span>
          <input
            type="datetime-local"
            value={targetDate}
            onChange={(ev) => setTargetDate(ev.target.value)}
            style={{
              padding: "8px 10px",
              fontSize: 14,
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              background: "var(--wg-surface, #fff)",
              fontFamily: "var(--wg-font-sans)",
            }}
          />
        </label>

        <label
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {t("slaLabel")}
          </span>
          <select
            value={sla}
            onChange={(ev) => setSla(ev.target.value)}
            style={{
              padding: "8px 10px",
              fontSize: 14,
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              background: "var(--wg-surface, #fff)",
              fontFamily: "var(--wg-font-sans)",
            }}
          >
            <option value="">{t("slaOptionNone")}</option>
            <option value="86400">{t("slaOption1d")}</option>
            <option value="259200">{t("slaOption3d")}</option>
            <option value="604800">{t("slaOption7d")}</option>
            <option value="1209600">{t("slaOption14d")}</option>
          </select>
          <span
            style={{
              fontSize: 11,
              color: "var(--wg-ink-faint)",
            }}
          >
            {t("slaHint")}
          </span>
        </label>

        <label
          style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            {t("metricLabel")}
          </span>
          <input
            value={metric}
            onChange={(ev) => setMetric(ev.target.value)}
            placeholder={t("metricPlaceholder")}
            maxLength={500}
            style={{
              padding: "8px 10px",
              fontSize: 14,
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              background: "var(--wg-surface, #fff)",
              fontFamily: "var(--wg-font-sans)",
            }}
          />
        </label>

        {error && (
          <div
            role="alert"
            style={{
              fontSize: 12,
              color: "var(--wg-accent)",
              background: "rgba(199,68,74,0.06)",
              border: "1px solid var(--wg-accent-ring)",
              borderRadius: 4,
              padding: "6px 10px",
            }}
          >
            {error}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 4,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{
              padding: "8px 14px",
              fontSize: 13,
              background: "transparent",
              color: "var(--wg-ink-soft)",
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            {t("cancel")}
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            style={{
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              background: canSubmit
                ? "var(--wg-accent)"
                : "var(--wg-line)",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              cursor: canSubmit ? "pointer" : "not-allowed",
            }}
          >
            {submitting ? t("submitting") : t("submit")}
          </button>
        </div>
      </form>
    </div>
  );
}
