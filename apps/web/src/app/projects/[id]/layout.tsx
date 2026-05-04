import { ProjectModuleRail } from "@/components/projects/ProjectModuleRail";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Project layout: auth + a single chrome row. ProjectBar used to live
// here too, but its only unique widget was the scope pills (the
// "当前项目: ..." text and surface crumb were redundant with the
// Topbar breadcrumb and the active rail tab). The scope pills moved
// into ProjectModuleRail's right side so we can ship one row of chrome
// instead of two.
export default async function ProjectLayout({
  params,
  children,
}: {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}`);

  return (
    <>
      <ProjectModuleRail projectId={id} />
      {children}
    </>
  );
}
