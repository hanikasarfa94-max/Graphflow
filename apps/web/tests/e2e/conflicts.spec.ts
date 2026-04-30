import { expect, test } from "@playwright/test";

import { apiRequest, intake, loginViaUi, rando, registerUser } from "./helpers";

// Phase 8 + Phase 9 canonical coverage. A fresh plan with no assignments
// produces at least one conflict; the user opens the Conflicts page,
// submits a decision with rationale, and the decision history entry
// shows the outcome + rationale.
//
// Navigation note: the project overview page (with conflict-banner +
// "Conflicts" sidebar link) was removed in the chat-centered surface
// refactor (commit 1f23cd9, projects/[id]/page.tsx:5). The /detail/
// conflicts page still exists at a stable URL and is the load-bearing
// surface. The conflict-banner testid is also gone — that overview
// surface no longer exists, and there's no UI entry point to conflicts
// from the sidebar's Detail submenu (which is graph/plan/tasks/risks/
// decisions only). We navigate by URL and assert on the decide loop,
// which is the actual product value.

test.describe("conflicts decision loop", () => {
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

    // Planning is the trigger for conflict detection. Real LLM takes
    // ~20s; bypass the dev-server proxy timeout (helpers.ts apiRequest).
    const api = await apiRequest();
    const planRes = await api.post(`/api/projects/${projectId}/plan`, {
      timeout: 60_000,
    });
    expect(planRes.ok(), `plan failed ${planRes.status()}`).toBeTruthy();

    // Detection is kicked async after POST /plan returns. Navigate to
    // the conflicts page directly; the page polls for state.
    await page.goto(`/projects/${projectId}/detail/conflicts`);
    await expect(page).toHaveURL(
      new RegExp(`/projects/${projectId}/detail/conflicts$`),
    );

    // Summary mounts once the page reads conflict state.
    await expect(page.getByTestId("conflict-summary")).toBeVisible({
      timeout: 20_000,
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
