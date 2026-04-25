import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";

import { ageSecondsFrom, formatAge } from "./age";
import { NewTaskComposer } from "./NewTaskComposer";
import { EmptyState, Panel } from "./Panel";
import { TaskScoreCell, TaskStatusCell } from "./TaskRowControls";

type Task = ProjectState["plan"]["tasks"][number];
type Member = ProjectState["members"][number];
type Assignment = {
  task_id?: string;
  user_id?: string;
  active?: boolean;
  created_at?: string;
};

// Terminal statuses — anything not in this set counts as "active".
// Matches what PlanRepository / UI use elsewhere. Phase U expanded
// the human-driven taxonomy: backend writes "canceled" (US spelling)
// from TaskProgressService; we tolerate both spellings here so old
// rows + new rows both filter out of the active list.
const TERMINAL_STATUSES = new Set(["done", "cancelled", "canceled", "archived"]);

// House signal-color rule (2026-04-21 unification pass): task status
// pills ride the same sage / amber / terracotta triad as risks and
// drift — was previously three custom pastel hexes (#dcf1dc / #fff3d9
// / #fdecec) that didn't line up with anything else.
function statusColor(status: string): string {
  switch (status) {
    case "done":
      return "var(--wg-ok-soft)";
    case "in_progress":
      return "var(--wg-amber-soft)";
    case "blocked":
      return "var(--wg-accent-soft)";
    default:
      return "var(--wg-surface)";
  }
}

export async function TasksPanel({
  tasks,
  assignments,
  members,
  currentUserId,
  isProjectOwner,
  projectId,
}: {
  tasks: Task[];
  assignments: Record<string, unknown>[];
  members: Member[];
  // Phase U row controls — assignee sees a status dropdown, project
  // owner sees both dropdown + score button. Optional so older callers
  // (panels without auth context) still render the static pill.
  currentUserId?: string;
  isProjectOwner?: boolean;
  // Phase T — projectId enables the "+ New task" composer at the
  // panel head. When omitted, the panel stays read-only (legacy).
  projectId?: string;
}) {
  const t = await getTranslations();
  const now = new Date();

  const memberById = new Map(members.map((m) => [m.user_id, m]));
  const assignmentByTask = new Map<string, Assignment>();
  for (const raw of assignments ?? []) {
    const a = raw as Assignment;
    if (a?.task_id && a?.active !== false) {
      assignmentByTask.set(a.task_id, a);
    }
  }

  // Phase U — include `done` tasks too so project owners can score
  // them inline. We still hide explicitly canceled / archived tasks.
  // Active-only filter would have made the score button unreachable.
  const HIDDEN_STATUSES = new Set(["cancelled", "canceled", "archived"]);
  const active = tasks
    .filter((task) => !HIDDEN_STATUSES.has(task.status))
    .map((task) => {
      const assignment = assignmentByTask.get(task.id);
      const owner = assignment?.user_id
        ? memberById.get(assignment.user_id)
        : undefined;
      const ownerLabel = owner
        ? owner.display_name || owner.username
        : task.assignee_role && task.assignee_role !== "unknown"
          ? `${t("status.members.roleLabel")}: ${task.assignee_role}`
          : t("status.tasks.unassigned");
      // TaskRow doesn't expose created_at in /state today — fall back to
      // the assignment's created_at as a pragmatic age signal.
      const ageSeconds = ageSecondsFrom(assignment?.created_at, now);
      return { task, ownerLabel, ageSeconds };
    })
    .sort((a, b) => {
      // Oldest in-flight first. null ages sort last so unknown ages don't
      // dominate the top of the table.
      const aSec = a.ageSeconds ?? -1;
      const bSec = b.ageSeconds ?? -1;
      return bSec - aSec;
    });

  return (
    <Panel
      title={t("status.tasks.title")}
      subtitle={active.length > 0 ? String(active.length) : undefined}
    >
      {projectId && currentUserId ? (
        <NewTaskComposer projectId={projectId} />
      ) : null}
      {active.length === 0 ? (
        <EmptyState>{t("status.tasks.empty")}</EmptyState>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid var(--wg-line)",
                  textAlign: "left",
                }}
              >
                <Th>{t("status.tasks.columnTitle")}</Th>
                <Th>{t("status.tasks.columnOwner")}</Th>
                <Th>{t("status.tasks.columnStatus")}</Th>
                <Th style={{ textAlign: "right" }}>
                  {t("status.tasks.columnAge")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {active.map(({ task, ownerLabel, ageSeconds }) => {
                const assignment = assignmentByTask.get(task.id);
                const isAssignee = Boolean(
                  currentUserId && assignment?.user_id === currentUserId,
                );
                const canEditStatus = Boolean(
                  isAssignee || isProjectOwner,
                );
                return (
                  <tr
                    key={task.id}
                    style={{ borderBottom: "1px solid var(--wg-line)" }}
                  >
                    <Td>
                      <div style={{ fontWeight: 600 }}>{task.title}</div>
                    </Td>
                    <Td style={{ color: "var(--wg-ink-soft)" }}>
                      {ownerLabel}
                    </Td>
                    <Td>
                      <div
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: 4,
                          alignItems: "flex-start",
                        }}
                      >
                        <TaskStatusCell
                          taskId={task.id}
                          status={task.status}
                          canEdit={canEditStatus}
                        />
                        <TaskScoreCell
                          taskId={task.id}
                          status={task.status}
                          isProjectOwner={Boolean(isProjectOwner)}
                        />
                      </div>
                    </Td>
                    <Td
                      style={{
                        textAlign: "right",
                        fontFamily: "var(--wg-font-mono)",
                        color: "var(--wg-ink-soft)",
                        fontSize: 12,
                      }}
                    >
                      {formatAge(ageSeconds, t)}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function Th({
  children,
  style,
}: {
  children?: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <th
      style={{
        padding: "8px 10px",
        fontSize: 11,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        color: "var(--wg-ink-soft)",
        fontWeight: 600,
        ...style,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <td style={{ padding: "8px 10px", verticalAlign: "top", ...style }}>
      {children}
    </td>
  );
}
