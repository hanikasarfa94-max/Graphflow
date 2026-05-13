// MemoryReviewDrawer — FE action-decoder tests.
//
// Phase RW-3.2: exercises `postCandidateAction` against the WG error
// envelope shapes the backend actually returns. Stubs `fetch` so the
// test runs offline without a live API. The decoder is the load-
// bearing piece: the rest of the drawer is presentation that the
// real backend invariant tests (apps/api/tests/test_rw3_memory_
// candidate_actions.py) cover.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { postCandidateAction } from "./memoryCandidateActions";

const originalFetch = globalThis.fetch;

interface StubResponse {
  status: number;
  body: unknown;
}

function stubFetch(response: StubResponse) {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(response.body), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

describe("postCandidateAction", () => {
  beforeEach(() => {
    globalThis.fetch = originalFetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("returns ok:true on 200", async () => {
    stubFetch({ status: 200, body: { candidate_id: "c1", status: "accepted" } });
    const result = await postCandidateAction("accept", "c1");
    expect(result.ok).toBe(true);
  });

  test("decodes 403 authority_required into typed error + role", async () => {
    // WG envelope shape emitted by the global exception handler.
    stubFetch({
      status: 403,
      body: {
        code: "internal_error",
        message: "authority_required",
        details: {
          required_roles: ["project_owner", "admin"],
          user_roles: ["project_member"],
          allowed_actions: ["comment", "request_review", "defer"],
        },
        trace_id: "trace-abc",
      },
    });
    const result = await postCandidateAction("accept", "c1");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("authority_required");
    // Required role surfaces so the i18n key can interpolate it.
    expect(result.required_role).toBe("project_owner");
  });

  test("decodes 409 already_resolved", async () => {
    stubFetch({
      status: 409,
      body: { code: "conflict", message: "already_resolved", details: {} },
    });
    const result = await postCandidateAction("accept", "c1");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("already_resolved");
  });

  test("decodes 409 not_reopenable", async () => {
    stubFetch({
      status: 409,
      body: { code: "conflict", message: "not_reopenable", details: {} },
    });
    const result = await postCandidateAction("reopen", "c1");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("not_reopenable");
  });

  test("decodes 404 not_found", async () => {
    stubFetch({
      status: 404,
      body: { code: "not_found", message: "not_found", details: {} },
    });
    const result = await postCandidateAction("defer", "c1");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("not_found");
  });

  test("returns network error when fetch throws", async () => {
    globalThis.fetch = (async () => {
      throw new Error("ECONNREFUSED");
    }) as typeof fetch;
    const result = await postCandidateAction("accept", "c1");
    expect(result.ok).toBe(false);
    expect(result.error).toBe("network");
  });

  test("preserves all four action paths in URL", async () => {
    const seen: string[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      seen.push(typeof input === "string" ? input : (input as URL).toString());
      return new Response("{}", { status: 200 });
    }) as typeof fetch;
    await postCandidateAction("accept", "c1");
    await postCandidateAction("defer", "c2");
    await postCandidateAction("reject", "c3");
    await postCandidateAction("reopen", "c4");
    expect(seen).toEqual([
      "/api/memory-candidates/c1/accept",
      "/api/memory-candidates/c2/defer",
      "/api/memory-candidates/c3/reject",
      "/api/memory-candidates/c4/reopen",
    ]);
  });
});
