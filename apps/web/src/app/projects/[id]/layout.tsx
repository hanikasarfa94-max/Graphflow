import { ProjectBar } from "@/components/projects/ProjectBar";
import { ProjectModuleRail } from "@/components/projects/ProjectModuleRail";
import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Phase-Q project layout: auth + ProjectBar + ProjectModuleRail.
// Per memory workgraph_next_design_20260428: "ProjectBar pills are
// scope control" — the persistent home for the scope-tier widget so
// all subroutes share one canonical toggle.
export default async function ProjectLayout({
  params,
  children,
}: {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}`);

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
