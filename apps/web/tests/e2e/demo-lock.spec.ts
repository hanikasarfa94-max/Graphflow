import { expect, test } from "@playwright/test";

import { apiRequest, loginViaUi, rando, registerUser } from "./helpers";

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
// minutes. The spec spends most of its time inside the seed walker,
// which makes ~17 sequential DeepSeek calls (intake parse → clarify
// gen → 3x clarify-reply re-parse → planning → ~12x conflict
// explanations → delivery). Measured 95–115s wall-clock against
// real DeepSeek with the prompt-cache warm. The 150s budget is the
// "if this exceeds, something has drifted seriously" guard, not the
// happy-path target. The original 90s was set when planning was
// short-circuited via stubs and conflict explanations didn't run
// per-rule; both costs are now real.
const DEMO_BUDGET_MS = 150_000;

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
    // conflict decision → delivery server-side in one call. With real
    // LLMs the walk takes ~90s; the Next.js dev-server proxy hangs up
    // around 30s for slow upstreams. Bypass the proxy and call the
    // FastAPI backend directly — see helpers.ts apiRequest() for the
    // full rationale.
    const api = await apiRequest();
    const seedRes = await api.post("/api/demo/seed", {
      data: { username: user.username, password: user.password },
      timeout: 120_000,
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
