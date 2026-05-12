// AppShellV3 — server wrapper for the v0.6.2 shell.
//
// Mirrors AppShell.tsx but fetches the v0.6.2 data shape:
//   * session (same auth contract)
//   * scopes (project memberships, mapped to {id, title} — replaces the
//     project + DM + workspace + routed-inbox fetches that the legacy
//     shell did)
//
// Phase A.2 reuses GET /api/projects to source the scope list because
// /api/scopes is a Phase B addition. The mapping is trivial — project
// id → scope id, project title → scope title.
//
// Auth gating mirrors AppShell.tsx: if no session, render plain children
// so /login / /register continue to work without the shell.

import { cookies } from "next/headers";

import { ApiError, type ProjectSummary, type User } from "@/lib/api";

import { AppShellClientV3 } from "./AppShellClientV3";
import type { Scope } from "./ScopeBand";

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

async function fetchScopes(cookieHeader: string): Promise<Scope[]> {
  try {
    const res = await fetch(`${API_BASE}/api/projects`, {
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      cache: "no-store",
    });
    if (!res.ok) {
      // Tolerant: 401 means the session expired between auth/me and
      // here; let the children re-trigger requireUser to redirect.
      // Network failures also fall through with an empty scope list.
      return [];
    }
    const projects = (await res.json()) as ProjectSummary[];
    return projects.map((p) => ({ id: p.id, title: p.title }));
  } catch (err) {
    if (err instanceof ApiError) throw err;
    return [];
  }
}

export async function AppShellV3({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();

  const user = await fetchSession(cookieHeader);
  if (!user) {
    // Logged-out — render plain children. Page-level requireUser
    // handles the /login redirect.
    return <>{children}</>;
  }

  const scopes = await fetchScopes(cookieHeader);

  return (
    <AppShellClientV3 user={user} scopes={scopes}>
      {children}
    </AppShellClientV3>
  );
}
