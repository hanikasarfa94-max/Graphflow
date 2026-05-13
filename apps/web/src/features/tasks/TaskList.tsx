"use client";

// TaskList — task rows grouped by status, rendered as TaskCards.
//
// Phase RW-7 (2026-05-13): live data. MOCK_TASKS + useTasks() are
// gone. The shell page fetches GET /api/tasks and passes rows down.
// Unknown status strings fall into an "Other" bucket so we never
// drop a row the BE emitted.

import { useTranslations } from "next-intl";

import { Card, EmptyState, Text } from "@/components/ui";

import { TaskCard } from "./TaskCard";
import type { TaskRow, TaskStatus } from "./types";

const STATUS_GROUP_ORDER: TaskStatus[] = [
  "confirmation_pending",
  "ready_for_review",
  "blocked",
  "waiting_for_feedback",
  "in_progress",
  "pending",
  "candidate",
  "team_confirmed",
  "accepted_personal",
  "personal_draft",
  "done",
  "archived",
];

const STATUS_GROUP_LABEL: Partial<Record<TaskStatus, string>> = {
  confirmation_pending: "Confirmation pending",
  ready_for_review: "Ready for review",
  blocked: "Blocked",
  waiting_for_feedback: "Waiting on feedback",
  in_progress: "In progress",
  pending: "Pending",
  candidate: "Candidates",
  team_confirmed: "Team confirmed",
  accepted_personal: "Accepted (personal)",
  personal_draft: "Personal drafts",
  done: "Done",
  archived: "Archived",
};

export function TaskList({ tasks }: { tasks: TaskRow[] }) {
  const t = useTranslations("shellV062.tasks.list");

  if (tasks.length === 0) {
    return (
      <Card title={t("emptyTitle")} flush>
        <div style={{ padding: 16 }}>
          <EmptyState>{t("empty")}</EmptyState>
        </div>
      </Card>
    );
  }

  const buckets = new Map<string, TaskRow[]>();
  for (const task of tasks) {
    const key = STATUS_GROUP_LABEL[task.status] ? task.status : "_other";
    const bucket = buckets.get(key) ?? [];
    bucket.push(task);
    buckets.set(key, bucket);
  }

  const known = STATUS_GROUP_ORDER.filter((s) => buckets.has(s));
  const otherRows = buckets.get("_other") ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {known.map((status) => {
        const rows = buckets.get(status) ?? [];
        return (
          <Card
            key={status}
            title={
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                {STATUS_GROUP_LABEL[status]}
                <Text variant="caption" muted>
                  {rows.length}
                </Text>
              </span>
            }
            flush
          >
            <div role="list">
              {rows.map((row) => (
                <div role="listitem" key={row.id}>
                  <TaskCard task={row} />
                </div>
              ))}
            </div>
          </Card>
        );
      })}

      {otherRows.length > 0 ? (
        <Card
          title={
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              {t("otherGroup")}
              <Text variant="caption" muted>
                {otherRows.length}
              </Text>
            </span>
          }
          flush
        >
          <div role="list">
            {otherRows.map((row) => (
              <div role="listitem" key={row.id}>
                <TaskCard task={row} />
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
