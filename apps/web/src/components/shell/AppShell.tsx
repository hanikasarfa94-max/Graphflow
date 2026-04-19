// AppShell — Phase Q global layout wrapper.
//
// Wraps the app under NextIntlClientProvider. Decides at request time
// whether to render the full shell (sidebar + main) or plain children
// (auth pages, server errors). Authed users see the sidebar with project
// list + DM list + routed-inbox badge; logged-out users on /login or
// /register see nothing extra so the auth surface stays minimal.
//
// Auth detection reuses /api/auth/me (same endpoint as requireUser). When
// it 401s we render plain children — we do NOT redirect from here, page-
// level `requireUser` keeps ownership of redirects. This lets the root
// layout wrap the WHOLE app without breaking /login's own render.

import { cookies } from "next/headers";

import type {
  ProjectSummary,
  RoutingSignal,
  StreamSummary,
  User,
} from "@/lib/api";

import { AppShellClient, type ShellProject } from "./AppShellClient";

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

// A thin routing inbox preload used for the initial badge count. Drawer
// refetches on open to get the freshest state, but the first paint has
// an accurate number so the badge never lies about pending signals.
async function fetchInboxCount(cookieHeader: string): Promise<number> {
  const data = await fetchJson<{ signals: RoutingSignal[] }>(
    "/api/routing/inbox?status=pending&limit=200",
    cookieHeader,
    { signals: [] },
  );
  return data.signals.length;
}

export async function AppShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  // Single source of truth for "show shell or plain children": the
  // session cookie. If the user isn't authed — which covers /login,
  // /register, and any first-hit to an authed route before redirect
  // — we render plain children and let page-level `requireUser` handle
  // the redirect. If authed, we render the shell regardless of route.
  // (Next.js 15 doesn't expose the in-flight pathname via headers()
  // reliably, so we don't try to pathname-gate here.)
  const user = await fetchSession(cookieHeader);
  if (!user) {
    return <>{children}</>;
  }

  // Shell data — all tolerant of failures.
  const [projects, streamsResp, inboxCount] = await Promise.all([
    fetchJson<ProjectSummary[]>("/api/projects", cookieHeader, []),
    fetchJson<{ streams: StreamSummary[] }>(
      "/api/streams",
      cookieHeader,
      { streams: [] },
    ),
    fetchInboxCount(cookieHeader),
  ]);

  const streams = streamsResp.streams ?? [];
  const streamByProject = new Map<string, StreamSummary>();
  for (const s of streams) {
    if (s.type === "project" && s.project_id) {
      streamByProject.set(s.project_id, s);
    }
  }

  const shellProjects: ShellProject[] = projects.map((p) => {
    const s = streamByProject.get(p.id);
    return {
      id: p.id,
      title: p.title,
      unread_count: s?.unread_count ?? 0,
      last_activity_at: s?.last_activity_at ?? p.updated_at ?? null,
    };
  });
  shellProjects.sort((a, b) => {
    const at = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
    const bt = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
    return bt - at;
  });

  const dmSummaries = streams
    .filter((s) => s.type === "dm")
    .map((s) => {
      const other = s.members.find((m) => m.user_id !== user.id);
      return {
        stream_id: s.id,
        other_user_id: other?.user_id ?? "",
        other_display_name:
          other?.display_name ?? other?.username ?? "(unknown)",
        other_username: other?.username ?? "",
        last_activity_at: s.last_activity_at,
        unread_count: s.unread_count,
      };
    })
    .sort((a, b) => {
      const at = a.last_activity_at ? new Date(a.last_activity_at).getTime() : 0;
      const bt = b.last_activity_at ? new Date(b.last_activity_at).getTime() : 0;
      return bt - at;
    });

  return (
    <AppShellClient
      user={user}
      projects={shellProjects}
      dms={dmSummaries}
      initialInboxCount={inboxCount}
    >
      {children}
    </AppShellClient>
  );
}
