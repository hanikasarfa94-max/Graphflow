import { expect, test } from "@playwright/test";

import { intake, rando, registerUser } from "./helpers";

// Per-item license override — owner-only PUT that clamps a single KB
// item to a tighter tier than the project default. Historically a
// regression magnet because the override interacts with the visibility
// gate at multiple read sites.
//
// Asserts:
//   1. PUT with a valid tier writes the override and the GET reflects it
//   2. PUT with null clears the override (back to project tier)
//   3. Non-owner PUT returns 403

test.describe("kb item license override", () => {
  test("owner sets, clears, non-owner blocked", async ({ request }) => {
    const owner = await registerUser(request, { username: rando("licO") });
    const loginRes = await request.post("/api/auth/login", {
      data: { username: owner.username, password: owner.password },
    });
    expect(loginRes.ok(), "owner login failed").toBeTruthy();

    const projectId = await intake(
      request,
      `Maintain a customer-facing FAQ. ${owner.display_name} owns docs.`,
    );

    // Create a group-scope KB item.
    const itemRes = await request.post(
      `/api/projects/${projectId}/kb-items`,
      {
        data: {
          title: `playbook-${Date.now()}`,
          content_md: "Step 1: ...",
          scope: "group",
        },
      },
    );
    expect(
      itemRes.ok(),
      `create item failed ${itemRes.status()} ${await itemRes.text()}`,
    ).toBeTruthy();
    const itemId = (await itemRes.json())?.id as string;
    expect(itemId).toBeTruthy();

    // Tree initially has license_tier_override === null for this item.
    const before = await request.get(`/api/projects/${projectId}/kb/tree`);
    const beforeTree = await before.json();
    const beforeItem = (beforeTree?.items ?? []).find(
      (i: any) => i.id === itemId,
    );
    expect(beforeItem, "item not in tree").toBeTruthy();
    expect(beforeItem.license_tier_override).toBeNull();

    // Owner sets override.
    const setRes = await request.put(
      `/api/projects/${projectId}/kb/items/${itemId}/license`,
      { data: { license_tier: "observer" } },
    );
    expect(
      setRes.ok(),
      `set license failed ${setRes.status()} ${await setRes.text()}`,
    ).toBeTruthy();

    const after = await request.get(`/api/projects/${projectId}/kb/tree`);
    const afterTree = await after.json();
    const afterItem = (afterTree?.items ?? []).find(
      (i: any) => i.id === itemId,
    );
    expect(afterItem.license_tier_override).toBe("observer");

    // Owner clears.
    const clearRes = await request.put(
      `/api/projects/${projectId}/kb/items/${itemId}/license`,
      { data: { license_tier: null } },
    );
    expect(
      clearRes.ok(),
      `clear license failed ${clearRes.status()} ${await clearRes.text()}`,
    ).toBeTruthy();

    const cleared = await request.get(`/api/projects/${projectId}/kb/tree`);
    const clearedTree = await cleared.json();
    const clearedItem = (clearedTree?.items ?? []).find(
      (i: any) => i.id === itemId,
    );
    expect(clearedItem.license_tier_override).toBeNull();

    // Non-owner is forbidden. Register a second user (this also logs
    // them in and clobbers our owner cookie), then re-login as owner
    // to send the invite, then switch back to member to attempt PUT.
    const member = await registerUser(request, { username: rando("licM") });
    const ownerReLogin = await request.post("/api/auth/login", {
      data: { username: owner.username, password: owner.password },
    });
    expect(ownerReLogin.ok(), "owner re-login failed").toBeTruthy();

    const inviteRes = await request.post(
      `/api/projects/${projectId}/invite`,
      { data: { username: member.username } },
    );
    expect(
      inviteRes.ok(),
      `invite failed ${inviteRes.status()} ${await inviteRes.text()}`,
    ).toBeTruthy();

    // Switch to member session in the same request context.
    const memberLogin = await request.post("/api/auth/login", {
      data: { username: member.username, password: member.password },
    });
    expect(memberLogin.ok(), "member login failed").toBeTruthy();

    const forbidden = await request.put(
      `/api/projects/${projectId}/kb/items/${itemId}/license`,
      { data: { license_tier: "task_scoped" } },
    );
    expect(forbidden.status()).toBe(403);
  });
});
