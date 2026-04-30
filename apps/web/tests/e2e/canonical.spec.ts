import { expect, test } from "@playwright/test";

import { intake, loginViaUi, rando, registerUser } from "./helpers";

// The canonical scenario — single user walks the demo path:
// register → login → land on projects list → create a project via intake
// → land on the per-project surface → graph detail tab → events stream.
//
// Navigation note (commit 1f23cd9 + projects/[id]/page.tsx:5):
// Per-project top tabs were deliberately removed in the chat-centered
// surface refactor. Navigation moved to the global left sidebar's
// "Detail" submenu (apps/web/src/components/shell/AppSidebar.tsx:319),
// which is collapsed by default. Detail subpages still exist at stable
// URLs (/projects/{id}/detail/{graph,plan,tasks,risks,decisions,events,
// conflicts,delivery,...}); only graph/plan/tasks/risks/decisions are
// surfaced in the sidebar. Events is reachable by URL only — no UI
// link — so we navigate directly. If the sidebar's Detail entries get
// further pruned, this spec needs another pass.

test.describe("canonical single-user flow", () => {
  test("register, intake, project surface, graph, events", async ({
    page,
    request,
  }) => {
    const user = await registerUser(request, { username: rando("canon") });
    await loginViaUi(page, user);

    const text =
      "Ship an event registration page in one week. Needs signup form, invite-code gate, and admin export.";
    const projectId = await intake(request, text);

    // The list page re-fetches on refresh. Refresh to see the project.
    await page.goto("/projects");
    await expect(
      page.getByRole("link", { name: /event registration/i }).first(),
    ).toBeVisible();

    // Open the per-project landing — chat-centered, renders the personal
    // stream for this user. We don't assert on stream content (that's a
    // separate spec); just that we landed on the project shell.
    await page.goto(`/projects/${projectId}`);
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/?$`));

    // Graph tab — direct URL navigation. The sidebar entry exists too
    // but is behind a collapsed "Detail" toggle; URL keeps the test
    // stable against sidebar UX iterations.
    await page.goto(`/projects/${projectId}/detail/graph`);
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/detail/graph$`));
    // Canvas must mount even if it's empty (real LLM fills it; stubs
    // may not produce graph entities). The .react-flow class is the
    // ReactFlow root container — it's always rendered, the nodes are
    // children if any.
    await expect(page.locator(".react-flow")).toBeVisible({ timeout: 15_000 });

    // Events tab — SSE connects. URL nav (no sidebar entry).
    await page.goto(`/projects/${projectId}/detail/events`);
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/detail/events$`));
    await expect(page.getByTestId("sse-status")).toHaveText("open", {
      timeout: 15_000,
    });
  });
});
