import { ProjectBar } from "@/components/projects/ProjectBar";
import { ProjectModuleRail } from "@/components/projects/ProjectModuleRail";
import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// When SHELL_VNEXT=true, the global v-Next shell already provides a
// ProjectBar (ProjectBarVNext at the top) and a Rail with the same
// detail-page glyphs that ProjectModuleRail used to surface. Rendering
// both layers here piles two project bars + two nav strips on every
// /projects/[id]/... route, which is the "pile" we keep getting bug
// reports about. Honor the env flag the same way layout.tsx does.
const SHELL_VNEXT_ACTIVE = process.env.SHELL_VNEXT === "true";

// Legacy phase-Q project layout: auth + ProjectBar + ProjectModuleRail.
// Per memory workgraph_next_design_20260428: "ProjectBar pills are
// scope control" — this was the persistent home for the scope-tier
// widget so all subroutes share one canonical toggle. In v-next that
// duty moves to the global shell.
export default async function ProjectLayout({
  params,
  children,
}: {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}`);

  // v-Next: shell already owns the project chrome — just authenticate
  // and pass through. ProjectBarVNext + Rail handle crumb / scope
  // pills / per-project surface switching in the global shell.
  if (SHELL_VNEXT_ACTIVE) {
    return <>{children}</>;
  }

  // Pull just the project title for the bar. Swallow errors — a 404
  // here would break every project subroute; better to render the
  // bar with "Untitled" and let the page layer handle the real error.
  let projectTitle: string | null = null;
  try {
    const state = await serverFetch<ProjectState>(
      `/api/projects/${id}/state`,
    );
    projectTitle = state.project?.title ?? null;
  } catch {
    projectTitle = null;
  }

  return (
    <>
      <ProjectBar projectId={id} projectTitle={projectTitle} />
      <ProjectModuleRail projectId={id} />
      {children}
    </>
  );
}
