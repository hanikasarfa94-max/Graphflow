import { expect, test } from "@playwright/test";

import { intake, loginViaUi, rando, registerUser } from "./helpers";

// Phase 8 + Phase 9 canonical coverage. A fresh plan with no assignments
// produces at least one `missing_owner` conflict. The user opens the
// Conflicts tab, submits a decision with rationale (Phase 9), and the
// decision history entry shows the outcome + rationale.

test.describe("conflicts tab + decision loop", () => {
  test("plan produces a conflict the user can decide with rationale", async ({
    page,
    request,
  }) => {
    const user = await registerUser(request, { username: rando("conf") });
    await loginViaUi(page, user);

    const projectId = await intake(
      request,
      "Launch an event signup page next week. Needs invite-code gate, phone validation, admin export.",
    );

    // Planning is the trigger for conflict detection. Fire it via API so
    // the test doesn't depend on the clarify UI.
    const planRes = await request.post(`/api/projects/${projectId}/plan`);
    expect(planRes.ok(), `plan failed ${planRes.status()}`).toBeTruthy();

    // The overview banner should flip on once detection lands. Detection
    // is kicked async after POST /plan returns, so poll.
    await page.goto(`/projects/${projectId}`);
    await expect(page.getByTestId("conflict-banner")).toBeVisible({
      timeout: 20_000,
    });

    // The nav badge mirrors the open count.
    await expect(
      page.getByRole("link", { name: /Conflicts/ }),
    ).toBeVisible();

    // Click through to the Conflicts tab.
    await page.getByRole("link", { name: /Conflicts/ }).click();
    await expect(page).toHaveURL(
      new RegExp(`/projects/${projectId}/detail/conflicts$`),
    );

    // WebSocket status flips to `open` once hub connects.
    await expect(page.getByTestId("conflict-summary")).toBeVisible({
      timeout: 15_000,
    });

    // At least one card must render.
    const firstCard = page.getByTestId("conflict-card").first();
    await expect(firstCard).toBeVisible({ timeout: 15_000 });

    // Explanation is best-effort; wait for at least one option to land so
    // the select button is clickable. If the LLM explanation doesn't
    // materialize within the window, take the custom-text path so we
    // still exercise the Phase 9 decision flow end-to-end.
    const selectBtn = firstCard.getByTestId("select-option-0");
    const customText = firstCard.getByTestId("custom-text");
    const rationale = firstCard.getByTestId("rationale");
    const submit = firstCard.getByTestId("submit-decision");

    const selectCount = await selectBtn.count();
    if (selectCount > 0) {
      await selectBtn.click();
    } else {
      await customText.fill("Split into two swimlanes so BE unblocks FE.");
    }
    await rationale.fill("Tight v1 scope; we will iterate after launch.");
    await submit.click();

    // Card flips to resolved and a decision-history entry appears with
    // the rationale text.
    await expect(firstCard).toHaveAttribute("data-status", "resolved", {
      timeout: 10_000,
    });
    const history = firstCard.getByTestId("decision-history");
    await expect(history).toBeVisible({ timeout: 10_000 });
    await expect(
      history.getByTestId("decision-entry").first(),
    ).toContainText(/Tight v1 scope/);
  });
});
