// v-next AppShell — single global shell per docs/shell-v-next.txt.
//
// Mirrors the existing apps/web/src/components/shell/AppShell.tsx data
// fetch (auth detection + projects + streams + workspaces + inbox count)
// but hands off to <AppShellVNextClient> which renders the prototype-
// faithful 4-column grid (Rail | ImNav | Main | Workbench) instead of
// the projects-as-primary-nav AppSidebar.
//
// Mount-point: apps/web/src/app/layout.tsx switches between this and
// the legacy AppShell based on the SHELL_VNEXT env var. Old shell stays
// the default during transition (per spec §7 "do not delete").

import { cookies } from "next/headers";

import type {
  ProjectSummary,
  RoutingSignal,
  StreamSummary,
  User,
} from "@/lib/api";

import { AppShellVNextClient } from "./AppShellClient";
import type {
  ShellGroupItem,
  ShellDMItem,
  ShellPersonalAgent,
  ShellWorkspace,
} from "./types";

const API_BASE =
  process.env.WORKGRAPH_API_BASE_SERVER ??
  process.env.WORKGRAPH_API_BASE ??
  "http://127.0.0.1:8000";

async function fetchSession(cookieHeader: string): Promise<User | null> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as User;
  } catch {
    return null;
  }
}

async function fetchJson<T>(
  path: string,
  cookieHeader: string,
  fallback: T,
): Promise<T> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

async function fetchInboxCount(cookieHeader: string): Promise<number> {
  const [routed, gated] = await Promise.all([
    fetchJson<{ signals: RoutingSignal[] }>(
      "/api/routing/inbox?status=pending&limit=200",
      cookieHeader,
      { signals: [] },
    ),
    fetchJson<{ items: unknown[] }>(
      "/api/inbox/gated?limit=200",
      cookieHeader,
      { items: [] },
    ),
  ]);
  return routed.signals.length + gated.items.length;
}

export async function AppShellVNext({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  const user = await fetchSession(cookieHeader);
  if (!user) {
    return <>{children}</>;
  }

  const [projects, streamsResp, inboxCount, workspaces] = await Promise.all([
    fetchJson<ProjectSummary[]>("/api/projects", cookieHeader, []),
    fetchJson<{ streams: StreamSummary[] }>(
      "/api/streams",
      cookieHeader,
      { streams: [] },
    ),
    fetchInboxCount(cookieHeader),
    fetchJson<Array<{
      id: string;
      name: string;
      slug: string;
      role: string;
    }>>("/api/organizations", cookieHeader, []),
  ]);

  const streams = streamsResp.streams ?? [];

  // Partition streams into the four ImNav buckets per docs/shell-v-next.txt §2.
  //
  //   通用 Agent       — kind='personal' AND project_id=null AND owner=me
  //   项目 Agent rows  — kind='personal' AND project_id!=null AND owner=me
  //   群组             — kind IN ('project','room')
  //   私聊             — kind='dm'
  //
  // last_activity_at sort happens here (Q-D answer: recency only,
  // no search input as primary affordance).

  let generalAgent: ShellPersonalAgent | null = null;
  const projectAgents: ShellPersonalAgent[] = [];
  const groups: ShellGroupItem[] = [];
  const dms: ShellDMItem[] = [];

  // Project title lookup so we can format "<title> 的 Agent" labels.
  // BE returns display_name resolved server-side (E-3); fallback to
  // local map for any miss.
  const projectTitleById = new Map<string, string>();
  for (const p of projects) projectTitleById.set(p.id, p.title);

  for (const s of streams) {
    if (s.type === "personal" && s.owner_user_id === user.id) {
      const item: ShellPersonalAgent = {
        stream_id: s.id,
        project_id: s.project_id,
        // For project agents the BE returns the project title as
        // display_name; the FE adds "的 Agent" via i18n.
        // For the global agent display_name is null and the FE shows
        // a localized "通用 Agent" label.
        anchor_name:
          s.display_name ??
          (s.project_id ? projectTitleById.get(s.project_id) ?? "" : ""),
        last_activity_at: s.last_activity_at,
        unread_count: s.unread_count,
      };
      if (s.project_id === null) {
        generalAgent = item;
      } else {
        projectAgents.push(item);
      }
    } else if (s.type === "project" || s.type === "room") {
      groups.push({
        stream_id: s.id,
        kind: s.type,
        project_id: s.project_id,
        // For groups the BE display_name is project.title (project
        // streams) or stream.name (named rooms) or project.title
        // (unnamed rooms — Q-E fallback).
        display_name:
          s.display_name ??
          (s.project_id ? projectTitleById.get(s.project_id) ?? null : null),
        last_activity_at: s.last_activity_at,
        unread_count: s.unread_count,
        member_count: s.members.length,
      });
    } else if (s.type === "dm") {
      const other = s.members.find((m) => m.user_id !== user.id);
      dms.push({
        stream_id: s.id,
        other_user_id: other?.user_id ?? "",
        other_display_name:
          other?.display_name ?? other?.username ?? "(unknown)",
        other_username: other?.username ?? "",
        last_activity_at: s.last_activity_at,
        unread_count: s.unread_count,
      });
    }
  }

  // Recency sort within each bucket (Q-D).
  const byRecency = (a: { last_activity_at: string | null }, b: typeof a) => {
    const at = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
    const bt = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
    return bt - at;
  };
  projectAgents.sort(byRecency);
  groups.sort(byRecency);
  dms.sort(byRecency);

  const shellWorkspaces: ShellWorkspace[] = workspaces.map((w) => ({
    id: w.id,
    name: w.name,
    slug: w.slug,
    role: w.role,
  }));

  return (
    <AppShellVNextClient
      user={user}
      generalAgent={generalAgent}
      projectAgents={projectAgents}
      groups={groups}
      dms={dms}
      initialInboxCount={inboxCount}
      workspaces={shellWorkspaces}
    >
      {children}
    </AppShellVNextClient>
  );
}
