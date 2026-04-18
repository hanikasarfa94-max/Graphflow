import { expect, type APIRequestContext, type Page } from "@playwright/test";

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
export async function intake(
  api: APIRequestContext,
  text: string,
): Promise<string> {
  const res = await api.post("/api/intake/message", {
    data: { text },
  });
  expect(res.ok(), `intake failed ${res.status()}`).toBeTruthy();
  const body = await res.json();
  // IntakeResult nests the project: { project: { id, ... }, requirement: ... }
  const projectId = body?.project?.id as string | undefined;
  expect(projectId, "intake response missing project.id").toBeTruthy();
  return projectId as string;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
