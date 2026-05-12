// /tasks — global task index.
//
// Phase A.1 scaffold (2026-05-12). Replaces the project-scoped
// /projects/[id]/detail/tasks audit route. Tasks are global; the
// scope_id query param filters to a project. The full TaskList +
// TaskCard + RecognitionPolicyBadge surface arrives in Phase D.
//
// API surface (Phase B):
//   GET  /api/tasks?scope_id=...&view=my_tasks|all
//   POST /api/tasks/candidates
//   POST /api/tasks/:id/promote   (requires TaskRecognitionPolicy)
//
// TaskRecognitionPolicy enum (schemas.graphflow.json):
//   "none" | "assignee_accept" | "project_owner_confirm"
//   | "flow_required" | "review_required"
//
// TaskStatus enum (full lifecycle): personal_draft → candidate →
// confirmation_pending → accepted_personal → team_confirmed → in_progress
// → blocked → waiting_for_feedback → ready_for_review → done → archived

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function TasksIndexPage() {
  await requireUser("/tasks");

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Tasks"
        title="Tasks"
        subtitle="Work in flight. Tasks are context-born — they enter as candidates and ascend through recognition policy to canonical."
      />

      <Card title="Coming next">
        <Text variant="body" muted>
          Global task index with my_tasks / all views, recognition policy
          badges, and candidate promotion arrives in Phase D of{" "}
          <code>BUILD-v062.md</code>.
        </Text>
      </Card>
    </main>
  );
}
