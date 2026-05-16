// /tasks/[id] — deep-link to a single task.
//
// Phase RW-7 (2026-05-13): server-side fetches GET /api/tasks/:id
// and passes the resolved task into TaskRightRail. The Phase D
// scaffold's useTask() mock with fabricated content_summary +
// invented evidence_sources + synthesized AI assistance buttons is
// gone. The right rail renders only real BE fields plus honest
// empty states.
//
// URL invariant (FRONTEND_IMPLEMENTATION.md §Routes): canonical
// task URL is /tasks/[id]. No /projects/<id>/tasks/<id>.

import { getTranslations } from "next-intl/server";

import { Card, EmptyState, Heading, Text } from "@/components/ui";
import { TaskRightRail } from "@/features/tasks/TaskRightRail";
import type { TaskDetailResponse } from "@/features/tasks/types";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

async function loadTask(id: string): Promise<
  | { kind: "ok"; data: TaskDetailResponse }
  | { kind: "forbidden" }
  | { kind: "not_found" }
  | { kind: "error" }
> {
  try {
    const data = await serverFetch<TaskDetailResponse>(
      `/api/tasks/${encodeURIComponent(id)}`,
    );
    return { kind: "ok", data };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 403) return { kind: "forbidden" };
      if (err.status === 404) return { kind: "not_found" };
    }
    return { kind: "error" };
  }
}

export default async function TaskDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/tasks/${id}`);
  const t = await getTranslations("shellV062.tasks.detail");
  const result = await loadTask(id);

  if (result.kind !== "ok") {
    return (
      <main
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          padding: "32px 28px 80px",
        }}
      >
        <Heading
          level={1}
          variant="hero"
          style={{ margin: "6px 0 12px" }}
        >
          {t("title")}
        </Heading>
        <Card>
          <EmptyState>
            {result.kind === "forbidden"
              ? t("forbidden")
              : result.kind === "not_found"
                ? t("notFound", { id })
                : t("loadError")}
          </EmptyState>
        </Card>
      </main>
    );
  }

  const task = result.data.task;

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
        <Text variant="caption" muted>
          {t("kicker")} · {task.id}
        </Text>
        <Heading
          level={1}
          variant="hero"
          style={{ margin: "6px 0 12px" }}
        >
          {task.title}
        </Heading>
        <Text as="p" variant="body" muted style={{ maxWidth: 640 }}>
          {t("subtitle")}
        </Text>
      </section>
      <TaskRightRail task={task} />
    </main>
  );
}
