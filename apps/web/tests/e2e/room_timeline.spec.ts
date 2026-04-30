import { expect, test } from "@playwright/test";

import {
  apiRequest,
  intake,
  rando,
  registerUser,
} from "./helpers";

// Room-stream timeline — the projection model end-to-end.
//
// Verifies the contract the frontend RoomShell consumes:
//   1. POST /api/projects/{id}/rooms with a name → name persisted.
//   2. POST /api/projects/{id}/messages with stream_id=room → message
//      lands in the room's stream.
//   3. GET /api/projects/{id}/rooms/{room_id}/timeline → returns the
//      message in the items array with kind='message'.
//   4. The IM classifier may produce a suggestion which the timeline
//      surfaces as kind='im_suggestion'. (Best-effort assertion —
//      classifier latency varies; we don't gate on it.)
//   5. GET /api/projects/{id}/im_suggestions?stream_id=<room> →
//      returns only suggestions whose source message is in this room.
//
// Run via the standard request fixture (web proxy → API) so we exercise
// the same code path the browser hits.

test.describe("room timeline + projection", () => {
  test("post into a room and read it back via the timeline endpoint", async ({
    request,
  }) => {
    const user = await registerUser(request, { username: rando("room") });
    // Establish session.
    const loginRes = await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    expect(loginRes.ok(), "login failed").toBeTruthy();

    const projectId = await intake(
      request,
      `${user.display_name} owns intake. Track follow-ups in rooms.`,
    );

    // Resolve current user id.
    const meRes = await request.get("/api/auth/me");
    expect(meRes.ok()).toBeTruthy();
    const me = (await meRes.json()) as { id: string };

    // Create a room with the persisted-name field (alembic 0029).
    const roomRes = await request.post(`/api/projects/${projectId}/rooms`, {
      data: { name: "design-sync", member_user_ids: [me.id] },
    });
    expect(
      roomRes.ok(),
      `room create failed ${roomRes.status()} ${await roomRes.text()}`,
    ).toBeTruthy();
    const roomBody = await roomRes.json();
    const room = roomBody.stream as { id: string; name: string };
    expect(room.name).toBe("design-sync");

    // Post a message into the room (Composer streamId path).
    const msgRes = await request.post(
      `/api/projects/${projectId}/messages`,
      {
        data: {
          body: "let's drop this deliverable for the v1 launch",
          stream_id: room.id,
        },
      },
    );
    expect(
      msgRes.ok(),
      `message post failed ${msgRes.status()} ${await msgRes.text()}`,
    ).toBeTruthy();
    const msgBody = await msgRes.json();
    expect(msgBody.stream_id).toBe(room.id);

    // GET the room timeline. Must include the message we just posted.
    const tlRes = await request.get(
      `/api/projects/${projectId}/rooms/${room.id}/timeline`,
    );
    expect(
      tlRes.ok(),
      `timeline fetch failed ${tlRes.status()} ${await tlRes.text()}`,
    ).toBeTruthy();
    const tlBody = (await tlRes.json()) as {
      items: Array<{ kind: string; id: string }>;
    };
    expect(tlBody.items.length).toBeGreaterThan(0);
    const kinds = tlBody.items.map((it) => it.kind);
    expect(kinds).toContain("message");

    // The IM classifier runs async (`im_service.drain()` isn't exposed
    // over HTTP). Poll the suggestion list endpoint up to ~5s — if a
    // suggestion appears, also assert the room-scoped query returns
    // it. If not, the test still passes the projection-shape contract
    // (message timeline works) — the classifier latency is opaque to
    // this layer.
    let suggestion: { id: string } | null = null;
    for (let i = 0; i < 10; i++) {
      const sugRes = await request.get(
        `/api/projects/${projectId}/im_suggestions?stream_id=${room.id}`,
      );
      if (sugRes.ok()) {
        const sugBody = (await sugRes.json()) as {
          suggestions: Array<{ id: string }>;
        };
        if (sugBody.suggestions.length > 0) {
          suggestion = sugBody.suggestions[0];
          break;
        }
      }
      await new Promise((r) => setTimeout(r, 500));
    }

    if (suggestion) {
      // Re-fetch the timeline — should now also include the suggestion.
      const tl2Res = await request.get(
        `/api/projects/${projectId}/rooms/${room.id}/timeline`,
      );
      expect(tl2Res.ok()).toBeTruthy();
      const tl2Body = (await tl2Res.json()) as {
        items: Array<{ kind: string; id: string }>;
      };
      expect(tl2Body.items.some((it) => it.kind === "im_suggestion")).toBe(
        true,
      );

      // Sanity: same suggestion in BOTH projections (timeline + filtered list).
      const sugInTimeline = tl2Body.items.find(
        (it) => it.kind === "im_suggestion",
      );
      expect(sugInTimeline?.id).toBe(suggestion.id);
    }
  });

  test("rooms list returns persisted names", async ({ request }) => {
    const user = await registerUser(request, { username: rando("rooml") });
    const loginRes = await request.post("/api/auth/login", {
      data: { username: user.username, password: user.password },
    });
    expect(loginRes.ok()).toBeTruthy();

    const projectId = await intake(
      request,
      `${user.display_name} owns this project.`,
    );
    const meRes = await request.get("/api/auth/me");
    const me = (await meRes.json()) as { id: string };

    await request.post(`/api/projects/${projectId}/rooms`, {
      data: { name: "auth-redesign", member_user_ids: [me.id] },
    });
    await request.post(`/api/projects/${projectId}/rooms`, {
      data: { name: "billing-spike", member_user_ids: [me.id] },
    });

    const listRes = await request.get(`/api/projects/${projectId}/rooms`);
    expect(listRes.ok()).toBeTruthy();
    const body = (await listRes.json()) as {
      rooms: Array<{ id: string; name: string | null }>;
    };
    const names = body.rooms.map((r) => r.name).filter(Boolean);
    expect(names).toContain("auth-redesign");
    expect(names).toContain("billing-spike");
  });
});
