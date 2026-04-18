import { expect, test } from "@playwright/test";

import { loginViaUi, rando, registerUser } from "./helpers";

// Phase 11 canonical coverage. Landing → Run canonical demo → console
// shell renders → graph sidebar visible → stage auto-follows → user runs
// the planner → delivery summary generates → state is readable without
// poking DB.

test.describe("landing + console shell", () => {
  test("landing demo button drives the console end-to-end", async ({
    page,
    request,
  }) => {
    // Register + log in. The landing demo button itself also registers
    // for fresh anon users via /login redirect, but tests need a stable
    // session so we log in deliberately.
    const user = await registerUser(request, { username: rando("console") });
    await loginViaUi(page, user, "/");

    await expect(
      page.getByRole("heading", {
        name: /Coordination as a graph, not a document/,
      }),
    ).toBeVisible();

    const demoButton = page.getByTestId("run-canonical-demo");
    await expect(demoButton).toBeVisible();
    await demoButton.click();

    // Navigates to /console/{project_id}
    await expect(page).toHaveURL(/\/console\/[^/]+/, { timeout: 20_000 });
    await expect(page.getByTestId("console-shell")).toBeVisible();
    await expect(page.getByTestId("console-graph-sidebar")).toBeVisible();
    await expect(page.getByTestId("stage-label")).toBeVisible();
    await expect(page.getByTestId("graph-river")).toBeVisible();

    // Fresh intake with stub agents → we land in intake/clarify stage.
    const stage = (await page.getByTestId("stage-label").innerText()).trim();
    expect(["intake", "clarify"]).toContain(stage);

    // If there are clarifications, canvas renders messages. Otherwise it
    // offers "Run planner". Either path moves forward.
    const runPlanner = page.getByTestId("run-planner");
    const answerBtn = page.getByTestId("answer-1");
    if (await runPlanner.count()) {
      await runPlanner.click();
    } else if (await answerBtn.count()) {
      // Answer the first clarification so we can progress.
      await answerBtn.click();
      await page.getByTestId("answer-input").fill("Yes, proceed.");
      await page.getByTestId("submit-answer").click();
    }

    // Stage should flip off intake/clarify within the timeout.
    await expect
      .poll(
        async () =>
          (await page.getByTestId("stage-label").innerText()).trim(),
        { timeout: 25_000 },
      )
      .not.toMatch(/^(intake|clarify)$/);

    // Agent-log drawer toggle works.
    await page.getByTestId("toggle-agent-log").click();
    await expect(page.getByTestId("agent-log-drawer")).toHaveAttribute(
      "aria-hidden",
      "false",
    );
  });
});
