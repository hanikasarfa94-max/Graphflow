// /docs — Documents / KB index.
//
// Phase A.1 scaffold (2026-05-12). Replaces /projects/[id]/kb and
// /projects/[id]/renders. The full DocumentIndex with Project Brief
// pinned (ProjectBriefBadge) + editor with publish→memory_candidate
// flow arrives in Phase D per BUILD-v062.md.
//
// Doctrine — Project Brief is a pinned KB document, not a separate
// concept. DocumentEditor's publish action returns memory_candidates,
// never accepted memory (memory crystallization is a separate decision).
//
// API surface (Phase B):
//   GET  /api/documents?scope_id=...&type=all
//   GET  /api/scopes/:scopeId/project-brief
//   POST /api/documents/:id/publish  (returns memory_candidates)

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DocsIndexPage() {
  await requireUser("/docs");

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Documents · KB"
        title="Documents"
        subtitle="Project Briefs, rendered artifacts, knowledge entries. Authoring is a path to memory candidates — publish doesn't make memory canonical."
      />

      <Card title="Coming next">
        <Text variant="body" muted>
          Document index with Project Brief, KB browser, and the
          publish→memory-candidate flow lands in Phase D of{" "}
          <code>BUILD-v062.md</code>.
        </Text>
      </Card>
    </main>
  );
}
