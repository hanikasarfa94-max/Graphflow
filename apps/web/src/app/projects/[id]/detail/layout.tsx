// /projects/[id]/detail/layout.tsx — Batch B IA reshape.
//
// All /detail/* pages share this layout. The AuditTabBar is rendered
// at the top but self-hides on non-audit subpages (clarify, conflicts,
// delivery, events, im) so they keep their existing chrome. Visually
// this gives the 5 audit pages (graph/plan/tasks/risks/decisions) the
// "single page with internal tabs" experience the home_redesign
// HTML specced, without requiring us to move 5 substantial pages
// into one route.

import { AuditTabBar } from "@/components/audit/AuditTabBar";

export default async function DetailLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <AuditTabBar projectId={id} />
      {children}
    </>
  );
}
