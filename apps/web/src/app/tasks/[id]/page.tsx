// /tasks/[id] — deep-link to a single task.
//
// Phase D scaffold (2026-05-13). The detail page is intentionally
// minimal: PageHeader + TaskRightRail (5-section spine). The right
// rail carries the load-bearing surface; the left side is reserved
// for a future timeline / comments stream (Phase D.2).
//
// URL invariant (FRONTEND_IMPLEMENTATION.md §Routes): the canonical
// task URL is /tasks/[id]. There is NO /projects/<id>/tasks/<id>.

import { Heading, Text } from "@/components/ui";
import { TaskRightRail } from "@/features/tasks/TaskRightRail";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/tasks/${id}`);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) 380px",
        gap: 24,
        alignItems: "start",
      }}
    >
      <section>
        {/* TODO(i18n) */}
        <Text variant="caption" muted>
          Task · {id}
        </Text>
        <Heading
          level={1}
          variant="display"
          style={{ margin: "6px 0 12px", letterSpacing: "-0.02em" }}
        >
          Task detail
        </Heading>
        <Text as="p" variant="body" muted style={{ maxWidth: 640 }}>
          The full timeline + comments stream lands in Phase D.2. The
          right rail carries the doctrine-load-bearing surface today:
          Context, Related Work, Evidence, AI Assistance, and the
          state-changing Primary Action.
        </Text>
      </section>
      <TaskRightRail taskId={id} />
    </main>
  );
}
