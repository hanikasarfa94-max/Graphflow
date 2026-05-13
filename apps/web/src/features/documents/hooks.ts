// Documents feature hooks — Phase D scaffold (2026-05-13).
//
// Three mock hooks that mirror the API_CONTRACT.md §"Documents / KB"
// endpoints. Phase D.2 swaps them for real SWR-backed reads.
//
//   useDocuments(scope_id?, type?)  →  GET /api/documents
//   useDocument(id)                 →  GET /api/documents/:id
//   useProjectBrief(scope_id)       →  GET /api/scopes/:id/project-brief
//
// `useDocuments` re-exports from DocumentIndex.tsx (which owns the
// MOCK_DOCUMENTS roster). Keeping the roster co-located with the
// index component means there's one canonical mock source until D.2.

import { useDocuments } from "./DocumentIndex";
import type { Document, ProjectBriefEnvelope } from "./types";

export { useDocuments };

// TODO(phase-d.2): replace with real
//   `GET /api/documents/:id`
// returning a Document with body_md populated.
export function useDocument(id: string): Document | null {
  // Inline mock to avoid circular import on MOCK_DOCUMENTS — Phase
  // D.2's SWR fetcher will replace this end-to-end.
  if (!id) return null;
  return {
    document_id: id,
    scope_id: "scope_tikhub",
    scope_label: "TikHub",
    title: id === "doc_brief_tikhub" ? "TikHub Project Brief" : "Untitled document",
    scope: "group",
    status: "published",
    is_project_brief: id === "doc_brief_tikhub",
    kind: id === "doc_brief_tikhub" ? "brief" : "note",
    updated_at: "2026-05-13T09:14:00Z",
    created_at: "2026-04-02T10:00:00Z",
    author: { id: "user_mei", display_name: "Mei" },
    source: "kb",
    body_md:
      id === "doc_brief_tikhub"
        ? `# TikHub Project Brief

## Mission
Ship TikHub's v2 surface by end of Q3.

## Decisions to date
- Launch date locked to 2026-09-18.
- Vendor renewal pending VP-ops approval.

## Open questions
- Mobile parity in v2 or v2.1?
`
        : `# ${id}

Draft body. Replace with real content from the KbItemRow once the
backend wires GET /api/documents/{id}.
`,
  };
}

// TODO(phase-d.2): replace with real
//   `GET /api/scopes/:id/project-brief`
// Per INVARIANT_TESTS.md §"Project not routable as page", the
// returned envelope MUST always include `document_id` (may be null
// in the 4-tier fallback edge case).
export function useProjectBrief(scope_id: string): ProjectBriefEnvelope {
  if (!scope_id) {
    return {
      document_id: null,
      scope_id,
      brief: null,
      fallback_used: true,
      fallback_reason: "no_documents_in_scope",
    };
  }
  // Mock: every scope returns the TikHub brief for D.1 demo purposes.
  return {
    document_id: "doc_brief_tikhub",
    scope_id,
    brief: {
      document_id: "doc_brief_tikhub",
      scope_id,
      scope_label: "TikHub",
      title: "TikHub Project Brief",
      scope: "group",
      status: "published",
      is_project_brief: true,
      kind: "brief",
      updated_at: "2026-05-12T18:02:00Z",
      created_at: "2026-04-02T10:00:00Z",
      author: { id: "user_mei", display_name: "Mei" },
      source: "kb",
    },
    fallback_used: false,
  };
}
