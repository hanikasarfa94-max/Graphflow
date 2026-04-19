import { expect, test } from "@playwright/test";

import { intake, loginViaUi, rando, registerUser } from "./helpers";

// The canonical scenario — single user walks the demo path:
// register → login → land on projects list → create a project via intake
// → see it render in the overview → see the graph tab render nodes
// → see the events stream connect.

test.describe("canonical single-user flow", () => {
  test("register, intake, overview, graph, events", async ({ page, request }) => {
    const user = await registerUser(request, { username: rando("canon") });
    await loginViaUi(page, user);

    // We are on /projects. Use the intake composer to create a project.
    await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

    // The intake endpoint is faster than the UI (LLM may be stubbed),
    // and returns the project_id directly. Use the API so we can assert
    // on deterministic state.
    const text =
      "Ship an event registration page in one week. Needs signup form, invite-code gate, and admin export.";
    const projectId = await intake(request, text);

    // The list page re-fetches on refresh. Refresh to see the project.
    await page.goto("/projects");
    await expect(
      page.getByRole("link", { name: /event registration/i }).first(),
    ).toBeVisible();

    // Open the overview.
    await page.goto(`/projects/${projectId}`);
    await expect(
      page.getByRole("heading", { level: 1 }),
    ).toBeVisible();
    await expect(page.getByText(/deliverables/i).first()).toBeVisible();

    // Graph tab — React Flow renders nodes as .react-flow__node.
    await page.getByRole("link", { name: "Graph" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/detail/graph$`));
    // If the agent stack produced graph entities, nodes should render.
    // The canvas might be empty if running with a stubbed agent — accept
    // either state, but the canvas itself must be mounted.
    const canvas = page.locator(".react-flow");
    await expect(canvas).toBeVisible({ timeout: 15_000 });

    // Events tab — SSE connects. Status dot flips to `open`.
    await page.getByRole("link", { name: "Events" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/detail/events$`));
    // Status dot flips through connecting → open once SSE lands.
    await expect(page.getByTestId("sse-status")).toHaveText("open", {
      timeout: 15_000,
    });
  });
});
