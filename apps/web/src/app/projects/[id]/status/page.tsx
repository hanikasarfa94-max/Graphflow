import { getTranslations } from "next-intl/server";

import { ArtifactsPanel } from "@/components/status/ArtifactsPanel";
import { DecisionsPanel } from "@/components/status/DecisionsPanel";
import { MembersPanel } from "@/components/status/MembersPanel";
import { Panel } from "@/components/status/Panel";
import { RenderTriggers } from "@/components/status/RenderTriggers";
import { RisksPanel } from "@/components/status/RisksPanel";
import { TasksPanel } from "@/components/status/TasksPanel";
import { Heading, Text } from "@/components/ui";
import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

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
  let errorMessage: string | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : "failed to load project";
  }

  const refreshedAt = new Date().toLocaleString();

  return (
    <main>
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <Heading level={2}>{t("status.title")}</Heading>
        <Text variant="caption" muted>
          {t("status.lastRefreshed", { time: refreshedAt })}
        </Text>
      </header>

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
          <MembersPanel members={state?.members ?? []} />
        </div>
        <TasksPanel
          tasks={state?.plan.tasks ?? []}
          assignments={state?.assignments ?? []}
          members={state?.members ?? []}
          currentUserId={user.id}
          isProjectOwner={
            (state?.members ?? []).find((m) => m.user_id === user.id)?.role ===
            "owner"
          }
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
