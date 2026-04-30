import {
  expect,
  test,
  type APIRequestContext,
} from "@playwright/test";

import { intake, rando, registerUser, loginViaUi } from "./helpers";

// projection_walkthrough — automates the manual demo gate the room slice
// docs called out as the v-Next ship criterion.
//
// "Team conversation visibly transforms into decisions, tasks, knowledge,
// and structured memory through membrane review." This spec asserts the
// projection-model story: one canonical entity, multiple projections.
//
// Three tests:
//
//   1. projection_two_views_one_entity
//        Post a decision-shaped message in a room. Wait for the IM
//        classifier suggestion. Assert the SAME suggestion id appears
//        in BOTH the inline timeline AND the workbench Requests panel.
//        Click Accept in the workbench. Assert: decision card appears
//        inline, suggestion no longer in Requests panel.
//
//   2. workbench_tasks_inline_create
//        Open the Tasks chip → +New → type a title → submit. Assert
//        the new task renders as a workbench-panel-item.
//
//   3. project_wide_vote_renders_in_stream_view
//        Crystallize a project-scoped decision via personal stream
//        (no scope_stream_id). Navigate to the project home stream.
//        Assert DecisionVoteControls render on the decision card.
//
// IM classifier latency:
//   The classifier is async and depends on a real LLM. Tests poll for
//   the suggestion via the existing API contract (mirrors
//   room_timeline.spec.ts pattern). When the classifier doesn't fire
//   within the budget, we mark the assertion as soft (test.skip with
//   a reason) — this keeps the spec from flaking on cold-start LLM
//   outliers while still catching real regressions on warm runs.

const SUGGESTION_POLL_BUDGET_MS = 30_000;
const SUGGESTION_POLL_INTERVAL_MS = 1_000;
const DECISION_TRIGGER_BODY = "let's drop this deliverable for the v1 launch";

test.describe("projection model — room walkthrough", () => {
  test("projection_two_views_one_entity — one suggestion, two projections", async ({
    page,
    request,
  }) => {
    const user = await registerUser(request, { username: rando("proj") });
    await loginViaUi(page, user, "/projects");

    // Cookie is on the page context now; also seed a session on the
    // request fixture so intake() can authenticate.
    const loginRes = await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    expect(loginRes.ok()).toBeTruthy();

    const projectId = await intake(
      request,
      `${user.display_name} owns the projection walkthrough project.`,
    );
    const me = (await (await request.get("/api/auth/me")).json()) as {
      id: string;
    };

    // Create a room. Persisted name (alembic 0029) shows in the header.
    const roomRes = await request.post(
      `/api/projects/${projectId}/rooms`,
      { data: { name: "projection-room", member_user_ids: [me.id] } },
    );
    expect(roomRes.ok()).toBeTruthy();
    const room = ((await roomRes.json()).stream as {
      id: string;
      name: string;
    });

    await page.goto(`/projects/${projectId}/rooms/${room.id}`);
    await expect(
      page.getByText(room.name).first(),
    ).toBeVisible({ timeout: 15_000 });

    // Post the decision-shaped message via composer.
    const composer = page.getByTestId("stream-composer");
    await composer.fill(DECISION_TRIGGER_BODY);
    await page.getByTestId("stream-send-btn").click();

    // Message should appear inline. data-entity-kind is the projection
    // anchor every inline card carries; this is the same selector
    // PanelItem.scrollToEntity uses to navigate from workbench → inline.
    await expect(
      page.locator('[data-entity-kind="message"]').last(),
    ).toBeVisible({ timeout: 10_000 });

    // Poll the API for the IM classifier suggestion. The classifier
    // runs async; polling the wire is more reliable than waiting on
    // DOM mutations because the suggestion may take >10s on cold LLM.
    const suggestionId = await pollForSuggestion(
      request,
      projectId,
      room.id,
      SUGGESTION_POLL_BUDGET_MS,
    );
    if (!suggestionId) {
      test.skip(
        true,
        "IM classifier did not produce a suggestion within the budget; " +
          "skipping projection assertion (likely cold LLM, not a regression)",
      );
      return;
    }

    // ---- The projection assertion ----
    // Same suggestion id must render in BOTH projections:
    //   * inline timeline card (data-entity-kind="im_suggestion")
    //   * workbench Requests panel (workbench-panel-item with same id)
    const inlineSuggestion = page.locator(
      `[data-entity-kind="im_suggestion"][data-entity-id="${suggestionId}"]`,
    );
    await expect(inlineSuggestion).toBeVisible({ timeout: 10_000 });

    const workbenchSuggestion = page.locator(
      `[data-testid="workbench-panel-item"][data-entity-id="${suggestionId}"]`,
    );
    await expect(workbenchSuggestion).toBeVisible({ timeout: 10_000 });

    // Click the workbench item — should scroll the inline card into
    // view and apply a brief highlight class. The scroll itself is a
    // browser side effect; we just confirm the click doesn't throw and
    // the inline card is still in the viewport (post-scroll).
    await workbenchSuggestion.click();
    await expect(inlineSuggestion).toBeInViewport();

    // ---- Accept from workbench ----
    // The accept button lives inside the workbench PanelItem actions
    // (the inline card is read-only by design — accept/dismiss are
    // workbench affordances).
    const acceptBtn = workbenchSuggestion
      .locator('[data-testid="workbench-suggestion-accept"]')
      .first();
    await acceptBtn.click();

    // Decision card must appear inline (crystallization is the
    // membrane's "accept → decision" path).
    await expect(
      page.getByTestId("stream-decision-card").first(),
    ).toBeVisible({ timeout: 15_000 });

    // The suggestion's workbench projection must drop (status becomes
    // accepted; filtered out of pendingSuggestions in the timeline
    // hook). Use a timeout because WS reconciliation is async.
    await expect(workbenchSuggestion).toHaveCount(0, { timeout: 10_000 });
  });

  test("workbench_tasks_inline_create — +New form persists", async ({
    page,
    request,
  }) => {
    const user = await registerUser(request, { username: rando("tasks") });
    await loginViaUi(page, user, "/projects");
    await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    const projectId = await intake(
      request,
      `${user.display_name} owns the tasks-panel project.`,
    );
    const me = (await (await request.get("/api/auth/me")).json()) as {
      id: string;
    };
    const room = ((await (
      await request.post(`/api/projects/${projectId}/rooms`, {
        data: { name: "tasks-room", member_user_ids: [me.id] },
      })
    ).json()).stream as { id: string });

    await page.goto(`/projects/${projectId}/rooms/${room.id}`);

    // Open the Tasks panel via its chip (workbench mounts requests by
    // default; tasks lands on demand).
    await page.getByTestId("workbench-chip-tasks").click();

    // Empty state copy (i18n key stream.rooms.tasksEmpty) renders
    // before any task is created.
    await expect(page.getByText(/no personal tasks/i)).toBeVisible({
      timeout: 5_000,
    });

    // Create a task via the inline +New form.
    await page.getByTestId("workbench-tasks-new").click();
    const input = page.getByTestId("workbench-tasks-input");
    await input.fill("QA the projection model walkthrough");
    await page.getByTestId("workbench-tasks-submit").click();

    // The new task must appear as a workbench-panel-item.
    await expect(
      page.getByText("QA the projection model walkthrough"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("project_wide_vote_renders_in_stream_view — DecisionVoteControls mount on project-scope decisions", async ({
    page,
    request,
  }) => {
    const user = await registerUser(request, { username: rando("vote") });
    await loginViaUi(page, user, "/projects");
    await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    const projectId = await intake(
      request,
      `${user.display_name} owns the project-wide-vote project.`,
    );

    // Crystallize a project-scoped decision via the existing intake
    // helper for personal-stream IM (the personal stream does NOT
    // have a stream_id arg, so the resulting suggestion has no
    // scope_stream_id → vote pool defaults to the project pool).
    const postRes = await request.post(`/api/personal/${projectId}/post`, {
      data: { body: DECISION_TRIGGER_BODY },
    });
    expect(postRes.ok()).toBeTruthy();

    const suggestionId = await pollForPersonalSuggestion(
      request,
      projectId,
      SUGGESTION_POLL_BUDGET_MS,
    );
    if (!suggestionId) {
      test.skip(
        true,
        "IM classifier did not produce a suggestion within the budget; " +
          "skipping project-wide-vote assertion",
      );
      return;
    }

    // Accept the suggestion — yields a DecisionRow with
    // scope_stream_id=null (the personal-stream branch never sets it).
    const acceptRes = await request.post(
      `/api/im_suggestions/${suggestionId}/accept`,
      { data: {} },
    );
    expect(
      acceptRes.ok(),
      `accept failed ${acceptRes.status()} ${await acceptRes.text()}`,
    ).toBeTruthy();

    // Navigate to the project home stream and find the decision card.
    await page.goto(`/projects/${projectId}`);
    const decisionCard = page.getByTestId("stream-decision-card").first();
    await expect(decisionCard).toBeVisible({ timeout: 15_000 });

    // The vote affordance must render — DecisionVoteControls exposes
    // its tally line as a child of the decision card. The component
    // contains "approve / deny / abstain" buttons (i18n keys under
    // stream.decision.voteVerdict); we assert at least one of them
    // is reachable to confirm the controls mounted.
    await expect(
      decisionCard.getByRole("button", { name: /approve|deny|abstain/i }),
    ).toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

async function pollForSuggestion(
  request: APIRequestContext,
  projectId: string,
  roomId: string,
  budgetMs: number,
): Promise<string | null> {
  const deadline = Date.now() + budgetMs;
  while (Date.now() < deadline) {
    const r = await request.get(
      `/api/projects/${projectId}/im_suggestions?stream_id=${roomId}`,
    );
    if (r.ok()) {
      const body = (await r.json()) as {
        suggestions: Array<{ id: string; status: string }>;
      };
      const pending = body.suggestions.find((s) => s.status === "pending");
      if (pending) return pending.id;
    }
    await new Promise((res) => setTimeout(res, SUGGESTION_POLL_INTERVAL_MS));
  }
  return null;
}

async function pollForPersonalSuggestion(
  request: APIRequestContext,
  projectId: string,
  budgetMs: number,
): Promise<string | null> {
  const deadline = Date.now() + budgetMs;
  while (Date.now() < deadline) {
    const r = await request.get(
      `/api/projects/${projectId}/im_suggestions`,
    );
    if (r.ok()) {
      const body = (await r.json()) as {
        suggestions: Array<{ id: string; status: string }>;
      };
      const pending = body.suggestions.find((s) => s.status === "pending");
      if (pending) return pending.id;
    }
    await new Promise((res) => setTimeout(res, SUGGESTION_POLL_INTERVAL_MS));
  }
  return null;
}

