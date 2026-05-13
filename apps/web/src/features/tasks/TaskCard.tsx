"use client";

// TaskCard — one row in the global Tasks index.
//
// Phase RW-7 (2026-05-13): renders only the truthful fields the BE
// emits today (title, status, assignee_role, scope_id). The Phase D
// scaffold rendered a fabricated RecognitionPolicyBadge + an invented
// assignee_display_name + a synthesized scope_label — all gone. The
// drawer-on-click handler is also gone; plain navigation to
// /tasks/[id].

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Tag, Text } from "@/components/ui";

import type { TaskRow, TaskStatus } from "./types";

const STATUS_LABEL: Partial<Record<TaskStatus, string>> = {
  personal_draft: "Personal draft",
  candidate: "Candidate",
  confirmation_pending: "Confirmation pending",
  accepted_personal: "Accepted (personal)",
  team_confirmed: "Team confirmed",
  in_progress: "In progress",
  blocked: "Blocked",
  waiting_for_feedback: "Waiting on feedback",
  ready_for_review: "Ready for review",
  done: "Done",
  archived: "Archived",
  pending: "Pending",
};

const STATUS_TONE: Partial<
  Record<TaskStatus, "neutral" | "accent" | "amber" | "ok" | "danger">
> = {
  personal_draft: "neutral",
  candidate: "accent",
  confirmation_pending: "accent",
  accepted_personal: "neutral",
  team_confirmed: "ok",
  in_progress: "accent",
  blocked: "danger",
  waiting_for_feedback: "amber",
  ready_for_review: "amber",
  done: "ok",
  archived: "neutral",
  pending: "neutral",
};

export function TaskCard({ task }: { task: TaskRow }) {
  const t = useTranslations("shellV062.tasks.card");
  const statusLabel = STATUS_LABEL[task.status] || task.status;
  const statusTone = STATUS_TONE[task.status] || "neutral";

  return (
    <Link
      href={`/tasks/${encodeURIComponent(task.id)}`}
      style={{
        display: "block",
        padding: "14px 16px",
        borderBottom: "1px solid var(--wg-line-soft)",
        textDecoration: "none",
        color: "inherit",
        transition: "background var(--wg-dur-short) var(--wg-ease-enter)",
      }}
      aria-label={`Task: ${task.title}`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Text
          variant="body"
          style={{
            fontWeight: 600,
            color: "var(--wg-ink)",
            minWidth: 0,
          }}
        >
          {task.title}
        </Text>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <Tag tone={statusTone} size="sm">
            {statusLabel}
          </Tag>

          {task.assignee_role && task.assignee_role !== "unknown" ? (
            <Text variant="caption" muted>
              {t("roleLabel")}: {task.assignee_role}
            </Text>
          ) : null}

          {task.scope_id ? (
            <>
              <span aria-hidden style={{ color: "var(--wg-line)" }}>
                ·
              </span>
              <Tag tone="neutral" size="sm">
                {task.scope_id.slice(0, 8)}
              </Tag>
            </>
          ) : null}
        </div>
      </div>
    </Link>
  );
}
