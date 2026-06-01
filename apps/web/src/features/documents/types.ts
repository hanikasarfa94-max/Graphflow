// Feature-scoped types for the Documents / KB surface.
//
// Phase RW-8 (2026-05-13): shapes pruned to match the live wire from
// _doc_from_kb / _doc_full_from_kb in apps/api/.../documents.py. The
// Phase D scaffold types had fabricated fields (scope_label, kind,
// author, attachment_hint, body_md as optional) that didn't match
// what the BE emits. Removed.

import type { components } from "@/lib/api-types.gen";

export type DocumentTypeFilter = "all" | "brief" | "note" | "attachment";

// C1-C: generated-backed (GET /api/documents response_model=DocumentListResponse
// in routers/documents.py, mirroring _doc_from_kb). Stable names preserved.
// The singleton (`_doc_full_from_kb`) endpoint isn't promoted yet, so
// DocumentDetail below extends this generated base with its extra fields.
export type Document = components["schemas"]["Document"];

// Singleton extension — populated only by GET /api/documents/:id.
// C1-C: generated-backed (GET /api/documents/:id response_model=DocumentDetailResponse).
// attachment references the generated DocumentAttachment schema transitively.
export type DocumentDetail = components["schemas"]["DocumentDetail"];

// List endpoint wire shape. C1-C: generated-backed.
export type DocumentListResponse = components["schemas"]["DocumentListResponse"];

// Singleton wire shape. C1-C: generated-backed.
export type DocumentDetailResponse = components["schemas"]["DocumentDetailResponse"];

// Project brief envelope. Still hand-written: the /project-brief endpoint
// emits a `_todo` key on its last-resort branch that response_model would
// strip (and Pydantic can't model a leading-underscore field) — deferred.
export interface ProjectBriefEnvelope {
  document_id: string | null;
  scope_id: string;
  brief: Document | null;
  fallback_used: boolean;
  fallback_reason?: string;
}
