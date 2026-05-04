import { getTranslations } from "next-intl/server";

import { ArtifactsPanel } from "@/components/status/ArtifactsPanel";
import { BudgetControl } from "@/components/status/BudgetControl";
import { DecisionsPanel } from "@/components/status/DecisionsPanel";
import { MembersPanel } from "@/components/status/MembersPanel";
import { MembraneNotesPanel } from "@/components/status/MembraneNotesPanel";
import { Panel } from "@/components/status/Panel";
import { RenderTriggers } from "@/components/status/RenderTriggers";
import { RisksPanel } from "@/components/status/RisksPanel";
import { TasksPanel } from "@/components/status/TasksPanel";
import { Metric, PageHeader, Text } from "@/components/ui";
import type {
  MembraneNotesResponse,
  PersonalTask,
  ProjectState,
} from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";
import { formatIso } from "@/lib/time";

export const dynamic = "force-dynamic";

// Read-only status dashboard (Phase G). First-use surface for finance
// role; audit slice for everyone else. Pulls one `/state` snapshot and
// renders panels server-side — no mutations, no client-side fetches.
// When pieces of data are missing (e.g., the /state call fails), the
// page still renders with graceful empty states rather than 500ing.
//
// Phase Q.7 addition: a RenderTriggers panel at the bottom surfaces the
// postmortem + handoff render flows, which previously had no visible
// entry point in the UI.
export default async function ProjectStatusPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const t = await getTranslations();
  // We need the current user id to filter them out of the handoff list
  // (you don't generate a handoff doc for yourself).
  const user = await requireUser(`/projects/${id}/status`);

  let state: ProjectState | null = null;
  let personalTasks: PersonalTask[] = [];
  let errorMessage: string | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : "failed to load project";
  }
  // Personal tasks live in a separate fetch — they're per-viewer and
  // not part of /state (which is project-wide). Failure here is non-
  // fatal: the panel still renders the plan-scope tasks.
  try {
    const r = await serverFetch<{ ok: true; tasks: PersonalTask[] }>(
      `/api/projects/${id}/personal-tasks`,
    );
    personalTasks = r.tasks ?? [];
  } catch {
    /* non-fatal — drafts surface stays empty */
  }

  // Batch C — membrane notes (pending reviews + clarifications).
  // Surfaces the membrane's outstanding work so it's not invisible.
  // Empty state is the calm default; loud only when there's work.
  let membraneNotes: MembraneNotesResponse | null = null;
  try {
    membraneNotes = await serverFetch<MembraneNotesResponse>(
      `/api/projects/${id}/membrane/notes`,
    );
  } catch {
    /* non-fatal */
  }

  const refreshedAt = formatIso();

  return (
    <main
      style={{
        padding: "20px clamp(16px, 4vw, 32px) 48px",
        maxWidth: 1280,
        margin: "0 auto",
      }}
    >
      <PageHeader
        title={t("status.title")}
        subtitle={t("status.subtitle")}
        right={
          <Text variant="caption" muted>
            {t("status.lastRefreshed", { time: refreshedAt })}
          </Text>
        }
      />

      {/* Batch F.3 — 4-metric strip per html2 spec. Counts are derived
          straight from the ProjectState payload we already fetched, so
          they always agree with the panels below. Open-only filter on
          risks matches the legacy panel's display rule. */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 12,
          marginBottom: 18,
        }}
      >
        <Metric
          value={state?.plan?.tasks?.length ?? 0}
          label={t("status.metrics.tasks")}
        />
        <Metric
          value={state?.graph?.deliverables?.length ?? 0}
          label={t("status.metrics.deliverables")}
        />
        <Metric
          value={
            (state?.graph?.risks ?? []).filter((r) => r.status === "open").length
          }
          label={t("status.metrics.risks")}
          tone={
            (state?.graph?.risks ?? []).some(
              (r) => r.status === "open" && (r.severity === "critical" || r.severity === "high"),
            )
              ? "danger"
              : (state?.graph?.risks ?? []).some((r) => r.status === "open")
                ? "amber"
                : "neutral"
          }
        />
        <Metric
          value={state?.decisions?.length ?? 0}
          label={t("status.metrics.decisions")}
          tone="accent"
        />
      </section>

      {state?.requirement_id &&
      (state?.members ?? []).find((m) => m.user_id === user.id)?.role ===
        "owner" ? (
        <div style={{ marginBottom: 16 }}>
          <BudgetControl
            projectId={id}
            requirementId={state.requirement_id}
            initialBudgetHours={state.budget_hours ?? null}
          />
        </div>
      ) : null}

      {errorMessage ? (
        <Panel title={t("status.title")}>
          <div role="alert" style={{ padding: 12 }}>
            <Text variant="body" style={{ color: "var(--wg-accent)", fontFamily: "var(--wg-font-mono)" }}>
              {errorMessage}
            </Text>
          </div>
        </Panel>
      ) : null}

      <div
        style={{
          display: "grid",
          gap: 16,
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          alignItems: "start",
        }}
      >
        <div style={{ gridColumn: "1 / -1" }}>
          <MembersPanel
            members={state?.members ?? []}
            projectId={id}
            currentUserId={user.id}
          />
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <MembraneNotesPanel projectId={id} notes={membraneNotes} />
        </div>
        <TasksPanel
          tasks={state?.plan.tasks ?? []}
          personalTasks={personalTasks}
          assignments={state?.assignments ?? []}
          members={state?.members ?? []}
          currentUserId={user.id}
          isProjectOwner={
            (state?.members ?? []).find((m) => m.user_id === user.id)?.role ===
            "owner"
          }
          projectId={id}
        />
        <RisksPanel risks={state?.graph.risks ?? []} />
        <DecisionsPanel decisions={state?.decisions ?? []} projectId={id} />
        <ArtifactsPanel />
        <div style={{ gridColumn: "1 / -1" }}>
          <RenderTriggers
            projectId={id}
            members={state?.members ?? []}
            currentUserId={user.id}
          />
        </div>
      </div>
    </main>
  );
}
