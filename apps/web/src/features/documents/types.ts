// Feature-scoped types for the Documents / KB surface.
//
// Phase RW-8 (2026-05-13): shapes pruned to match the live wire from
// _doc_from_kb / _doc_full_from_kb in apps/api/.../documents.py. The
// Phase D scaffold types had fabricated fields (scope_label, kind,
// author, attachment_hint, body_md as optional) that didn't match
// what the BE emits. Removed.

export type DocumentTypeFilter = "all" | "brief" | "note" | "attachment";

// Shape returned by `_doc_from_kb()` in routers/documents.py (list).
// Singleton (`_doc_full_from_kb`) extends with content_md + attachment.
export interface Document {
  document_id: string;
  scope_id: string | null;
  title: string;
  // KB scope distinguishes personal vs group writes.
  scope: "personal" | "group" | string;
  status: "draft" | "published" | "archived" | "pending-review" | string;
  is_project_brief: boolean;
  updated_at: string | null;
  created_at: string | null;
  source: string | null;
  owner_user_id: string | null;
}

// Singleton extension — populated only by GET /api/documents/:id.
export interface DocumentDetail extends Document {
  content_md: string | null;
  folder_id: string | null;
  attachment: {
    filename: string;
    mime: string | null;
    bytes: number | null;
    download_url: string;
  } | null;
}

// List endpoint wire shape.
export interface DocumentListResponse {
  documents: Document[];
  scope_id: string;
  type: DocumentTypeFilter;
}

// Singleton wire shape.
export interface DocumentDetailResponse {
  document: DocumentDetail;
}

// Project brief envelope — already real on the BE.
export interface ProjectBriefEnvelope {
  document_id: string | null;
  scope_id: string;
  brief: Document | null;
  fallback_used: boolean;
  fallback_reason?: string;
}
