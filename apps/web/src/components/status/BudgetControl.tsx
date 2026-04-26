"use client";

// Owner-only inline edit for RequirementRow.budget_hours. Drives the
// membrane's task_promote estimate-overflow advisory (services/membrane.py
// _review_task_promote check 3). Empty value clears the budget.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, setRequirementBudget } from "@/lib/api";
import { Button } from "@/components/ui";

export function BudgetControl({
  projectId,
  requirementId,
  initialBudgetHours,
}: {
  projectId: string;
  requirementId: string;
  initialBudgetHours: number | null;
}) {
  const t = useTranslations("status.budget");
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(
    initialBudgetHours == null ? "" : String(initialBudgetHours),
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<number | null>(initialBudgetHours);

  async function save() {
    if (pending) return;
    const trimmed = draft.trim();
    let value: number | null = null;
    if (trimmed) {
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed) || parsed < 1 || parsed > 100000) {
        setError(t("invalid"));
        return;
      }
      value = Math.floor(parsed);
    }
    setPending(true);
    setError(null);
    try {
      const r = await setRequirementBudget(projectId, requirementId, value);
      setCurrent(r.budget_hours);
      setEditing(false);
      router.refresh();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${t("saveFailed")} (${e.status})`
          : t("saveFailed"),
      );
    } finally {
      setPending(false);
    }
  }

  if (!editing) {
    return (
      <div
        data-testid="budget-control"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          background: "var(--wg-surface-sunk)",
          borderRadius: "var(--wg-radius-sm, 4px)",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        <span>{t("label")}:</span>
        <span style={{ fontWeight: 600, color: "var(--wg-ink)" }}>
          {current == null ? t("unset") : `${current}h`}
        </span>
        <Button
          variant="link"
          size="sm"
          onClick={() => setEditing(true)}
          data-testid="budget-edit"
        >
          {t("edit")}
        </Button>
      </div>
    );
  }

  return (
    <div
      data-testid="budget-editor"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius-sm, 4px)",
        fontSize: 12,
        fontFamily: "var(--wg-font-mono)",
      }}
    >
      <span style={{ color: "var(--wg-ink-soft)" }}>{t("label")}:</span>
      <input
        type="number"
        min={1}
        max={100000}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
        placeholder={t("placeholder")}
        data-testid="budget-input"
        style={{
          padding: "2px 6px",
          width: 80,
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-sm, 4px)",
          background: "var(--wg-surface)",
          color: "var(--wg-ink)",
        }}
      />
      <Button
        variant="primary"
        size="sm"
        onClick={() => void save()}
        disabled={pending}
        data-testid="budget-save"
      >
        {pending ? t("saving") : t("save")}
      </Button>
      <Button
        variant="link"
        size="sm"
        onClick={() => {
          setEditing(false);
          setDraft(current == null ? "" : String(current));
          setError(null);
        }}
        disabled={pending}
      >
        {t("cancel")}
      </Button>
      {error ? (
        <span
          role="alert"
          style={{
            fontSize: 11,
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </span>
      ) : null}
    </div>
  );
}
