"use client";

// TaskCard — one row in the global Tasks index.
//
// Phase D scaffold (2026-05-13). Renders the task summary line:
// title + RecognitionPolicyBadge + assignee + status pill + scope chip.
// Click opens the task detail in the shared DrawerHost (preview) or
// navigates to /tasks/[id] for a full page.
//
// URL invariant — Phase A.4 cut over to the 5-surface shell. Task
// links MUST resolve to `/tasks/[id]` and NEVER /projects/.../tasks/...
// (FRONTEND_IMPLEMENTATION.md §Routes).

// TODO(i18n): externalize status / aria labels.

import Link from "next/link";

import { Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import { RecognitionPolicyBadge } from "./RecognitionPolicyBadge";
import type { TaskRow, TaskStatus } from "./types";

// Status display labels. The grouping order lives in TaskList.tsx.
const STATUS_LABEL: Record<TaskStatus, string> = {
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
};

const STATUS_TONE: Record<
  TaskStatus,
  "neutral" | "accent" | "amber" | "ok" | "danger"
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
};

export function TaskCard({ task }: { task: TaskRow }) {
  const drawer = useDrawer();

  function handleClick(e: React.MouseEvent<HTMLAnchorElement>) {
    // Modifier-click / middle-click falls through to the deep-link
    // route so users can open a task in a new tab as expected. A
    // plain left-click opens the preview drawer for the inline flow.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    drawer.open({
      type: "edit_request", // placeholder drawer slot; D.2 adds 'task_detail' to DrawerType.
      props: { task_id: task.id },
      title: task.title,
    });
  }

  return (
    <Link
      href={`/tasks/${task.id}`}
      onClick={handleClick}
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
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {/* Row 1 — title + badge cluster */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <Text
            variant="body"
            style={{
              fontWeight: 600,
              color: "var(--wg-ink)",
              flex: 1,
              minWidth: 0,
            }}
          >
            {task.title}
          </Text>
          <RecognitionPolicyBadge policy={task.recognition_policy} />
        </div>

        {/* Row 2 — assignee / status / scope chips */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <Tag tone={STATUS_TONE[task.status]} size="sm">
            {STATUS_LABEL[task.status]}
          </Tag>
          <Text variant="caption" muted>
            {/* TODO(i18n): "Assigned to" prefix. */}
            Assigned to {task.assignee_display_name}
          </Text>
          <span aria-hidden style={{ color: "var(--wg-line)" }}>
            ·
          </span>
          {/* Scope chip — links to the scope's home surface. Per Phase
              A.4 there is no /projects/<id> page; the scope label is
              informational only. */}
          <Tag tone="neutral" size="sm">
            {task.scope_label}
          </Tag>
        </div>
      </div>
    </Link>
  );
}
