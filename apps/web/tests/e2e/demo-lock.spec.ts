import { expect, test } from "@playwright/test";

import { loginViaUi, rando, registerUser } from "./helpers";

// Phase 13 — demo-lock canonical fixture.
//
// The other specs walk the happy path through the UI directly. This one
// locks the demo to a single contract: `POST /api/demo/seed` produces a
// fully-delivered canonical project, and every demo-day surface (console
// shell, graph, delivery tab) renders it without further interaction.
//
// If anything about the canonical demo breaks, *this* spec should fail
// first — it has the least moving parts and the sharpest assertions.
//
// Budget: PLAN.md Phase 13 AC says the full live demo must fit in 7
// minutes. This spec only navigates seeded state (no LLM roundtrips),
// so we hold it to a tighter 90s for the whole spec — leaving cushion
// for the narration during the live demo.

const DEMO_BUDGET_MS = 90_000;

test.describe("phase 13 — canonical demo seed + UI lock", () => {
  test.setTimeout(DEMO_BUDGET_MS + 30_000); // fail the spec before Playwright's own timeout.

  test("seed endpoint drives a fully-delivered canonical project", async ({
    page,
    request,
  }) => {
    const started = Date.now();

    // A fresh user per run — the seed endpoint is idempotent-ish, but
    // collision-resistant usernames keep the SQLite file stable across
    // runs without a wipe.
    const user = await registerUser(request, { username: rando("demolock") });
    await loginViaUi(page, user);

    // Hit the seed endpoint. This walks intake → clarify → plan →
    // conflict decision → delivery server-side in one call.
    const seedRes = await request.post("/api/demo/seed", {
      data: { username: user.username, password: user.password },
    });
    expect(
      seedRes.ok(),
      `seed failed ${seedRes.status()}: ${await seedRes.text()}`,
    ).toBeTruthy();
    const seed = await seedRes.json();

    // Shape contract — if any of these drift, the Playwright spec
    // should fail, not silently skip the check.
    expect(seed.project_id).toBeTruthy();
    expect(seed.requirement_version).toBeGreaterThanOrEqual(2);
    expect(Array.isArray(seed.completed_scope_items)).toBeTruthy();
    expect(seed.completed_scope_items.length).toBeGreaterThan(0);
    expect(seed.elapsed_seconds).toBeGreaterThanOrEqual(0);

    const projectId: string = seed.project_id;

    // --- overview: the project shows up on /projects -----------------
    await page.goto("/projects");
    await expect(
      page.getByRole("link", { name: /event registration/i }).first(),
    ).toBeVisible();

    // --- project overview renders the seeded requirement -------------
    await page.goto(`/projects/${projectId}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/deliverables/i).first()).toBeVisible();

    // --- graph tab: the planned tasks render -------------------------
    await page.goto(`/projects/${projectId}/detail/graph`);
    await expect(page.locator(".react-flow")).toBeVisible({
      timeout: 15_000,
    });

    // --- delivery tab: the shipped summary renders -------------------
    await page.goto(`/projects/${projectId}/detail/delivery`);
    await expect(page.getByTestId("delivery-latest")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("delivery-headline")).not.toBeEmpty();
    await expect(page.getByTestId("completed-item").first()).toBeVisible();

    // --- health dashboard: agent runs are visible --------------------
    await page.goto("/health");
    await expect(page.getByTestId("health-panel")).toBeVisible();
    await expect(page.getByTestId("totals-card")).toBeVisible();

    const elapsed = Date.now() - started;
    expect(
      elapsed,
      `demo-lock walk took ${elapsed}ms, over ${DEMO_BUDGET_MS}ms budget`,
    ).toBeLessThan(DEMO_BUDGET_MS);
  });

});
