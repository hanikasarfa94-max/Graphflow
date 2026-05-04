// /projects/[id]/detail/layout.tsx — Batch B IA reshape.
//
// All /detail/* pages share this layout. The AuditTabBar is rendered
// at the top but self-hides on non-audit subpages (clarify, conflicts,
// delivery, events, im) so they keep their existing chrome. Visually
// this gives the 5 audit pages (graph/plan/tasks/risks/decisions) the
// "single page with internal tabs" experience the home_redesign
// HTML specced, without requiring us to move 5 substantial pages
// into one route.
//
// Padding rationale: every audit subroute (plan/tasks/risks/decisions/
// graph) used to render flush against the AppShell main-column edge —
// PlanTable, the tasks list table, the risks list, etc. all start at
// their parent's left edge with no horizontal margin. Wrapping here
// gives all 10 detail subroutes consistent breathing room without
// touching each page individually. clamp(16px, 4vw, 32px) keeps it
// tight on mobile, generous on desktop.

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
    <div
      style={{
        padding: "20px clamp(16px, 4vw, 32px) 48px",
        maxWidth: 1280,
        margin: "0 auto",
      }}
    >
      <AuditTabBar projectId={id} />
      {children}
    </div>
  );
}
