import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiError, type User } from "./api";

// WORKGRAPH_API_BASE_SERVER lets Docker point at the internal container name
// (e.g. http://api:8000) while the browser-facing rewrites use the public
// origin. In dev + E2E, only WORKGRAPH_API_BASE is set, so fall through.
const API_BASE =
  process.env.WORKGRAPH_API_BASE_SERVER ??
  process.env.WORKGRAPH_API_BASE ??
  "http://127.0.0.1:8000";

// Server-side session check. Forwards the browser's cookie to the FastAPI
// backend and redirects to /login on 401. Used by every authenticated
// server component.
export async function requireUser(nextPath?: string): Promise<User> {
  const cookieHeader = (await cookies()).toString();
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    cache: "no-store",
  });
  if (res.status === 401) {
    const target = nextPath ? `/login?next=${encodeURIComponent(nextPath)}` : "/login";
    redirect(target);
  }
  if (!res.ok) {
    throw new ApiError(res.status, null, `auth/me ${res.status}`);
  }
  return (await res.json()) as User;
}

// Server-side fetch that forwards the session cookie. Returns null on 404
// so pages can render a "not found" state without throwing.
export async function serverFetch<T>(path: string): Promise<T> {
  const cookieHeader = (await cookies()).toString();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    cache: "no-store",
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body, `api ${res.status} on ${path}`);
  return body as T;
}
