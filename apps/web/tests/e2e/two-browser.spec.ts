import { expect, test } from "@playwright/test";

import { loginViaUi, rando, registerUser } from "./helpers";

// Two-browser realtime test — the core claim of Phase 7'':
// user B's browser sees user A's message (and its IM suggestion) live via
// WebSocket, without reloading. Uses two independent browser contexts so
// cookies don't leak between the sessions.

test.describe("two-browser realtime fanout", () => {
  test("user B sees user A's message over WebSocket", async ({
    browser,
    request,
  }) => {
    // Register both users up-front (bare request ctx — anonymous register).
    const userA = await registerUser(request, { username: rando("a") });
    const userB = await registerUser(request, { username: rando("b") });

    // A's browser context — login first so ctxA.request carries A's cookie.
    const ctxA = await browser.newContext();
    const pageA = await ctxA.newPage();
    await loginViaUi(pageA, userA, `/projects`);

    // Intake via A's authenticated request context. The intake service binds
    // the creator (A) as a project member via bind_creator, so A can invite.
    const intakeRes = await ctxA.request.post("/api/intake/message", {
      data: {
        text: `Build a signup page; two devs collaborate. ${userA.username} owns FE, ${userB.username} owns BE.`,
      },
    });
    expect(intakeRes.ok(), `intake failed ${intakeRes.status()}`).toBeTruthy();
    const intakeBody = await intakeRes.json();
    const projectId = intakeBody?.project?.id as string | undefined;
    expect(projectId, "intake response missing project.id").toBeTruthy();

    // Invite B. The layout loader relies on membership, so B must be
    // a member before their browser loads the project.
    const inviteRes = await ctxA.request.post(
      `/api/projects/${projectId}/invite`,
      { data: { username: userB.username } },
    );
    expect(inviteRes.ok(), `invite failed ${inviteRes.status()}`).toBeTruthy();

    // B opens the chat tab in a separate browser context.
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    await loginViaUi(pageB, userB, `/projects/${projectId}/im`);

    // Wait for B's WebSocket to land (status dot flips to `open`).
    await expect(pageB.getByTestId("ws-status")).toHaveText("open", {
      timeout: 15_000,
    });

    // A navigates to the chat tab and sends a message.
    await pageA.goto(`/projects/${projectId}/im`);
    await expect(pageA.getByTestId("ws-status")).toHaveText("open", {
      timeout: 15_000,
    });

    const marker = `hello-from-A-${Date.now().toString(36)}`;
    await pageA
      .getByPlaceholder(/Send a message/i)
      .fill(`${marker} — ping @${userB.username}`);
    await pageA.getByRole("button", { name: "Send" }).click();

    // B must see the marker within a few seconds, without reloading.
    await expect(pageB.getByText(marker)).toBeVisible({ timeout: 10_000 });

    // And B sees A's display name above the bubble (WS payload carried
    // author metadata, not just the id).
    await expect(pageB.getByText(userA.display_name).first()).toBeVisible();

    await ctxA.close();
    await ctxB.close();
  });
});
