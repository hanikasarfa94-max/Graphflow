import { requireUser, serverFetch } from "@/lib/auth";
import type { ProjectState } from "@/lib/api";

export const dynamic = "force-dynamic";

// Phase Q — project layout is deliberately minimal.
//
// Navigation (Home / projects / team room / status / KB / renders / DMs)
// lives in the global AppSidebar. Notifications live in the sidebar's
// routed-inbox badge. The old in-page breadcrumb + h1 + sub-nav ate
// ~175px at the top of every chat view; gone.
//
// We keep a thin title strip so the user knows which project they're in
// when glancing at the main pane (redundant with sidebar highlighting,
// but useful when scrolled deep or sharing a screenshot). The project
// counts are rendered here in a tiny line — one glance, no chrome.
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
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }

  return (
    <div
      style={{
        maxWidth: 1200,
        margin: "0 auto",
        padding: "14px 20px",
      }}
    >
      {state ? (
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 12,
            marginBottom: 10,
            paddingBottom: 8,
            borderBottom: "1px solid var(--wg-line)",
          }}
        >
          <h1
            style={{
              fontSize: 14,
              fontWeight: 600,
              margin: 0,
              color: "var(--wg-ink)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={state.project.title}
          >
            {state.project.title}
          </h1>
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
              whiteSpace: "nowrap",
            }}
          >
            {state.plan.tasks.length} tasks · {state.graph.deliverables.length}{" "}
            deliverables · v{state.requirement_version}
          </span>
        </div>
      ) : null}
      {children}
    </div>
  );
}
