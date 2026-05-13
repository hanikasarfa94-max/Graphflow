"use client";

// TaskRightRail — five-section spine for a selected task.
//
// Phase D scaffold (2026-05-13). Renders the shared right-rail spine
// (schemas.graphflow.json §RightRailSpine):
//   1. Context
//   2. Related Work
//   3. Evidence / Sources
//   4. AI Assistance       (proposal-only, never mutates state)
//   5. Primary Action      (sticky CTA footer — state-changing)
//
// Doctrine — per FRONTEND_IMPLEMENTATION.md §"AI Assistance":
//   "AI Assistance buttons are secondary and proposal-only. Sticky CTA
//    footer performs state-changing actions."
// We honor that split visually: AI Assistance items render as small
// ghost buttons inside Section 4; the Section 5 footer holds the one
// state-changing action (e.g. "Promote", "Mark in progress").
//
// Link layer — every TaskRelatedItem.href is /tasks/, /nodes/,
// /decisions/, or /docs/. The link layer must NOT construct
// /projects/... URLs (Phase A.4 invariant).

// TODO(i18n): externalize section headers + primary action labels.

import Link from "next/link";

import { Button, Card, Text } from "@/components/ui";

import { RecognitionPolicyBadge } from "./RecognitionPolicyBadge";
import type { TaskDetail, TaskRecognitionPolicy, TaskStatus } from "./types";

// TODO(phase-d.2): replace with a real data hook.
//   `GET /api/tasks/:id` (Phase D.2 adds the singleton endpoint to
//   apps/api/.../routers/tasks_global.py) +
//   `GET /api/right-rail?surface=task&object_id=task_<id>` for refresh.
// The scaffold returns a deterministic stub keyed by id.
export function useTask(id: string): TaskDetail {
  // Stable demo content per id. Real hook returns server payload.
  const baseTitle = id === "task_004"
    ? "Compliance review of the new SOC2 evidence pack"
    : id === "task_005"
      ? "Onboarding handoff: surface → growth team"
      : id === "task_003"
        ? "Wire SSO callback into the new auth shim"
        : "Promote pricing tier audit to plan";

  const status: TaskStatus = id === "task_004"
    ? "ready_for_review"
    : id === "task_005"
      ? "blocked"
      : id === "task_003"
        ? "in_progress"
        : "candidate";

  const policy: TaskRecognitionPolicy = id === "task_004"
    ? "review_required"
    : id === "task_005"
      ? "flow_required"
      : id === "task_003"
        ? "assignee_accept"
        : "project_owner_confirm";

  return {
    id,
    scope_id: "scope_tikhub",
    project_id: "scope_tikhub",
    title: baseTitle,
    description: "Born from #pricing-room thread; needs owner sign-off before scope expansion.",
    scope: status === "candidate" ? "personal" : "plan",
    status,
    owner_user_id: "user_ravi",
    recognition_policy: policy,
    assignee_display_name: "Ravi",
    assignee_id: "user_ravi",
    scope_label: "TikHub",
    requirement_id: null,
    source_message_id: "msg_pricing_audit",
    estimate_hours: 6,
    created_at: "2026-05-10T16:20:00Z",
    updated_at: "2026-05-12T08:02:00Z",
    context_summary:
      "Surfaced from #pricing-room on 2026-05-10. The proposing message cites the Q2 enterprise renewal cohort; promotion will attach this task to the pricing plan and route to the project owner for confirmation.",
    related_work: [
      // Per URL invariant — /docs/, /tasks/, /nodes/, /decisions/.
      { kind: "doc", id: "doc_pricing_v3", label: "Pricing memo v3", href: "/docs/doc_pricing_v3" },
      { kind: "decision", id: "decision_q2_renewal", label: "Decision: Q2 renewal floor", href: "/decisions/decision_q2_renewal" },
      { kind: "node", id: "node_pricing_audit", label: "Node: pricing tier audit", href: "/nodes/node_pricing_audit" },
    ],
    evidence_sources: [
      {
        kind: "conversation_message",
        id: "msg_pricing_audit",
        excerpt: "We should audit the tier mapping before the renewal cohort lands.",
        author: "Ravi",
        timestamp: "2026-05-10T16:20:00Z",
      },
      {
        kind: "document",
        id: "doc_pricing_v3",
        excerpt: "Section 4.2 flags two tiers as ambiguous on the new contract.",
        author: "Mei",
        timestamp: "2026-05-09T11:00:00Z",
      },
    ],
    ai_assistance: [
      { label: "Draft assignment note", hint: "Compose a handoff line for the assignee." },
      { label: "Explain the recognition policy", hint: "Why this gate, and who can clear it." },
      { label: "Summarize blockers", hint: "Pull the latest blocker signals from related work." },
    ],
    primary_action_label:
      status === "candidate" ? "Promote to plan" : "Mark in progress",
  };
}

export function TaskRightRail({ taskId }: { taskId: string }) {
  const task = useTask(taskId);

  return (
    <aside
      aria-label="Task detail"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        // Right rail max-width per DESIGN.md §Layout.
        maxWidth: 360,
        width: "100%",
      }}
    >
      {/* Header — title, policy, assignee. Mirrors TaskCard but with
          more breathing room since this is the detail surface. */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Text variant="caption" muted>
          Task · {task.scope_label}
        </Text>
        <Text variant="body" style={{ fontWeight: 600, color: "var(--wg-ink)" }}>
          {task.title}
        </Text>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <RecognitionPolicyBadge policy={task.recognition_policy} />
          <Text variant="caption" muted>
            Assigned to {task.assignee_display_name}
          </Text>
        </div>
      </div>

      {/* 1. Context */}
      <Card title="Context">
        <Text variant="body">{task.context_summary}</Text>
      </Card>

      {/* 2. Related Work */}
      <Card title="Related work" flush>
        <div style={{ padding: "8px 0" }}>
          {task.related_work.length === 0 ? (
            <div style={{ padding: "8px 16px" }}>
              <Text variant="caption" muted>
                No linked items yet.
              </Text>
            </div>
          ) : (
            task.related_work.map((item) => (
              <Link
                key={item.id}
                href={item.href}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 8,
                  padding: "10px 16px",
                  borderBottom: "1px solid var(--wg-line-soft)",
                  textDecoration: "none",
                  color: "var(--wg-ink)",
                }}
              >
                <Text variant="body">{item.label}</Text>
                <Text variant="caption" muted>
                  {item.kind}
                </Text>
              </Link>
            ))
          )}
        </div>
      </Card>

      {/* 3. Evidence / Sources */}
      <Card title="Evidence" flush>
        <div style={{ padding: "8px 0" }}>
          {task.evidence_sources.map((src) => (
            <div
              key={src.id}
              style={{
                padding: "10px 16px",
                borderBottom: "1px solid var(--wg-line-soft)",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              <Text variant="caption" muted>
                {src.kind} · {src.author}
              </Text>
              <Text variant="body">{src.excerpt}</Text>
            </div>
          ))}
        </div>
      </Card>

      {/* 4. AI Assistance — proposal-only, never mutates state. */}
      <Card title="AI Assistance">
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {task.ai_assistance.map((a) => (
            <div
              key={a.label}
              style={{ display: "flex", flexDirection: "column", gap: 4 }}
            >
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  // TODO(phase-d.2): POST /api/ai-assistance/run
                  // with mutates_state: false. Phase D scaffold just
                  // logs; no state change at all.
                  // eslint-disable-next-line no-console
                  console.info("[ai-assistance] propose:", a.label);
                }}
              >
                {a.label}
              </Button>
              <Text variant="caption" muted>
                {a.hint}
              </Text>
            </div>
          ))}
          <Text variant="caption" muted>
            Proposal-only. AI Assistance never mutates state.
          </Text>
        </div>
      </Card>

      {/* 5. Primary Action — sticky CTA footer.
          The only state-changing surface in this rail. */}
      <div
        style={{
          position: "sticky",
          bottom: 0,
          background: "var(--wg-surface)",
          borderTop: "1px solid var(--wg-line)",
          padding: "12px 0",
          display: "flex",
          gap: 8,
        }}
      >
        <Button
          variant="primary"
          onClick={() => {
            // TODO(phase-d.2): POST /api/tasks/:id/promote with the
            // selected TaskRecognitionPolicy (currently inherited from
            // the task object) OR the appropriate state-transition
            // endpoint. The API rejects recognition_policy="none".
            // eslint-disable-next-line no-console
            console.info("[task] primary action:", task.primary_action_label);
          }}
          style={{ flex: 1 }}
        >
          {task.primary_action_label}
        </Button>
        <Button variant="ghost" onClick={() => history.back()}>
          Close
        </Button>
      </div>
    </aside>
  );
}
