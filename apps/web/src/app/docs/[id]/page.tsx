// /docs/[id] — Document reader / editor for one KB document.
//
// Phase D scaffold (2026-05-13). Thin server wrapper that mirrors the
// pattern in /conversations/[id]/page.tsx — requires auth, then hands
// the id to the client-side `<DocumentDetail />` which owns
// view/edit toggling, the right rail, and the publish flow.
//
// Doctrine — for a Project Brief the URL is still /docs/[id]; there
// is no /projects/.../brief route (DESIGN_LOCK invariant #2: "Project
// is never a page"). The brief is just a pinned document with the
// `is_project_brief` flag, surfaced via <ProjectBriefBadge />.
//
// API surface (Phase D.2 wires reads):
//   GET  /api/documents/:id
//   POST /api/documents/:id/publish

import { DocumentDetail } from "@/features/documents/DocumentDetail";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DocumentDetailPage({
  params,
}: {
  // Next 15 / App Router — params is a Promise on dynamic routes.
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/docs/${id}`);
  return <DocumentDetail id={id} />;
}
