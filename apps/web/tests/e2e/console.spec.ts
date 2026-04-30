import { expect, test } from "@playwright/test";

import { intake, loginViaUi, rando, registerUser } from "./helpers";

// New-user happy path through the chat-centered surface (rewrite of the
// Phase 11 console spec; the original tested an entry point — landing
// "Run canonical demo" button — that was removed when the public split
// landed in commit 8edc21d, and a `/console/[id]` surface that no
// longer carries the testids the old spec asserted on).
//
// Coverage now (the actual current happy path):
//   1. Logged-out user lands on `/` → public split + login form.
//   2. Register flow → lands on the home shell.
//   3. First project via intake API → renders in the project list.
//   4. Open the project → personal stream mounts and is interactive.
//   5. Status page renders members + active tasks panels.
//
// The aim is the same as the original spec: prove a brand-new user
// can walk to "in a project, ready to work" without any seed magic.

test.describe("new-user happy path", () => {
  test("anon → register → first project → personal stream", async ({
    page,
    request,
  }) => {
    // 1. Anonymous landing — public split + login form.
    await page.goto("/");
    await expect(
      page.getByRole("heading", {
        name: /Coordination as a graph,?/i,
      }),
    ).toBeVisible();

    // 2. Register via API (cheaper than typing the form), then login
    //    through the UI so the BROWSER context gets the session cookie
    //    too. registerUser only sets cookies on Playwright's
    //    APIRequestContext — not on the page's browser context.
    const user = await registerUser(request, { username: rando("happy") });
    await loginViaUi(page, user, "/");

    // Logged-in home renders the user's display name in the header
    // (and elsewhere, like a "your projects" / members panel — we
    // just need ONE occurrence to confirm we're authenticated).
    await expect(
      page.getByText(new RegExp(user.display_name)).first(),
    ).toBeVisible({ timeout: 10_000 });

    // 3. First project via intake API. Real LLM takes a few seconds.
    const projectId = await intake(
      request,
      "Ship a registration page next week with invite codes and admin export.",
    );

    // The project list re-fetches on navigation; visit it.
    await page.goto("/projects");
    await expect(
      page.getByRole("link", { name: /registration/i }).first(),
    ).toBeVisible();

    // 4. Project surface — chat-centered. Personal stream mounts.
    await page.goto(`/projects/${projectId}`);
    // The composer is the load-bearing affordance; if it's there, the
    // PersonalStream component mounted with auth + WS hooks intact.
    // Use the testid (stable across i18n + copy iterations) rather
    // than placeholder text.
    await expect(page.getByTestId("personal-composer")).toBeVisible({
      timeout: 15_000,
    });

    // 5. Status page renders the members + tasks panels.
    await page.goto(`/projects/${projectId}/status`);
    await expect(page.getByRole("heading", { name: /status/i })).toBeVisible();
    // The members panel is unconditional (creator joins as owner).
    // Username also appears in /home approvals/projects panels server-
    // rendered into the header — match any one with first().
    await expect(
      page.getByText(user.display_name).first(),
    ).toBeVisible();
  });
});
