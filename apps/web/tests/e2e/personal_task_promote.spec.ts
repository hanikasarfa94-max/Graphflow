import { expect, test } from "@playwright/test";

import { intake, loginViaUi, rando, registerUser } from "./helpers";

// Phase T+1 — personal task → promote → membrane review → owner accept.
//
// Two paths covered:
//   1. Auto-merge: novel title → promote returns task with scope='plan'.
//   2. Request_review (duplicate title against existing plan task) →
//      promote returns deferred=true; an IMSuggestion(membrane_review)
//      with detail.candidate_kind='task_promote' lands in the team room;
//      a project owner accepting it via /api/im_suggestions/{id}/accept
//      flips the personal task to plan-scope.
//
// The accept-handler path is the regression cover for the
// 'missing_kb_item_id' bug where the membrane_review apply branch
// only knew kb_item_id and would error on task_promote candidates.

test.describe("personal task promote via membrane", () => {
  test("novel-title promote auto-merges into plan", async ({ request }) => {
    const user = await registerUser(request, { username: rando("ptpa") });
    const ctx = await request.storageState();
    void ctx; // request keeps cookies in-process; loginViaUi not needed for API tests
    // Actually we need to authenticate the request context. The
    // existing helpers use registerUser then UI login; for an API-only
    // spec, log in via the API form so the request context's cookie
    // jar carries the session.
    const loginRes = await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    expect(loginRes.ok(), "api login failed").toBeTruthy();

    const projectId = await intake(
      request,
      `Build a quick service in two weeks. ${user.display_name} owns it.`,
    );

    // Create a personal task.
    const createRes = await request.post(
      `/api/projects/${projectId}/tasks`,
      { data: { title: `unique-${Date.now()}` } },
    );
    expect(createRes.ok(), "create personal task failed").toBeTruthy();
    const created = await createRes.json();
    const taskId = created?.task?.id as string;
    expect(taskId).toBeTruthy();
    expect(created?.task?.scope).toBe("personal");

    // Promote — no title collision, expect auto-merge → plan.
    const promoteRes = await request.post(`/api/tasks/${taskId}/promote`);
    expect(promoteRes.ok(), "promote failed").toBeTruthy();
    const promoted = await promoteRes.json();
    expect(promoted?.deferred).toBeFalsy();
    expect(promoted?.task?.scope).toBe("plan");
    expect(promoted?.task?.requirement_id).toBeTruthy();
  });

  test("duplicate-title promote defers, owner accept flips to plan", async ({
    browser,
    request,
  }) => {
    // Two users so the proposer can be a non-owner member; the project
    // owner does the accept. Mirrors the realistic crowd-curation flow.
    const owner = await registerUser(request, { username: rando("ptpO") });
    const member = await registerUser(request, { username: rando("ptpM") });

    // Owner intakes, then invites the member.
    const ownerCtx = await browser.newContext();
    const ownerPage = await ownerCtx.newPage();
    await loginViaUi(ownerPage, owner, "/projects");
    const intakeRes = await ownerCtx.request.post("/api/intake/message", {
      data: {
        text: `Ship a checkout flow next sprint. ${owner.display_name} leads.`,
      },
    });
    expect(intakeRes.ok(), `intake failed ${intakeRes.status()}`).toBeTruthy();
    const projectId = ((await intakeRes.json())?.project?.id as string) ?? "";
    expect(projectId).toBeTruthy();

    const inviteRes = await ownerCtx.request.post(
      `/api/projects/${projectId}/invite`,
      { data: { username: member.username } },
    );
    expect(inviteRes.ok(), `invite failed ${inviteRes.status()}`).toBeTruthy();

    // Owner pre-creates a plan-scope task by promoting their own
    // personal task. (No direct "create plan task" endpoint — this is
    // the canonical way to seed a plan task in this test.)
    const seedTitle = `seed-checkout-${Date.now().toString(36)}`;
    const seedCreate = await ownerCtx.request.post(
      `/api/projects/${projectId}/tasks`,
      { data: { title: seedTitle } },
    );
    const seedId = (await seedCreate.json())?.task?.id as string;
    const seedPromote = await ownerCtx.request.post(
      `/api/tasks/${seedId}/promote`,
    );
    expect(seedPromote.ok(), "seed promote failed").toBeTruthy();
    expect((await seedPromote.json())?.task?.scope).toBe("plan");

    // Member creates + promotes a personal task with the SAME title.
    // Expect deferred=true (membrane request_review on dup title).
    const memberCtx = await browser.newContext();
    await loginViaUi(await memberCtx.newPage(), member, "/projects");
    const memberCreate = await memberCtx.request.post(
      `/api/projects/${projectId}/tasks`,
      { data: { title: seedTitle.toUpperCase() } }, // normalized → same
    );
    const memberTaskId = (await memberCreate.json())?.task?.id as string;
    expect(memberTaskId).toBeTruthy();

    const memberPromote = await memberCtx.request.post(
      `/api/tasks/${memberTaskId}/promote`,
    );
    expect(memberPromote.ok(), "member promote failed").toBeTruthy();
    const promotedBody = await memberPromote.json();
    expect(promotedBody?.deferred).toBe(true);
    expect(promotedBody?.task).toBeNull();

    // Owner finds the queued IMSuggestion via the project messages
    // endpoint (each message carries an attached `suggestion` if any).
    // The membrane-review system message is anchored to the inbox
    // suggestion, which is what we need the id of.
    const msgsRes = await ownerCtx.request.get(
      `/api/projects/${projectId}/messages?limit=200`,
    );
    expect(msgsRes.ok(), "messages fetch failed").toBeTruthy();
    const msgs: any[] = (await msgsRes.json())?.messages ?? [];
    const reviewSug = msgs
      .map((m) => m.suggestion)
      .find(
        (s: any) =>
          s &&
          s.kind === "membrane_review" &&
          s.proposal?.detail?.candidate_kind === "task_promote" &&
          s.proposal?.detail?.task_id === memberTaskId,
      );
    expect(
      reviewSug,
      "membrane_review IMSuggestion with task_promote detail not found",
    ).toBeTruthy();

    const acceptRes = await ownerCtx.request.post(
      `/api/im_suggestions/${reviewSug.id}/accept`,
    );
    expect(
      acceptRes.ok(),
      `accept failed ${acceptRes.status()} ${await acceptRes.text()}`,
    ).toBeTruthy();

    // Member's task is now plan-scope.
    const refreshState = await ownerCtx.request.get(
      `/api/projects/${projectId}/state`,
    );
    const refreshed = await refreshState.json();
    const planTasks: any[] = refreshed?.plan?.tasks ?? [];
    const promotedTask = planTasks.find((t) => t.id === memberTaskId);
    expect(
      promotedTask,
      "promoted task not found in plan after accept",
    ).toBeTruthy();

    await ownerCtx.close();
    await memberCtx.close();
  });
});
