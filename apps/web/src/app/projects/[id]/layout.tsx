import Link from "next/link";

import { requireUser, serverFetch } from "@/lib/auth";
import type { ProjectState } from "@/lib/api";

import { NotificationBell } from "./NotificationBell";
import { ProjectNav } from "./ProjectNav";

export const dynamic = "force-dynamic";

export default async function ProjectLayout({
  params,
  children,
}: {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}`);
  let state: ProjectState | null = null;
  let errorMessage: string | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch (e) {
    errorMessage = e instanceof Error ? e.message : "failed to load project";
  }

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 24px" }}>
      <header
        style={{
          marginBottom: 20,
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            <Link
              href="/projects"
              style={{ color: "var(--wg-ink-soft)", textDecoration: "none" }}
            >
              ← projects
            </Link>
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 600, margin: "6px 0 2px" }}>
            {state?.project.title ?? (errorMessage ? "Unavailable" : "Loading…")}
          </h1>
          <div
            style={{
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {state
              ? `${state.graph.deliverables.length} deliverables · ${state.plan.tasks.length} tasks · v${state.requirement_version}`
              : errorMessage ?? ""}
          </div>
        </div>
        <NotificationBell projectId={id} />
      </header>

      <ProjectNav
        projectId={id}
        conflictBadge={state?.conflict_summary?.open ?? 0}
      />

      <div style={{ marginTop: 24 }}>{children}</div>
    </div>
  );
}
