// v-next shell types — partition shapes for the ImNav buckets.
//
// The server-side AppShell partitions the raw GET /api/streams response
// into these four buckets before passing to the client. This keeps the
// client simple (no filter/partition logic inline) and means the same
// shapes can be reused by useStreamList if we ever need a client-side
// refresh hook (Phase 2; today the shell re-renders on route change so
// the server fetch is sufficient).

export interface ShellPersonalAgent {
  stream_id: string;
  // null for the 通用 (global) agent; set for 项目 Agent rows.
  project_id: string | null;
  // BE returns display_name resolved as ProjectRow.title for project
  // agents, null for the global agent. FE adds the "的 Agent" suffix
  // via i18n + leaves global agent label as a localized constant.
  anchor_name: string;
  last_activity_at: string | null;
  unread_count: number;
}

export interface ShellGroupItem {
  stream_id: string;
  // 'project' = project main room (kind='project')
  // 'room'    = sub-team / topical / ad-hoc room
  // The ImNav surfaces them flat as one 群组 list (spec §2).
  kind: "project" | "room";
  project_id: string | null;
  // Resolved server-side per Q-E. May still be null if neither
  // stream.name nor project.title is available; FE falls back to
  // a localized placeholder.
  display_name: string | null;
  last_activity_at: string | null;
  unread_count: number;
  member_count: number;
}

export interface ShellDMItem {
  stream_id: string;
  other_user_id: string;
  other_display_name: string;
  other_username: string;
  last_activity_at: string | null;
  unread_count: number;
}

export interface ShellWorkspace {
  id: string;
  name: string;
  slug: string;
  role: string;
}
