"use client";

// TaskRowControls — Phase U inline controls for status self-report
// + leader scoring. Lives inside a TasksPanel row.
//
// Visibility logic (mirrors the backend permission model):
//   * Status dropdown — assignee OR project owner can flip the state.
//     Non-actor sees the static status pill.
//   * Score button — appears only when status === 'done' AND viewer is
//     project owner. Clicking expands a tiny radio group + feedback
//     textarea. Existing scores show inline ("✓ Good — Maya").
//
// On any successful write, calls onChanged() so the parent server-
// component page can router.refresh() the next render.

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  ApiError,
  fetchTaskHistory,
  scoreTask,
  updateTaskStatus,
  type TaskQuality,
  type TaskStatusValue,
} from "@/lib/api";

const ALLOWED_TARGET_STATES: TaskStatusValue[] = [
  "open",
  "in_progress",
  "blocked",
  "done",
  "canceled",
];

const QUALITY_OPTIONS: TaskQuality[] = ["good", "ok", "needs_work"];

function statusBg(status: string): string {
  switch (status) {
    case "done":
      return "var(--wg-ok-soft)";
    case "in_progress":
      return "var(--wg-amber-soft)";
    case "blocked":
      return "var(--wg-accent-soft)";
    case "canceled":
      return "var(--wg-surface-sunk)";
    default:
      return "var(--wg-surface)";
  }
}

export function TaskStatusCell({
  taskId,
  status,
  canEdit,
}: {
  taskId: string;
  status: string;
  canEdit: boolean;
}) {
  const t = useTranslations("taskProgress");
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!canEdit) {
    return <StatusPill status={status} />;
  }

  async function flip(newStatus: TaskStatusValue) {
    if (newStatus === status) return;
    setPending(true);
    setError(null);
    try {
      await updateTaskStatus(taskId, { new_status: newStatus });
      router.refresh();
    } catch (e) {
      const code =
        e instanceof ApiError && e.body && typeof (e.body as { message?: unknown }).message === "string"
          ? (e.body as { message: string }).message
          : "error";
      setError(code);
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <select
        value={status}
        onChange={(e) => void flip(e.target.value as TaskStatusValue)}
        disabled={pending}
        data-testid="task-status-select"
        style={{
          padding: "2px 8px",
          background: statusBg(status),
          color: "var(--wg-ink)",
          border: "1px solid var(--wg-line)",
          borderRadius: 999,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          cursor: pending ? "progress" : "pointer",
        }}
      >
        {ALLOWED_TARGET_STATES.map((s) => (
          <option key={s} value={s}>
            {t(`states.${s}`)}
          </option>
        ))}
      </select>
      {error ? (
        <span
          role="alert"
          style={{
            fontSize: 10,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </span>
      ) : null}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const t = useTranslations("taskProgress");
  return (
    <span
      data-testid="task-status-pill"
      style={{
        padding: "2px 8px",
        borderRadius: 999,
        background: statusBg(status),
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      {t(`states.${status}`, { fallback: status } as never)}
    </span>
  );
}

export function TaskScoreCell({
  taskId,
  status,
  isProjectOwner,
}: {
  taskId: string;
  status: string;
  isProjectOwner: boolean;
}) {
  const t = useTranslations("taskProgress");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [existingQuality, setExistingQuality] = useState<TaskQuality | null>(null);
  const [existingFeedback, setExistingFeedback] = useState<string | null>(null);
  const [quality, setQuality] = useState<TaskQuality>("good");
  const [feedback, setFeedback] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  // Lazy-load the current score on first expand. Cheap (single GET) +
  // means the row doesn't pay the cost when the user never clicks.
  useEffect(() => {
    if (!open || loadedRef.current) return;
    loadedRef.current = true;
    (async () => {
      try {
        const h = await fetchTaskHistory(taskId);
        if (h.score) {
          setExistingQuality(h.score.quality);
          setExistingFeedback(h.score.feedback);
          setQuality(h.score.quality);
          setFeedback(h.score.feedback ?? "");
        }
      } catch {
        /* non-fatal */
      }
    })();
  }, [open, taskId]);

  if (status !== "done" || !isProjectOwner) {
    // Non-owner / not-done rows render nothing for this cell.
    if (status === "done" && existingQuality) {
      return (
        <span
          data-testid="task-score-display"
          style={{
            padding: "2px 8px",
            background: "var(--wg-ok-soft)",
            color: "var(--wg-ok)",
            borderRadius: 999,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 600,
          }}
        >
          ✓ {t(`quality.${existingQuality}`)}
        </span>
      );
    }
    return null;
  }

  async function submit() {
    setPending(true);
    setError(null);
    try {
      await scoreTask(taskId, {
        quality,
        feedback: feedback.trim() || undefined,
      });
      setExistingQuality(quality);
      setExistingFeedback(feedback.trim() || null);
      setOpen(false);
      router.refresh();
    } catch (e) {
      const code =
        e instanceof ApiError && e.body && typeof (e.body as { message?: unknown }).message === "string"
          ? (e.body as { message: string }).message
          : "error";
      setError(code);
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="task-score-toggle"
        style={{
          padding: "2px 8px",
          background: existingQuality
            ? "var(--wg-ok-soft)"
            : "transparent",
          color: existingQuality ? "var(--wg-ok)" : "var(--wg-ink-soft)",
          border: `1px solid ${existingQuality ? "var(--wg-ok)" : "var(--wg-line)"}`,
          borderRadius: 999,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        {existingQuality
          ? `✓ ${t(`quality.${existingQuality}`)}`
          : t("scoreThis")}
      </button>
      {open ? (
        <div
          style={{
            padding: 8,
            background: "var(--wg-surface-raised)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-sm, 4px)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
            minWidth: 200,
          }}
        >
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {QUALITY_OPTIONS.map((q) => (
              <label
                key={q}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  cursor: "pointer",
                }}
              >
                <input
                  type="radio"
                  checked={quality === q}
                  onChange={() => setQuality(q)}
                />
                {t(`quality.${q}`)}
              </label>
            ))}
          </div>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder={t("feedbackPlaceholder")}
            rows={2}
            maxLength={2000}
            style={{
              padding: "4px 6px",
              fontSize: 12,
              fontFamily: "var(--wg-font-body, inherit)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              resize: "vertical",
              background: "var(--wg-surface)",
              color: "var(--wg-ink)",
            }}
          />
          {error ? (
            <div
              role="alert"
              style={{
                fontSize: 11,
                color: "var(--wg-accent)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {error}
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={pending}
              style={{
                padding: "4px 10px",
                background: "var(--wg-accent)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--wg-radius-sm, 4px)",
                fontSize: 11,
                fontWeight: 600,
                cursor: pending ? "progress" : "pointer",
              }}
            >
              {pending
                ? t("saving")
                : existingQuality
                  ? t("update")
                  : t("save")}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              style={{
                padding: "4px 10px",
                background: "transparent",
                color: "var(--wg-ink)",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius-sm, 4px)",
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              {t("cancel")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
