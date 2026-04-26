"use client";

// PromoteTaskButton — Phase T+1: turn a personal-scope draft task
// into a plan-scope task via the membrane review pathway. Mirrors the
// KB note promote button (NotesSection.tsx).
//
// Three response paths from POST /api/tasks/{id}/promote:
//   * task non-null         → auto-merged into the plan; refresh
//   * deferred=true         → membrane queued an inbox review for the
//                             owner. Show a one-line "Sent for review"
//                             toast inline; the personal row sticks
//                             around until the owner accepts in-stream.
//   * 4xx error             → surface the reason inline.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { ApiError, promoteTask } from "@/lib/api";

export function PromoteTaskButton({ taskId }: { taskId: string }) {
  const t = useTranslations("status.tasks");
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{
    kind: "info" | "error";
    text: string;
  } | null>(null);

  async function submit() {
    if (pending) return;
    setPending(true);
    setMessage(null);
    try {
      const r = await promoteTask(taskId);
      if (r.deferred) {
        setMessage({ kind: "info", text: t("promoteDeferred") });
      } else {
        // Auto-merged — task no longer exists as personal; refresh
        // wipes the row from the drafts list.
        router.refresh();
      }
    } catch (e) {
      const detail =
        e instanceof ApiError &&
        e.body &&
        typeof (e.body as { detail?: unknown }).detail === "string"
          ? (e.body as { detail: string }).detail
          : t("promoteFailed");
      setMessage({ kind: "error", text: detail });
    } finally {
      setPending(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <button
        type="button"
        onClick={() => void submit()}
        disabled={pending}
        data-testid="promote-task-button"
        style={{
          padding: "2px 10px",
          background: "transparent",
          color: "var(--wg-accent)",
          border: "1px solid var(--wg-accent)",
          borderRadius: 999,
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          fontWeight: 600,
          cursor: pending ? "progress" : "pointer",
        }}
      >
        {pending ? t("promoting") : t("promote")}
      </button>
      {message ? (
        <span
          role={message.kind === "error" ? "alert" : "status"}
          style={{
            fontSize: 10,
            color:
              message.kind === "error"
                ? "var(--wg-accent)"
                : "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {message.text}
        </span>
      ) : null}
    </div>
  );
}
