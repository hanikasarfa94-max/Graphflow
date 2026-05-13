// RW-5 — Conversation send wire tests.
//
// Three guarantees:
//   1. postConversationMessage() hits the right URL with the right
//      body shape — `{body: "..."}` against POST
//      /api/conversations/:id/messages.
//   2. WG envelope error decoding maps 403/404/422/network to the
//      typed SendResult kinds the composer uses to pick i18n keys.
//   3. The no-op send is structurally gone from ConversationShell —
//      send goes through the real action client. Catches a regression
//      where someone reverts to the placeholder noop.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { postConversationMessage } from "./conversationActions";

const originalFetch = globalThis.fetch;

describe("postConversationMessage", () => {
  beforeEach(() => {
    globalThis.fetch = originalFetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("POSTs to /api/conversations/:id/messages with the body shape", async () => {
    let capturedUrl: string | undefined;
    let capturedInit: RequestInit | undefined;
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      capturedUrl = typeof input === "string" ? input : (input as URL).toString();
      capturedInit = init;
      return new Response(
        JSON.stringify({ ok: true, id: "msg_1", body: "hi" }),
        { status: 200 },
      );
    }) as typeof fetch;

    const result = await postConversationMessage("conv_abc", "  hi  ");
    expect(result.ok).toBe(true);
    expect(capturedUrl).toBe("/api/conversations/conv_abc/messages");
    expect(capturedInit?.method).toBe("POST");
    // The action client trims client-side before the round-trip,
    // and the body field is the only thing sent (no extra metadata).
    const bodyText =
      typeof capturedInit?.body === "string" ? capturedInit.body : "";
    expect(JSON.parse(bodyText)).toEqual({ body: "hi" });
  });

  test("URL-encodes conversation ids that contain unsafe characters", async () => {
    let capturedUrl: string | undefined;
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      capturedUrl = typeof input === "string" ? input : (input as URL).toString();
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await postConversationMessage("conv/with slash", "x");
    expect(capturedUrl).toBe(
      "/api/conversations/conv%2Fwith%20slash/messages",
    );
  });

  test("trims and rejects empty before hitting the network", async () => {
    let calls = 0;
    globalThis.fetch = (async () => {
      calls += 1;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    const result = await postConversationMessage("c1", "   ");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("validation");
    expect(calls).toBe(0);
  });

  test("decodes 403 not_a_member from the WG envelope", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          code: "internal_error",
          message: "not_a_member",
          details: {},
        }),
        { status: 403 },
      );
    }) as typeof fetch;
    const result = await postConversationMessage("c1", "hi");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("not_a_member");
  });

  test("decodes 404 stream_not_found from the WG envelope", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          code: "not_found",
          message: "stream_not_found",
          details: {},
        }),
        { status: 404 },
      );
    }) as typeof fetch;
    const result = await postConversationMessage("c1", "hi");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("stream_not_found");
  });

  test("decodes 422 validation", async () => {
    globalThis.fetch = (async () => {
      return new Response(
        JSON.stringify({
          code: "validation_error",
          message: "request validation failed",
          details: {},
        }),
        { status: 422 },
      );
    }) as typeof fetch;
    const result = await postConversationMessage("c1", "hi");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("validation");
  });

  test("returns network error when fetch throws", async () => {
    globalThis.fetch = (async () => {
      throw new Error("ECONNREFUSED");
    }) as typeof fetch;
    const result = await postConversationMessage("c1", "hi");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("network");
  });
});

describe("RW-5 — Composer no-op is structurally gone", () => {
  test("ConversationShell calls postConversationMessage on send", async () => {
    const src = await Bun.file(
      "src/features/conversations/ConversationShell.tsx",
    ).text();
    // The shell must reference the real action client.
    expect(src.includes("postConversationMessage")).toBe(true);
    // The Phase D placeholder TODO comment must be gone — leaving
    // it in suggests the wiring isn't actually live.
    expect(src.includes("RW-5): POST /api/conversations")).toBe(false);
    expect(src.includes("RW-4 is read-only")).toBe(false);
  });

  test("ConversationComposer no-op fallback signature is removed", async () => {
    const src = await Bun.file(
      "src/features/conversations/ConversationComposer.tsx",
    ).text();
    // The composer is no longer typed for a void-returning send —
    // it must consume the discriminated SendResult so it can render
    // a typed error message.
    expect(src.includes("Promise<SendResult>")).toBe(true);
    // The old "no-op so the surface looks complete" affordance is
    // gone; the real path either succeeds or surfaces an error.
    expect(src.toLowerCase().includes("no-op")).toBe(false);
  });

  test("topic conversations get a disabled composer with honest copy", async () => {
    const src = await Bun.file(
      "src/features/conversations/ConversationShell.tsx",
    ).text();
    // The shell branches on type === "topic" → composer locked.
    expect(src.includes('conv.type === "topic"')).toBe(true);
    expect(src.includes("disabledTopic")).toBe(true);
  });
});
