"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { ProjectState } from "@/lib/api";

type Task = ProjectState["plan"]["tasks"][number];
type Member = ProjectState["members"][number];

type Assignment = {
  task_id: string;
  user_id: string;
  username?: string;
  display_name?: string;
};

type Comment = {
  id: string;
  author_id: string;
  author_username?: string;
  author_display_name?: string;
  body: string;
  created_at: string;
  parent_comment_id: string | null;
};

export function PlanTable({ state }: { state: ProjectState }) {
  const members = state.members;
  const deliverableTitle = useMemo(
    () => new Map(state.graph.deliverables.map((d) => [d.id, d.title])),
    [state.graph.deliverables],
  );

  // Seed assignment map from the initial /state snapshot. Then refresh
  // on mount so the client is authoritative (server may have mutated since
  // the page was rendered).
  const [assignments, setAssignments] = useState<Map<string, Assignment>>(
    () => {
      const m = new Map<string, Assignment>();
      for (const raw of state.assignments) {
        const a = raw as unknown as Assignment;
        if (a?.task_id) m.set(a.task_id, a);
      }
      return m;
    },
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const res = await fetch(
        `/api/projects/${state.project.id}/assignments`,
        { credentials: "include", cache: "no-store" },
      );
      if (!res.ok) return;
      const data = (await res.json()) as Assignment[];
      if (cancelled) return;
      const m = new Map<string, Assignment>();
      for (const a of data) m.set(a.task_id, a);
      setAssignments(m);
    })();
    return () => {
      cancelled = true;
    };
  }, [state.project.id]);

  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const setAssignee = useCallback(
    async (taskId: string, userId: string | null) => {
      setError(null);
      const res = await fetch(`/api/tasks/${taskId}/assignment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      setAssignments((prev) => {
        const next = new Map(prev);
        if (userId === null) {
          next.delete(taskId);
        } else {
          const member = members.find((m) => m.user_id === userId);
          next.set(taskId, {
            task_id: taskId,
            user_id: userId,
            username: member?.username,
            display_name: member?.display_name,
          });
        }
        return next;
      });
    },
    [members],
  );

  return (
    <div>
      {error && (
        <div
          role="alert"
          style={{
            marginBottom: 10,
            padding: "8px 12px",
            color: "var(--wg-accent)",
            fontSize: 13,
            fontFamily: "var(--wg-font-mono)",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius)",
          }}
        >
          {error}
        </div>
      )}
      <div
        style={{
          background: "#fff",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          overflow: "hidden",
        }}
      >
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}
        >
          <thead>
            <tr
              style={{
                background: "var(--wg-surface)",
                borderBottom: "1px solid var(--wg-line)",
              }}
            >
              <Th>Task</Th>
              <Th>Deliverable</Th>
              <Th>Assignee</Th>
              <Th style={{ textAlign: "right" }}>Est (h)</Th>
              <Th>Status</Th>
              <Th style={{ width: 80 }}></Th>
            </tr>
          </thead>
          <tbody>
            {state.plan.tasks.map((t) => {
              const assignment = assignments.get(t.id);
              const expanded = expandedTask === t.id;
              return (
                <TaskRow
                  key={t.id}
                  task={t}
                  assignment={assignment}
                  members={members}
                  deliverableTitle={deliverableTitle}
                  expanded={expanded}
                  onToggle={() =>
                    setExpandedTask(expanded ? null : t.id)
                  }
                  onAssigneeChange={(userId) => setAssignee(t.id, userId)}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TaskRow({
  task,
  assignment,
  members,
  deliverableTitle,
  expanded,
  onToggle,
  onAssigneeChange,
}: {
  task: Task;
  assignment: Assignment | undefined;
  members: Member[];
  deliverableTitle: Map<string, string>;
  expanded: boolean;
  onToggle: () => void;
  onAssigneeChange: (userId: string | null) => void;
}) {
  return (
    <>
      <tr style={{ borderBottom: "1px solid var(--wg-line)" }}>
        <Td>
          <div style={{ fontWeight: 600 }}>{task.title}</div>
          {task.description && (
            <div
              style={{
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                marginTop: 2,
              }}
            >
              {task.description}
            </div>
          )}
        </Td>
        <Td>
          {task.deliverable_id
            ? deliverableTitle.get(task.deliverable_id) ?? task.deliverable_id
            : "—"}
        </Td>
        <Td>
          <select
            value={assignment?.user_id ?? ""}
            onChange={(e) => onAssigneeChange(e.target.value || null)}
            style={{
              padding: "4px 6px",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              background: "#fff",
              fontSize: 13,
            }}
          >
            <option value="">
              {task.assignee_role ? `role: ${task.assignee_role}` : "unassigned"}
            </option>
            {members.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.display_name} (@{m.username})
              </option>
            ))}
          </select>
        </Td>
        <Td
          style={{
            textAlign: "right",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {task.estimate_hours ?? "—"}
        </Td>
        <Td>
          <span
            style={{
              padding: "2px 8px",
              borderRadius: 999,
              background: statusBg(task.status),
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {task.status}
          </span>
        </Td>
        <Td style={{ textAlign: "right" }}>
          <button
            type="button"
            onClick={onToggle}
            style={{
              background: "transparent",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius)",
              padding: "4px 10px",
              fontSize: 12,
              cursor: "pointer",
              color: "var(--wg-ink-soft)",
            }}
          >
            {expanded ? "Hide" : "Comments"}
          </button>
        </Td>
      </tr>
      {expanded && (
        <tr>
          <td
            colSpan={6}
            style={{
              padding: "12px 16px 16px",
              background: "var(--wg-surface)",
              borderBottom: "1px solid var(--wg-line)",
            }}
          >
            <CommentsThread targetKind="tasks" targetId={task.id} />
          </td>
        </tr>
      )}
    </>
  );
}

function CommentsThread({
  targetKind,
  targetId,
}: {
  targetKind: "tasks" | "deliverables" | "risks";
  targetId: string;
}) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const res = await fetch(
        `/api/${targetKind}/${targetId}/comments`,
        { credentials: "include", cache: "no-store" },
      );
      if (cancelled) return;
      if (!res.ok) {
        setError(`load failed (${res.status})`);
        setLoading(false);
        return;
      }
      const data = (await res.json()) as Comment[];
      if (!cancelled) {
        setComments(data);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [targetKind, targetId]);

  async function post() {
    const body = draft.trim();
    if (!body || posting) return;
    setPosting(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/${targetKind}/${targetId}/comments`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body }),
          credentials: "include",
        },
      );
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      const newComment = (await res.json()) as { comment?: Comment };
      if (newComment.comment) {
        setComments((prev) => [...prev, newComment.comment!]);
      }
      setDraft("");
    } finally {
      setPosting(false);
    }
  }

  return (
    <div>
      {loading ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          loading…
        </div>
      ) : comments.length === 0 ? (
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink-soft)",
            marginBottom: 8,
          }}
        >
          No comments yet. First one below.
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: "0 0 10px",
            display: "grid",
            gap: 8,
          }}
        >
          {comments.map((c) => (
            <li
              key={c.id}
              style={{
                padding: "8px 10px",
                background: "#fff",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                fontSize: 13,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-ink-soft)",
                  marginBottom: 3,
                }}
              >
                {c.author_display_name ?? c.author_username ?? c.author_id.slice(0, 8)}{" "}
                · {new Date(c.created_at).toLocaleString()}
              </div>
              <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {c.body}
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <div
          role="alert"
          style={{
            marginBottom: 6,
            fontSize: 12,
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              post();
            }
          }}
          placeholder="Add a comment…"
          style={{
            flex: 1,
            padding: "6px 10px",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 13,
            background: "#fff",
          }}
        />
        <button
          type="button"
          onClick={post}
          disabled={!draft.trim() || posting}
          style={{
            padding: "6px 12px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
            opacity: !draft.trim() || posting ? 0.6 : 1,
          }}
        >
          Post
        </button>
      </div>
    </div>
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
        padding: "10px 12px",
        textAlign: "left",
        fontWeight: 600,
        fontSize: 12,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        color: "var(--wg-ink-soft)",
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
    <td style={{ padding: "10px 12px", verticalAlign: "top", ...style }}>
      {children}
    </td>
  );
}

function statusBg(status: string): string {
  switch (status) {
    case "done":
      return "#dcf1dc";
    case "in_progress":
      return "#fff3d9";
    case "blocked":
      return "#fdecec";
    default:
      return "var(--wg-surface)";
  }
}
