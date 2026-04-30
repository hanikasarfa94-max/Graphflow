import {
  expect,
  request as pwRequest,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

// Tests use TWO different request contexts deliberately:
//
//   * `request` (the standard Playwright fixture) — points at
//     baseURL=http://127.0.0.1:3100 (the web). Used when we want to
//     exercise what a browser actually sees: the Next.js dev-server
//     proxies /api/* to the FastAPI backend via `rewrites()` in
//     next.config.mjs. That same-origin path is what production
//     browsers use (cookies need same-origin to flow), so testing
//     through it catches real proxy bugs.
//
//   * `apiRequest()` — points DIRECTLY at the FastAPI backend on
//     :8100. Used for long-running setup calls (seed walker, plan
//     generation with real LLM ≥ 30s) where the Next.js dev-server
//     proxy intermittently hangs up the socket on slow upstreams
//     (we measured ECONNRESET around 30s on real-LLM POSTs to
//     /api/demo/seed). That hang-up reproduces in dev only because
//     the dev-server proxy uses a different code path than the
//     standalone production server. The right place to fix it is the
//     dev-server config, but tests shouldn't be blocked on that —
//     production traffic doesn't go through `next dev`.
//
// Use the standard `request` for anything that asserts a UI-reachable
// flow (intake, login, suggestions) so the proxy stays under test.
// Use `apiRequest` for setup-only calls that don't matter for
// browser-shaped coverage.
const API_BASE_URL =
  process.env.WORKGRAPH_E2E_API_BASE ?? "http://127.0.0.1:8100";

export async function apiRequest(): Promise<APIRequestContext> {
  return pwRequest.newContext({ baseURL: API_BASE_URL });
}

// Generate a collision-resistant username per test so the SQLite database
// can be reused across runs without uniqueness headaches.
export function rando(prefix = "user"): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

export async function registerUser(
  api: APIRequestContext,
  opts: { username: string; password?: string; displayName?: string } = {
    username: rando(),
  },
): Promise<{ username: string; password: string; display_name: string }> {
  const password = opts.password ?? "hunter22hunter22";
  const display_name = opts.displayName ?? opts.username;
  const res = await api.post("/api/auth/register", {
    data: {
      username: opts.username,
      password,
      display_name,
    },
  });
  expect(res.ok(), `register failed ${res.status()}`).toBeTruthy();
  return { username: opts.username, password, display_name };
}

// Log in via the public form so the browser ends up with the session
// cookie. `page.goto("/login")` is the only way to guarantee the cookie
// gets stored on the correct origin.
export async function loginViaUi(
  page: Page,
  creds: { username: string; password: string },
  next = "/projects",
): Promise<void> {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Username").fill(creds.username);
  await page.getByLabel("Password").fill(creds.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(new RegExp(escapeRegExp(next)));
}

// Helper for creating a project via the intake endpoint. Returns the
// project_id so tests can navigate to /projects/{id}.
//
// Caller passes the standard `request` fixture; we copy the cookie
// jar onto the direct-API context so the post still authenticates as
// the same user. This keeps intake (real-LLM, ~3s) off the dev-server
// proxy timeout window — see apiRequest() docs.
export async function intake(
  api: APIRequestContext,
  text: string,
): Promise<string> {
  const cookies = await api.storageState();
  const direct = await pwRequest.newContext({
    baseURL: API_BASE_URL,
    storageState: cookies,
  });
  try {
    const res = await direct.post("/api/intake/message", {
      data: { text },
      timeout: 60_000,
    });
    expect(res.ok(), `intake failed ${res.status()}`).toBeTruthy();
    const body = await res.json();
    const projectId = body?.project?.id as string | undefined;
    expect(projectId, "intake response missing project.id").toBeTruthy();
    return projectId as string;
  } finally {
    await direct.dispose();
  }
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
