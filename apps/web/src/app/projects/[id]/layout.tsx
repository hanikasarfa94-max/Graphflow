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
// F.16 prod-density pass: the project-title h1 is gone too. The
// sidebar already shows which project is selected, the URL has the id,
// and most pages render their own PageHeader — repeating the project
// title at the top of every subpage was pure chrome. We keep the
// metadata strip (tasks · deliverables · version) since it's signal,
// not chrome — one glance to see project size at any depth.
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
            marginBottom: 10,
            paddingBottom: 8,
            borderBottom: "1px solid var(--wg-line)",
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            whiteSpace: "nowrap",
          }}
        >
          {state.plan.tasks.length} tasks · {state.graph.deliverables.length}{" "}
          deliverables · v{state.requirement_version}
        </div>
      ) : null}
      {children}
    </div>
  );
}
