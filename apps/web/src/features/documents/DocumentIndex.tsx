"use client";

// DocumentIndex — grid of DocumentCard, with the Project Brief pinned
// at the top when the active scope has one. Doctrine
// (DESIGN_LOCK §"Locked IA"): Project Brief is a pinned KB document,
// not a separate page. The pin is achieved via render order + the
// ProjectBriefBadge on the card, not a routing detour.
//
// Phase D scaffold (2026-05-13). MOCK_DOCUMENTS lives here so the
// surface renders end-to-end while Phase D.2 wires the real
// GET /api/documents call.

import { EmptyState, Text } from "@/components/ui";

import { DocumentCard } from "./DocumentCard";
import type { Document, DocumentTypeFilter } from "./types";

// TODO(phase-d.2): replace with `useDocuments(scope_id, type)`
// backed by `GET /api/documents?scope_id=...&type=...`.
//
// Mock matrix (at least 6 docs):
//   1 Project Brief (with badge, current scope)
//   2 design notes (different scopes)
//   1 attachment (PDF placeholder)
//   1 KB entry from a different scope
//   1 most-recent edit
const MOCK_DOCUMENTS: Document[] = [
  {
    document_id: "doc_brief_tikhub",
    scope_id: "scope_tikhub",
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
  {
    document_id: "doc_note_layout_v3",
    scope_id: "scope_tikhub",
    scope_label: "TikHub",
    title: "Design Notes — Layout v3 critique",
    scope: "group",
    status: "published",
    is_project_brief: false,
    kind: "note",
    updated_at: "2026-05-13T09:14:00Z", // most-recent edit
    created_at: "2026-05-10T12:30:00Z",
    author: { id: "user_alex", display_name: "Alex" },
    source: "kb",
  },
  {
    document_id: "doc_note_pricing",
    scope_id: "scope_growth",
    scope_label: "Growth",
    title: "Design Notes — Pricing memo response",
    scope: "group",
    status: "published",
    is_project_brief: false,
    kind: "note",
    updated_at: "2026-05-11T15:48:00Z",
    created_at: "2026-05-11T15:20:00Z",
    author: { id: "user_ravi", display_name: "Ravi" },
    source: "kb",
  },
  {
    document_id: "doc_attach_vendor_pdf",
    scope_id: "scope_tikhub",
    scope_label: "TikHub",
    title: "Vendor contract — Acme Renewal 2026",
    scope: "group",
    status: "published",
    is_project_brief: false,
    kind: "attachment",
    attachment_hint: "PDF · 1.2 MB",
    updated_at: "2026-05-09T11:00:00Z",
    created_at: "2026-05-09T11:00:00Z",
    author: { id: "user_jess", display_name: "Jess" },
    source: "upload",
  },
  {
    document_id: "doc_kb_onboarding",
    scope_id: "scope_growth",
    scope_label: "Growth",
    title: "Onboarding playbook (v2)",
    scope: "group",
    status: "published",
    is_project_brief: false,
    kind: "note",
    updated_at: "2026-05-08T16:00:00Z",
    created_at: "2026-05-08T14:00:00Z",
    author: { id: "user_priya", display_name: "Priya" },
    source: "kb",
  },
  {
    document_id: "doc_personal_draft",
    scope_id: "scope_tikhub",
    scope_label: "TikHub",
    title: "Personal scratchpad — Q3 risks",
    scope: "personal",
    status: "draft",
    is_project_brief: false,
    kind: "note",
    updated_at: "2026-05-13T08:22:00Z",
    created_at: "2026-05-12T19:00:00Z",
    author: { id: "user_alex", display_name: "Alex" },
    source: "kb",
  },
];

// TODO(phase-d.2): wire to `GET /api/documents?scope_id=...&type=...`.
// Until then, filter the mock client-side.
export function useDocuments(
  scope_id?: string,
  type: DocumentTypeFilter = "all",
): Document[] {
  let docs = MOCK_DOCUMENTS;
  if (scope_id) {
    docs = docs.filter((d) => d.scope_id === scope_id);
  }
  if (type === "brief") {
    docs = docs.filter((d) => d.is_project_brief);
  } else if (type === "note") {
    docs = docs.filter((d) => d.kind === "note");
  } else if (type === "attachment") {
    docs = docs.filter((d) => d.kind === "attachment");
  }
  return docs;
}

export function DocumentIndex({
  scope_id,
  type = "all",
}: {
  scope_id?: string;
  type?: DocumentTypeFilter;
}) {
  const docs = useDocuments(scope_id, type);

  if (docs.length === 0) {
    return (
      <EmptyState>
        {/* TODO(i18n) */}
        No documents in this scope yet. Create one from the + menu.
      </EmptyState>
    );
  }

  // Pin the project brief(s) to the top of the grid. Doctrine — the
  // brief is a pinned KB document, the pinning is the visual lever.
  const briefs = docs.filter((d) => d.is_project_brief);
  const rest = docs
    .filter((d) => !d.is_project_brief)
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const ordered = [...briefs, ...rest];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {briefs.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Text
            variant="caption"
            muted
            style={{
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {/* TODO(i18n) */}
            Pinned — Project Brief
          </Text>
        </div>
      ) : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {ordered.map((doc) => (
          <DocumentCard key={doc.document_id} doc={doc} />
        ))}
      </div>
    </div>
  );
}
