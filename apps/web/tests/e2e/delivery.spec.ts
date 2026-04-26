import { expect, test } from "@playwright/test";

import { apiRequest, intake, loginViaUi, rando, registerUser } from "./helpers";

// Phase 10 canonical coverage. After intake + plan, the user opens the
// Delivery tab, clicks Generate, and sees a rendered summary: headline,
// every scope item covered, regeneration history after a second click.

test.describe("delivery tab", () => {
  test("generates a summary citing scope items", async ({ page, request }) => {
    const user = await registerUser(request, { username: rando("dlv") });
    await loginViaUi(page, user);

    const projectId = await intake(
      request,
      "Launch an event signup page next week. Needs invite-code gate, phone validation, admin export.",
    );

    // Real-LLM planning takes ~20s; bypass the dev-server proxy that
    // hangs up on slow upstreams (see helpers.ts apiRequest).
    const api = await apiRequest();
    const planRes = await api.post(`/api/projects/${projectId}/plan`, {
      timeout: 60_000,
    });
    expect(planRes.ok(), `plan failed ${planRes.status()}`).toBeTruthy();

    await page.goto(`/projects/${projectId}/detail/delivery`);
    await expect(page.getByTestId("delivery-pane")).toBeVisible();
    await expect(page.getByTestId("delivery-empty")).toBeVisible();

    await page.getByTestId("generate-delivery").click();

    await expect(page.getByTestId("delivery-latest")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId("delivery-headline")).not.toBeEmpty();
    await expect(page.getByTestId("delivery-outcome")).toBeVisible();
    await expect(page.getByTestId("delivery-completed")).toBeVisible();
    await expect(page.getByTestId("completed-item").first()).toBeVisible();

    // Regenerate — second snapshot should push the history block into view.
    await page.getByTestId("generate-delivery").click();
    await expect(page.getByTestId("delivery-history")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId("history-row")).toHaveCount(2);
  });
});
