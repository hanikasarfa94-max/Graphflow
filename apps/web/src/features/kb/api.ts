// Feature-scoped KB client. Pilot extraction from `lib/api.ts` as part
// of the GraphFlow Architecture Organization Pass v1 (Phase D). Runtime
// URL strings, request bodies, and response shapes are byte-identical
// to the originals — `lib/api.ts` re-exports every public symbol below
// so existing call sites continue importing from `@/lib/api` unchanged.
//
// Future passes will move other features (rooms, decisions, etc.) the
// same way; until then this is the only feature-scoped client.

import { ApiError, api, type JsonValue } from "@/lib/api";

// ---------- Knowledge base (Phase Q.6) ----------
//
// Browseable KB surface. Backend endpoints:
//   GET /api/projects/{id}/kb               → list (optional query/source_kind/limit)
//   GET /api/projects/{id}/kb/{item_id}     → single item + raw_content
//
// The KB corpus is primarily LLM-facing (routing, retrieval, citations),
// but per `docs/north-star.md` §Q.6 the user-facing browse/search page
// ships in v1 so humans can audit what the edge LLM is grounded on. The
// listing endpoint may 404 while Phase Q-A is in flight — callers must
// catch `ApiError` with `status === 404` and render a "coming soon" state
// rather than propagating the failure.

// Two status vocabularies share the kb_items table post-fold:
//   * ingest rows (source='ingest')      — pending-review|approved|rejected|routed
//   * user-authored (manual/upload/llm)  — draft|published|archived
// Both are valid wherever a KB item appears. Renderer code switches on
// status to show the right chip; the backend doesn't enforce per-source
// transitions at the type system level.
export type KbItemStatus =
  | "pending-review"
  | "approved"
  | "rejected"
  | "routed"
  | "draft"
  | "published"
  | "archived";

export interface KbItem {
  id: string;
  source_kind: string;
  source_identifier: string | null;
  summary: string;
  tags: string[];
  status: KbItemStatus;
  created_at: string;
  ingested_by_user_id: string | null;
  ingested_by_username?: string;
}

export interface KbItemDetail extends KbItem {
  raw_content: string;
  classification_json?: Record<string, unknown> | null;
  // User-authored shape — populated for save-as-kb / paste / upload
  // (source in {'manual','upload','llm'}). Null for ingest rows. The
  // BE _kb_detail_payload emits both shapes from the unified
  // kb_items table; the FE picks whichever is populated.
  title?: string | null;
  content_md?: string | null;
  scope?: string | null;
  source?: string | null;
  owner_user_id?: string | null;
}

export interface KbListParams {
  query?: string;
  source_kind?: string;
  limit?: number;
}

function buildKbQuery(params?: KbListParams): string {
  if (!params) return "";
  const q = new URLSearchParams();
  if (params.query && params.query.trim()) q.set("query", params.query.trim());
  if (params.source_kind && params.source_kind !== "all") {
    q.set("source_kind", params.source_kind);
  }
  if (params.limit) q.set("limit", String(params.limit));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listProjectKb(
  projectId: string,
  params?: KbListParams,
  baseUrl?: string,
): Promise<{ items: KbItem[] }> {
  return api<{ items: KbItem[] }>(
    `/api/projects/${projectId}/kb${buildKbQuery(params)}`,
    { baseUrl },
  );
}

export async function getKbItem(
  projectId: string,
  itemId: string,
  baseUrl?: string,
): Promise<KbItemDetail> {
  // BE returns `{ok: true, item: KbItemDetail}` — unwrap so callers get
  // the row directly. (Previously this helper claimed to return
  // KbItemDetail but actually resolved to the wrapper, leaving every
  // field undefined; the route page worked around it with a hand-typed
  // serverFetch. Keeping the helper honest prevents that landmine
  // recurring in any future caller.)
  const res = await api<{ ok: boolean; item: KbItemDetail }>(
    `/api/projects/${projectId}/kb/${itemId}`,
    { baseUrl },
  );
  return res.item;
}

// ---------- Phase 3.A — hierarchical KB ----------
//
// Folder tree on top of the flat KB. The tree endpoint returns folders
// + items as two flat arrays with parent_id pointers; the client nests
// in memory. Cycle detection + per-item license override live on the
// backend (see apps/api/src/workgraph_api/services/kb_hierarchy.py).

export type LicenseTier = "full" | "task_scoped" | "observer";

// C1-C: generated-backed (GET /api/projects/{id}/kb/tree response_model=
// KbTreeResponse). Generated renders nullable fields as optional (| undefined)
// and widens status/license_tier_override to string; the 4 consumer sites that
// relied on | null / the LicenseTier union were updated with mechanical
// `?? []` / `?? null` / casts.
export type KbFolderNode = components["schemas"]["KbFolderNode"];
export type KbTreeItem = components["schemas"]["KbTreeItem"];
export type KbTreeResponse = components["schemas"]["KbTreeResponse"];

export function getKbTree(
  projectId: string,
  baseUrl?: string,
): Promise<KbTreeResponse> {
  return api<KbTreeResponse>(`/api/projects/${projectId}/kb/tree`, {
    baseUrl,
  });
}

export function createKbFolder(
  projectId: string,
  body: { name: string; parent_folder_id: string | null },
): Promise<{ ok: true; folder: KbFolderNode }> {
  return api(`/api/projects/${projectId}/kb/folders`, {
    method: "POST",
    body,
  });
}

export function reparentKbFolder(
  projectId: string,
  folderId: string,
  newParentId: string | null,
): Promise<{ ok: true; folder: KbFolderNode }> {
  return api(
    `/api/projects/${projectId}/kb/folders/${folderId}/parent`,
    { method: "PATCH", body: { new_parent_id: newParentId } },
  );
}

export function deleteKbFolder(
  projectId: string,
  folderId: string,
): Promise<{ ok: true; deleted_id: string }> {
  return api(`/api/projects/${projectId}/kb/folders/${folderId}`, {
    method: "DELETE",
  });
}

export function moveKbItem(
  projectId: string,
  itemId: string,
  folderId: string,
): Promise<{ ok: true; item_id: string; folder_id: string | null }> {
  return api(
    `/api/projects/${projectId}/kb/items/${itemId}/folder`,
    { method: "PATCH", body: { folder_id: folderId } },
  );
}

export function setKbItemLicense(
  projectId: string,
  itemId: string,
  licenseTier: LicenseTier | null,
): Promise<{
  ok: true;
  item_id: string;
  license_tier: LicenseTier | null;
}> {
  return api(
    `/api/projects/${projectId}/kb/items/${itemId}/license`,
    { method: "PUT", body: { license_tier: licenseTier } },
  );
}

// ---------- KB items (Phase V — manual-write notes) -------------------

// Helper unions retained for mutation call sites (createKbNote / updateKbNote /
// uploadKbNote args below accept these narrowed values). The KbNote wire type
// itself is now generated-backed where these surface as plain `string`.
export type KbNoteScope = "personal" | "group";
export type KbNoteStatus = "draft" | "published" | "archived";
export type KbNoteSource = "manual" | "upload" | "llm";

// C1-C: generated-backed (GET /api/kb-items/{id} response_model=KbNote;
// GET /api/projects/{id}/kb-items response_model=KbNoteListResponse). Widened to
// runtime truth: project_id/owner_user_id are str | None (unified ingest+authored
// table), and attachment.mime/bytes are nullable. Audit confirmed no consumer
// reads project_id/owner_user_id as non-null. scope/status/source are `string`.
import type { components } from "@/lib/api-types.gen";

export type KbNoteAttachment = components["schemas"]["KbNoteAttachment"];
export type KbNote = components["schemas"]["KbNote"];
export type KbNoteListResponse = components["schemas"]["KbNoteListResponse"];

export function listKbNotes(
  projectId: string,
  baseUrl?: string,
): Promise<KbNoteListResponse> {
  return api(`/api/projects/${projectId}/kb-items`, { baseUrl });
}

export function getKbNote(
  itemId: string,
  baseUrl?: string,
): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}`, { baseUrl });
}

export function createKbNote(
  projectId: string,
  input: {
    title: string;
    content_md?: string;
    scope?: KbNoteScope;
    folder_id?: string;
    source?: KbNoteSource;
    status?: KbNoteStatus;
  },
): Promise<KbNote> {
  return api(`/api/projects/${projectId}/kb-items`, {
    method: "POST",
    body: input as unknown as JsonValue,
  });
}

export function updateKbNote(
  itemId: string,
  input: {
    title?: string;
    content_md?: string;
    status?: KbNoteStatus;
    folder_id?: string | null;
  },
): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}`, {
    method: "PATCH",
    body: input as unknown as JsonValue,
  });
}

export function deleteKbNote(
  itemId: string,
): Promise<{ ok: boolean; deleted_id: string }> {
  return api(`/api/kb-items/${itemId}`, { method: "DELETE" });
}

export function promoteKbNote(itemId: string): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}/promote`, { method: "POST" });
}

export function demoteKbNote(itemId: string): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}/demote`, { method: "POST" });
}

// M1.2 — soft-archive primitive. Project owner for group-scope; item
// owner for personal-scope. Excluded from is_canonical_kb_row + KB
// listing afterwards.
export function archiveKbNote(itemId: string): Promise<KbNote> {
  return api(`/api/kb-items/${itemId}/archive`, { method: "POST" });
}

// M1.2 — non-owner archive request. Posts an IMSuggestion(membrane_review)
// for the project owner to accept or dismiss.
export function requestArchiveKb(
  itemId: string,
  body: { reason: string; suggested_replacement_id?: string },
): Promise<{
  ok: boolean;
  suggestion_id: string;
  kb_item_id: string;
  message_id: string;
}> {
  // `api()` already JSON.stringifies the body — pass the plain object,
  // otherwise the backend receives a double-encoded JSON string literal.
  return api(`/api/kb-items/${itemId}/archive-request`, {
    method: "POST",
    body: {
      reason: body.reason,
      suggested_replacement_id: body.suggested_replacement_id ?? null,
    },
  });
}

// Phase B — file upload. Multipart, so we don't go through the
// JSON `api` helper. Browser sets Content-Type with boundary.
export async function uploadKbNote(
  projectId: string,
  input: { file: File; title?: string; scope?: KbNoteScope; folderId?: string },
): Promise<KbNote> {
  const fd = new FormData();
  fd.append("file", input.file);
  if (input.title) fd.append("title", input.title);
  if (input.scope) fd.append("scope", input.scope);
  if (input.folderId) fd.append("folder_id", input.folderId);
  const res = await fetch(
    `/api/projects/${projectId}/kb-items/upload`,
    { method: "POST", credentials: "include", body: fd, cache: "no-store" },
  );
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    throw new ApiError(res.status, body, `upload ${res.status}`);
  }
  return body as KbNote;
}

// Download URL for an attached file. Component can use as <a href>.
export function kbAttachmentUrl(itemId: string): string {
  return `/api/kb-items/${itemId}/attachment`;
}
