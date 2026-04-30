// /projects/[id]/detail/tasks — Feishu/Lark-style multidimensional sheet.
//
// Rational audit view for the plan: every task row shows all the
// dimensions a lead actually needs (status, owner, milestone,
// deliverable, effort, dependencies) in a dense, sortable table with
// status chips + severity colors inline.

import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

const STATUS_COLOR: Record<string, { bg: string; fg: string }> = {
  todo: { bg: "#f0eee6", fg: "#5a5a5a" },
  in_progress: { bg: "#fdf4ec", fg: "#2563eb" },
  blocked: { bg: "#fee2e2", fg: "#991b1b" },
  done: { bg: "#e6efe0", fg: "#2f6a37" },
  closed: { bg: "#e6efe0", fg: "#2f6a37" },
};

function statusChip(status: string) {
  const c = STATUS_COLOR[status] ?? { bg: "var(--wg-surface)", fg: "var(--wg-ink-soft)" };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        background: c.bg,
        color: c.fg,
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        borderRadius: 999,
        lineHeight: 1.4,
        whiteSpace: "nowrap",
      }}
    >
      {status}
    </span>
  );
}

const cell = {
  padding: "8px 10px",
  fontSize: 12,
  borderBottom: "1px solid var(--wg-line)",
  lineHeight: 1.35,
  verticalAlign: "top" as const,
};

export default async function TasksSheetPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/detail/tasks`);
  const t = await getTranslations();

  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }
  const tasks = state?.plan.tasks ?? [];
  const deps = state?.plan.dependencies ?? [];
  const milestones = state?.plan.milestones ?? [];
  const deliverables = state?.graph.deliverables ?? [];
  const members = state?.members ?? [];
  const assignmentsRaw = (state?.assignments ?? []) as Array<Record<string, unknown>>;

  const memberById = new Map<string, string>();
  for (const m of members)
    memberById.set(m.user_id, m.display_name || m.username);

  const assigneeOf = new Map<string, string>();
  for (const a of assignmentsRaw) {
    const taskId = typeof a.task_id === "string" ? a.task_id : null;
    const userId = typeof a.user_id === "string" ? a.user_id : null;
    const active = a.active === true || a.active === undefined;
    if (taskId && userId && active) {
      assigneeOf.set(taskId, memberById.get(userId) ?? userId);
    }
  }

  const deliverableTitle = new Map<string, string>(
    deliverables.map((d) => [d.id, d.title]),
  );
  const milestoneOf = new Map<string, string>();
  for (const m of milestones) {
    for (const tid of m.related_task_ids) milestoneOf.set(tid, m.title);
  }

  const depsFrom = new Map<string, string[]>();
  const depsTo = new Map<string, string[]>();
  for (const d of deps) {
    if (!depsFrom.has(d.from_task_id)) depsFrom.set(d.from_task_id, []);
    depsFrom.get(d.from_task_id)!.push(d.to_task_id);
    if (!depsTo.has(d.to_task_id)) depsTo.set(d.to_task_id, []);
    depsTo.get(d.to_task_id)!.push(d.from_task_id);
  }

  // Group rollups for the summary strip at top.
  const statusCounts: Record<string, number> = {};
  for (const task of tasks) {
    statusCounts[task.status] = (statusCounts[task.status] ?? 0) + 1;
  }
  const totalHours = tasks.reduce((s, task) => s + (task.estimate_hours ?? 0), 0);

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 10,
          flexWrap: "wrap",
        }}
      >
        <h2
          style={{
            fontSize: 16,
            fontWeight: 600,
            margin: 0,
            color: "var(--wg-ink)",
          }}
        >
          {t("detail.tasks.title")} · {tasks.length}
        </h2>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            flexWrap: "wrap",
          }}
        >
          {Object.entries(statusCounts).map(([k, v]) => (
            <span key={k} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              {statusChip(k)} <span>{v}</span>
            </span>
          ))}
          <span>· {totalHours}h total</span>
        </div>
      </div>

      {tasks.length === 0 ? (
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("detail.tasks.empty")}
        </div>
      ) : (
        <div
          style={{
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            background: "#fff",
            overflow: "auto",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
              tableLayout: "fixed",
            }}
          >
            <colgroup>
              <col style={{ width: "34%" }} />
              <col style={{ width: "12%" }} />
              <col style={{ width: "10%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "14%" }} />
              <col style={{ width: "8%" }} />
              <col style={{ width: "8%" }} />
            </colgroup>
            <thead>
              <tr
                style={{
                  background: "var(--wg-surface)",
                  fontSize: 10,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-ink-soft)",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  textAlign: "left",
                }}
              >
                <th style={{ ...cell, padding: "10px 10px" }}>
                  {t("detail.tasks.col.title")}
                </th>
                <th style={{ ...cell, padding: "10px 10px" }}>
                  {t("detail.tasks.col.assignee")}
                </th>
                <th style={{ ...cell, padding: "10px 10px" }}>
                  {t("detail.tasks.col.status")}
                </th>
                <th style={{ ...cell, padding: "10px 10px" }}>
                  {t("detail.tasks.col.milestone")}
                </th>
                <th style={{ ...cell, padding: "10px 10px" }}>
                  {t("detail.tasks.col.deliverable")}
                </th>
                <th style={{ ...cell, padding: "10px 10px", textAlign: "right" }}>
                  {t("detail.tasks.col.effort")}
                </th>
                <th style={{ ...cell, padding: "10px 10px", textAlign: "right" }}>
                  {t("detail.tasks.col.deps")}
                </th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => {
                const from = depsFrom.get(task.id) ?? [];
                const to = depsTo.get(task.id) ?? [];
                const depBadge = from.length || to.length
                  ? `${to.length > 0 ? `⇠${to.length}` : ""}${to.length && from.length ? " " : ""}${from.length > 0 ? `⇢${from.length}` : ""}`
                  : "—";
                return (
                  <tr key={task.id}>
                    <td style={cell}>
                      <div style={{ fontWeight: 500, color: "var(--wg-ink)" }}>
                        {task.title}
                      </div>
                      {task.assignee_role ? (
                        <div
                          style={{
                            fontSize: 10,
                            fontFamily: "var(--wg-font-mono)",
                            color: "var(--wg-ink-faint)",
                            marginTop: 2,
                          }}
                        >
                          {task.assignee_role}
                        </div>
                      ) : null}
                    </td>
                    <td style={cell}>
                      {assigneeOf.get(task.id) ?? (
                        <span style={{ color: "var(--wg-ink-faint)" }}>—</span>
                      )}
                    </td>
                    <td style={cell}>{statusChip(task.status)}</td>
                    <td style={cell}>
                      {milestoneOf.get(task.id) ?? (
                        <span style={{ color: "var(--wg-ink-faint)" }}>—</span>
                      )}
                    </td>
                    <td style={cell}>
                      {task.deliverable_id
                        ? deliverableTitle.get(task.deliverable_id) ?? "—"
                        : "—"}
                    </td>
                    <td style={{ ...cell, textAlign: "right", fontFamily: "var(--wg-font-mono)" }}>
                      {task.estimate_hours != null ? `${task.estimate_hours}h` : "—"}
                    </td>
                    <td
                      style={{
                        ...cell,
                        textAlign: "right",
                        fontFamily: "var(--wg-font-mono)",
                        color: "var(--wg-ink-soft)",
                      }}
                      title={
                        from.length || to.length
                          ? `${to.length} upstream · ${from.length} downstream`
                          : undefined
                      }
                    >
                      {depBadge}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
