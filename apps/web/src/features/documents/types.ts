// Feature-scoped types for the Documents / KB surface.
//
// Phase D scaffold (2026-05-13). These mirror the wire contract in
// graphflow_handoff_v062/API_CONTRACT.md §"Documents / KB" and the
// shape returned by `apps/api/src/workgraph_api/routers/documents.py`.
// Phase D.2 will move the authoritative definitions into
// `@/lib/documents` (paralleling `@/lib/flows`) and this file will
// re-export from there.
//
// Doctrine — `Document.is_project_brief` is what makes a doc render
// pinned with <ProjectBriefBadge />. Project Brief is a pinned KB
// document, not a separate concept (DESIGN_LOCK §"Locked IA").

// ── Document type filter ─────────────────────────────────────────────

// Wire-shape filter parameter passed to GET /api/documents?type=...
// Phase B.1 is permissive; only `brief` is honored server-side, the
// others are advisory until Phase B.2 wires KbItemRow.document_kind.
export type DocumentTypeFilter = "all" | "brief" | "note" | "attachment";

// ── Document (one row in /docs) ──────────────────────────────────────

// Shape returned by `_doc_from_kb()` in routers/documents.py. Mirrored
// here so the surface doesn't need a server roundtrip for typing.
export interface Document {
  document_id: string;
  scope_id: string;
  scope_label?: string; // human-readable scope name (mock-only for D.1)
  title: string;
  // KB scope distinguishes personal vs group writes. Different from
  // surface-level scope (project membership).
  scope: "personal" | "group";
  status: "draft" | "published" | "archived";
  is_project_brief: boolean;
  // Best-effort tag for what kind of doc this is (note / attachment /
  // brief). Phase B.2 will surface this from KbItemRow.document_kind.
  kind?: "brief" | "note" | "attachment";
  // For attachments only — mime + label hint (e.g. "PDF · 1.2 MB").
  attachment_hint?: string;
  updated_at: string;
  created_at: string;
  author?: { id: string; display_name: string };
  source?: string;
  body_md?: string; // populated by GET /api/documents/{id}
}

// ── Project brief envelope ───────────────────────────────────────────

// Shape returned by GET /api/scopes/{scope_id}/project-brief. Per
// INVARIANT_TESTS.md §"Project not routable as page", `document_id`
// is always defined (may be null in the 4-tier fallback edge case).
export interface ProjectBriefEnvelope {
  document_id: string | null;
  scope_id: string;
  brief: Document | null;
  fallback_used: boolean;
  fallback_reason?:
    | "title_heuristic"
    | "most_recent_group_doc"
    | "most_recent_doc"
    | "no_documents_in_scope";
}

// ── Publish response ─────────────────────────────────────────────────

// Shape returned by POST /api/documents/{id}/publish. Doctrine: the
// `memory_candidates` array is proposal-only — never accepted memory.
// Each entry routes the user through MemoryReviewDrawer via DrawerHost.
export interface MemoryCandidateProposal {
  candidate_id: string;
  proposed_atom_preview: string;
  // Mirrors MemoryCandidate from flow-center/types — kept lightweight
  // for the publish-response envelope. Full shape is fetched on
  // demand by MemoryReviewDrawer's GET /api/memory-candidates/:id.
}

export interface DocumentPublishResponse {
  document: Document;
  memory_candidates: MemoryCandidateProposal[];
  mutates_state: true;
}

// ── Right rail spine sections (per DESIGN_LOCK invariant #10) ────────

// Shared spine: Context / Related Work / Evidence / AI Assistance /
// Primary Action. Documents fills each section with doc-specific
// content but the order + names are universal across surfaces.
export interface DocumentRightRailData {
  context: {
    scope_id: string;
    scope_label?: string;
    last_edited_at: string;
    author?: { id: string; display_name: string };
  };
  related_work: Array<{
    kind: "task" | "topic" | "doc" | "flow_request";
    id: string;
    label: string;
  }>;
  evidence: Array<{
    kind: "verbatim" | "citation" | "decision";
    id: string;
    label: string;
  }>;
  // AI Assistance buttons are proposal-only (DESIGN_LOCK invariant #4).
  ai_assistance: Array<{
    action_id: string;
    label: string;
    description: string;
  }>;
}
