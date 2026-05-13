"use client";

// TaskList — task rows grouped by TaskStatus, rendered as TaskCards.
//
// Phase D scaffold (2026-05-13). Group rendering reflects the full
// state machine (schemas.graphflow.json §TaskStatus) so a viewer can
// see where work actually is — not just "open vs done."
//
// Grouping order (top → bottom) follows the lifecycle, but pushes the
// "needs me" states (confirmation_pending, ready_for_review, blocked,
// waiting_for_feedback) above the steady-state work so the next-step
// reading sits at the top of the page. Doctrine: status is signal.
//
// Mock data lives at the top of this file (MOCK_TASKS) so the surface
// renders end-to-end while wire shapes stabilize. Phase D.2 swap-in:
// replace MOCK_TASKS + useTasks() with:
//   `GET /api/tasks?scope_id=<active>&view=<my_tasks|all>`
// (apps/api/.../routers/tasks_global.py:135).

// TODO(i18n): externalize group header copy.

import { Card, EmptyState, Text } from "@/components/ui";

import { TaskCard } from "./TaskCard";
import type { TaskRow, TaskStatus, TaskView } from "./types";

// Display order for grouping. Action-required statuses sit above
// steady-state work; archived sits at the bottom.
const STATUS_GROUP_ORDER: TaskStatus[] = [
  "confirmation_pending",
  "ready_for_review",
  "blocked",
  "waiting_for_feedback",
  "in_progress",
  "candidate",
  "team_confirmed",
  "accepted_personal",
  "personal_draft",
  "done",
  "archived",
];

const STATUS_GROUP_LABEL: Record<TaskStatus, string> = {
  confirmation_pending: "Confirmation pending",
  ready_for_review: "Ready for review",
  blocked: "Blocked",
  waiting_for_feedback: "Waiting on feedback",
  in_progress: "In progress",
  candidate: "Candidates",
  team_confirmed: "Team confirmed",
  accepted_personal: "Accepted (personal)",
  personal_draft: "Personal drafts",
  done: "Done",
  archived: "Archived",
};

// ─── Mock data ──────────────────────────────────────────────────────
// Six rows minimum covering the policy / status matrix from the brief.
// Phase D.2 deletes this and switches useTasks() to a real fetch.
const MOCK_TASKS: TaskRow[] = [
  {
    id: "task_001",
    scope_id: "scope_tikhub",
    project_id: "scope_tikhub",
    title: "Draft Q3 OKR proposal for engineering",
    description: "Pre-read for the planning offsite next week.",
    scope: "personal",
    status: "personal_draft",
    owner_user_id: "user_alex",
    recognition_policy: "assignee_accept",
    assignee_display_name: "Alex",
    assignee_id: "user_alex",
    scope_label: "TikHub",
    requirement_id: null,
    source_message_id: "msg_okr_kickoff",
    estimate_hours: 4,
    created_at: "2026-05-11T09:00:00Z",
    updated_at: "2026-05-12T11:14:00Z",
  },
  {
    id: "task_002",
    scope_id: "scope_tikhub",
    project_id: "scope_tikhub",
    title: "Promote pricing tier audit to plan",
    description: "Owner sign-off needed before scope expansion.",
    scope: "personal",
    status: "candidate",
    owner_user_id: "user_ravi",
    recognition_policy: "project_owner_confirm",
    assignee_display_name: "Ravi",
    assignee_id: "user_ravi",
    scope_label: "TikHub",
    requirement_id: null,
    source_message_id: "msg_pricing_audit",
    estimate_hours: 6,
    created_at: "2026-05-10T16:20:00Z",
    updated_at: "2026-05-12T08:02:00Z",
  },
  {
    id: "task_003",
    scope_id: "scope_growth",
    project_id: "scope_growth",
    title: "Wire SSO callback into the new auth shim",
    description: "Touches the same auth surface as last sprint's migration.",
    scope: "plan",
    status: "in_progress",
    owner_user_id: "user_mei",
    recognition_policy: "assignee_accept",
    assignee_display_name: "Mei",
    assignee_id: "user_mei",
    scope_label: "Growth",
    requirement_id: "req_sso",
    source_message_id: null,
    estimate_hours: 12,
    created_at: "2026-05-05T13:45:00Z",
    updated_at: "2026-05-13T07:30:00Z",
  },
  {
    id: "task_004",
    scope_id: "scope_tikhub",
    project_id: "scope_tikhub",
    title: "Compliance review of the new SOC2 evidence pack",
    description: "Domain reviewer + project owner both required before publish.",
    scope: "plan",
    status: "ready_for_review",
    owner_user_id: "user_priya",
    recognition_policy: "review_required",
    assignee_display_name: "Priya",
    assignee_id: "user_priya",
    scope_label: "TikHub",
    requirement_id: "req_soc2",
    source_message_id: null,
    estimate_hours: 8,
    created_at: "2026-05-08T10:11:00Z",
    updated_at: "2026-05-12T18:00:00Z",
  },
  {
    id: "task_005",
    scope_id: "scope_growth",
    project_id: "scope_growth",
    title: "Onboarding handoff: surface → growth team",
    description: "Blocked on vendor SLA confirmation before re-routing ownership.",
    scope: "plan",
    status: "blocked",
    owner_user_id: "user_jess",
    recognition_policy: "flow_required",
    assignee_display_name: "Jess",
    assignee_id: "user_jess",
    scope_label: "Growth",
    requirement_id: "req_onboarding_handoff",
    source_message_id: null,
    estimate_hours: 5,
    created_at: "2026-05-04T09:30:00Z",
    updated_at: "2026-05-12T15:45:00Z",
  },
  {
    id: "task_006",
    scope_id: "scope_tikhub",
    project_id: "scope_tikhub",
    title: "Sign $40k vendor renewal — closed",
    description: "Approval flow completed; archived for citation.",
    scope: "plan",
    status: "done",
    owner_user_id: "user_vp_ops",
    recognition_policy: "flow_required",
    assignee_display_name: "VP Ops",
    assignee_id: "user_vp_ops",
    scope_label: "TikHub",
    requirement_id: "req_vendor_renewal",
    source_message_id: null,
    estimate_hours: 2,
    created_at: "2026-04-22T11:00:00Z",
    updated_at: "2026-05-09T16:22:00Z",
  },
];

// TODO(phase-d.2): replace with a real data hook.
//   `GET /api/tasks?scope_id=<id|undefined>&view=<my_tasks|all>`
// (apps/api/.../routers/tasks_global.py:135).
// `view='my_tasks'` filters server-side to owner_user_id == caller.
// `scope_id` omitted means cross-scope (all memberships).
export function useTasks(view: TaskView, scope_id?: string): TaskRow[] {
  // For the scaffold we filter the mock array client-side to mimic
  // the server contract. Real hook returns whatever the server sent.
  return MOCK_TASKS.filter((t) => {
    if (scope_id && t.scope_id !== scope_id) return false;
    if (view === "my_tasks" && t.owner_user_id !== "user_alex") {
      // Mock "me" is user_alex. D.2 will replace this with the real
      // session-aware filter on the server side.
      return false;
    }
    return true;
  });
}

export function TaskList({
  view,
  scopeId,
}: {
  view: TaskView;
  scopeId?: string;
}) {
  const tasks = useTasks(view, scopeId);

  if (tasks.length === 0) {
    return (
      <Card title="Tasks" flush>
        <div style={{ padding: 16 }}>
          <EmptyState>
            {/* TODO(i18n) */}
            No tasks here yet. Tasks are context-born — start a
            conversation, draft a document, or respond to a flow request
            and a task candidate may surface for promotion.
          </EmptyState>
        </div>
      </Card>
    );
  }

  // Bucket by status, preserving the doctrine display order.
  const buckets = new Map<TaskStatus, TaskRow[]>();
  for (const t of tasks) {
    const bucket = buckets.get(t.status) ?? [];
    bucket.push(t);
    buckets.set(t.status, bucket);
  }

  const visibleGroups = STATUS_GROUP_ORDER.filter((s) => buckets.has(s));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {visibleGroups.map((status) => {
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
    </div>
  );
}
