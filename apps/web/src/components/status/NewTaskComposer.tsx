"use client";

// NewTaskComposer — Phase T inline manual task creation.
//
// Mirrors the KB pattern: any project member can self-create a
// personal-scope task. The task lives in their fork (not the canonical
// group plan) until promoted via the membrane review pathway. The
// composer creates personal tasks only; promote-to-plan is a separate
// row affordance (TaskRowControls or a dedicated drafts surface).

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, api } from "@/lib/api";
import { Button } from "@/components/ui";

// Mirrors apps/api/.../routers/task_progress.py CreatePersonalTaskRequest:
// assignee_role enum lives there as a free-string column with a small
// canonical set of values. Keeping this in sync by hand because the
// FE doesn't generate types from the backend yet.
const ASSIGNEE_ROLE_OPTIONS = [
  "unknown",
  "pm",
  "frontend",
  "backend",
  "qa",
  "design",
  "business",
  "approver",
] as const;

export function NewTaskComposer({ projectId }: { projectId: string }) {
  const t = useTranslations("status.tasks");
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  // Optional fields — the membrane's task_promote review uses them
  // when present. Empty/zero passes through as null on the wire.
  const [estimateHours, setEstimateHours] = useState("");
  const [assigneeRole, setAssigneeRole] = useState<string>("unknown");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const trimmed = title.trim();
    if (!trimmed || posting) return;
    setPosting(true);
    setError(null);
    const parsedEstimate = estimateHours.trim()
      ? Number(estimateHours)
      : null;
    try {
      await api(`/api/projects/${projectId}/tasks`, {
        method: "POST",
        body: {
          title: trimmed,
          description: description.trim(),
          ...(parsedEstimate && parsedEstimate > 0
            ? { estimate_hours: parsedEstimate }
            : {}),
          ...(assigneeRole && assigneeRole !== "unknown"
            ? { assignee_role: assigneeRole }
            : {}),
        },
      });
      setTitle("");
      setDescription("");
      setEstimateHours("");
      setAssigneeRole("unknown");
      setOpen(false);
      router.refresh();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${t("createFailed")} (${e.status})`
          : t("createFailed"),
      );
    } finally {
      setPosting(false);
    }
  }

  if (!open) {
    return (
      <div
        style={{
          padding: "8px 0 12px",
          display: "flex",
          justifyContent: "flex-end",
        }}
      >
        <Button
          variant="link"
          size="sm"
          onClick={() => setOpen(true)}
          data-testid="new-task-trigger"
        >
          + {t("newTask")}
        </Button>
      </div>
    );
  }

  return (
    <div
      data-testid="new-task-composer"
      style={{
        margin: "0 0 12px",
        padding: 12,
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-faint)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {t("newTaskHint")}
      </div>
      <input
        type="text"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
          setError(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void submit();
          }
        }}
        placeholder={t("newTaskTitlePlaceholder")}
        maxLength={500}
        autoFocus
        data-testid="new-task-title"
        style={{
          padding: "6px 10px",
          fontSize: 14,
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-sm, 4px)",
          background: "var(--wg-surface)",
          color: "var(--wg-ink)",
        }}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder={t("newTaskDescriptionPlaceholder")}
        maxLength={4000}
        rows={2}
        data-testid="new-task-description"
        style={{
          padding: "6px 10px",
          fontSize: 13,
          fontFamily: "var(--wg-font-sans, inherit)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-sm, 4px)",
          background: "var(--wg-surface)",
          color: "var(--wg-ink)",
          resize: "vertical",
        }}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <label
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            flex: 1,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          {t("newTaskEstimateLabel")}
          <input
            type="number"
            min={1}
            max={10000}
            value={estimateHours}
            onChange={(e) => setEstimateHours(e.target.value)}
            placeholder={t("newTaskEstimatePlaceholder")}
            data-testid="new-task-estimate"
            style={{
              padding: "4px 8px",
              fontSize: 13,
              fontFamily: "var(--wg-font-mono)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              background: "var(--wg-surface)",
              color: "var(--wg-ink)",
            }}
          />
        </label>
        <label
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            flex: 1,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          {t("newTaskRoleLabel")}
          <select
            value={assigneeRole}
            onChange={(e) => setAssigneeRole(e.target.value)}
            data-testid="new-task-role"
            style={{
              padding: "4px 8px",
              fontSize: 13,
              fontFamily: "var(--wg-font-mono)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              background: "var(--wg-surface)",
              color: "var(--wg-ink)",
            }}
          >
            {ASSIGNEE_ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? (
        <div
          role="alert"
          style={{
            fontSize: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <Button
          variant="link"
          size="sm"
          onClick={() => {
            setOpen(false);
            setTitle("");
            setDescription("");
            setError(null);
          }}
          disabled={posting}
        >
          {t("newTaskCancel")}
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={() => void submit()}
          disabled={!title.trim() || posting}
          data-testid="new-task-submit"
        >
          {posting ? t("newTaskSaving") : t("newTaskSave")}
        </Button>
      </div>
    </div>
  );
}
