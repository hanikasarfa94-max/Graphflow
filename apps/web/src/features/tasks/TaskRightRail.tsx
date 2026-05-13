"use client";

// TaskRightRail — read-only proof page for a single task.
//
// Phase RW-7 (2026-05-13): the mock useTask() that fabricated Ravi /
// invented evidence / synthesized AI Assistance proposals is gone.
// The caller (apps/web/src/app/tasks/[id]/page.tsx) fetches the
// real task via GET /api/tasks/:id and passes it down. The rail
// renders only the fields the BE actually emits today; everything
// else (related work, evidence sources, AI Assistance, primary
// action) is honest empty.
//
// Mutation surfaces (promote, status change) are deliberately
// absent per the RW-7 brief — read-only only.

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Card, EmptyState, Tag, Text } from "@/components/ui";

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

export function TaskRightRail({ task }: { task: TaskRow }) {
  const t = useTranslations("shellV062.tasks.detail");
  const statusLabel = STATUS_LABEL[task.status] || task.status;
  const statusTone = STATUS_TONE[task.status] || "neutral";

  return (
    <aside
      aria-label="Task detail"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        maxWidth: 360,
        width: "100%",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Tag tone={statusTone} size="sm">
          {statusLabel}
        </Tag>
        <Text variant="body" style={{ fontWeight: 600, color: "var(--wg-ink)" }}>
          {task.title}
        </Text>
      </div>

      <Card title={t("metaTitle")}>
        <Meta label={t("meta.id")} value={task.id} />
        {task.scope_id ? (
          <Meta
            label={t("meta.scope")}
            value={
              <Link
                href={`/scopes/${encodeURIComponent(task.scope_id)}`}
                style={{ color: "var(--wg-accent)" }}
              >
                {task.scope_id.slice(0, 8)} →
              </Link>
            }
          />
        ) : (
          <Meta label={t("meta.scope")} value="—" />
        )}
        <Meta label={t("meta.scopeKind")} value={task.scope} />
        <Meta
          label={t("meta.owner")}
          value={
            task.owner_user_id
              ? `user:${task.owner_user_id.slice(0, 8)}`
              : "—"
          }
        />
        <Meta
          label={t("meta.assigneeRole")}
          value={task.assignee_role || "—"}
        />
        <Meta
          label={t("meta.estimate")}
          value={
            task.estimate_hours !== null && task.estimate_hours !== undefined
              ? `${task.estimate_hours}h`
              : "—"
          }
        />
        {task.requirement_id ? (
          <Meta
            label={t("meta.requirement")}
            value={task.requirement_id.slice(0, 8)}
          />
        ) : null}
        <Meta label={t("meta.created")} value={task.created_at || "—"} />
      </Card>

      <Card title={t("descriptionTitle")}>
        {task.description ? (
          <Text as="p" variant="body" style={{ whiteSpace: "pre-wrap" }}>
            {task.description}
          </Text>
        ) : (
          <EmptyState>{t("noDescription")}</EmptyState>
        )}
      </Card>

      <Card title={t("sourceTitle")}>
        {task.source_message_id ? (
          <Text variant="body">
            {t("sourceFromMessage")}{" "}
            <Text variant="mono" as="span">
              {task.source_message_id}
            </Text>
          </Text>
        ) : (
          <EmptyState>{t("noSource")}</EmptyState>
        )}
      </Card>

      <Card variant="sunk">
        <Text variant="caption" muted>
          {t("notWired")}
        </Text>
      </Card>
    </aside>
  );
}

function Meta({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        marginBottom: 6,
        alignItems: "baseline",
      }}
    >
      <Text
        variant="caption"
        muted
        style={{
          minWidth: 110,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </Text>
      <Text variant="body" as="span">
        {value}
      </Text>
    </div>
  );
}
