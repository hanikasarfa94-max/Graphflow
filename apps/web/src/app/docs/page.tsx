// /docs — Documents / KB index.
//
// Phase D scaffold (2026-05-13). The full Documents feature body lives
// at `apps/web/src/features/documents/Documents.tsx`; this route file
// is a thin server wrapper that requires auth and renders the
// client-side feature. Mirrors the pattern in /flow-center/page.tsx.
//
// Doctrine (DESIGN_LOCK §"Locked IA") — Project Brief is a pinned KB
// document, not a separate page. `GET /api/scopes/:id/project-brief`
// always returns a `document_id` (4-tier fallback per the backend).
//
// API surface (Phase B.1 live, Phase D.2 wires reads):
//   GET  /api/documents?scope_id=...&type=all|brief|note|attachment
//   GET  /api/scopes/:scopeId/project-brief
//   POST /api/documents/:id/publish  (returns memory_candidates)

import { Documents } from "@/features/documents/Documents";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DocsIndexPage() {
  await requireUser("/docs");
  return <Documents />;
}
