// RW-9 — FlowDrawer + flowRequestActions safety / structural tests.
//
// Guarantees:
//   1. The Phase D / RW-3.5 "not wired" empty state is gone — the
//      drawer no longer renders a hard-coded honest-empty card with
//      no fetch. It now fetches the singleton and routes states.
//   2. flowRequestActions issues the exact wire shapes the BE expects:
//      GET  /api/flow-requests/:id
//      POST /api/flow-requests/:id/respond  body={kind:"direct_response",text}
//   3. No fabricated request fixtures (Mei, launch-date framing,
//      placeholder authority) survive in the source.
//   4. The drawer does NOT auto-route to the memory review drawer
//      on respond success — memory crystallization stays a separate
//      decision.

import { describe, expect, test } from "bun:test";

function strip(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
}

describe("RW-9 — FlowDrawer routes the live singleton, not mock copy", () => {
  test("FlowDrawer.tsx imports fetchFlowRequest from flowRequestActions", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("fetchFlowRequest")).toBe(true);
    expect(src.includes("postFlowRequestResponse")).toBe(true);
    expect(src.includes("./flowRequestActions")).toBe(true);
  });

  test("FlowDrawer.tsx removed the legacy hardcoded not-wired body", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    const stripped = strip(src);
    // The earlier surface rendered a single static EmptyState referring
    // to GET /api/flow-requests/:id as not-landing-yet. Once the
    // singleton is real, those phrases must be gone.
    expect(
      stripped.includes("detail surface isn’t wired to the backend"),
    ).toBe(false);
    expect(
      stripped.includes("isn’t wired to the backend"),
    ).toBe(false);
    // The drawer no longer surfaces flow-drawer-not-wired as its only
    // test-id; the new states use distinct ids.
    expect(stripped.includes("flow-drawer-not-wired")).toBe(false);
  });

  test("FlowDrawer.tsx renders distinct test-ids for the new states", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("flow-drawer-not-supported")).toBe(true);
    expect(src.includes("flow-drawer-respond")).toBe(true);
    expect(src.includes("flow-drawer-respond-disabled")).toBe(true);
    expect(src.includes("flow-drawer-respond-submit")).toBe(true);
  });

  test("FlowDrawer.tsx does NOT open the memory review drawer on respond", async () => {
    // Doctrine: memory crystallization is a separate decision. Even
    // when /respond succeeds, the drawer must not auto-route to
    // MemoryReviewDrawer or MemoryPromptDrawer.
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    const stripped = strip(src);
    expect(stripped.includes("memory_review")).toBe(false);
    expect(stripped.includes("memory_prompt")).toBe(false);
    expect(stripped.includes("MemoryReviewDrawer")).toBe(false);
    expect(stripped.includes("MemoryPromptDrawer")).toBe(false);
  });
});

describe("RW-9 — flowRequestActions wire shapes", () => {
  test("flowRequestActions targets exactly /api/flow-requests/:id and /respond", async () => {
    const src = await Bun.file(
      "src/features/flow-center/flowRequestActions.ts",
    ).text();
    expect(src.includes("/api/flow-requests/")).toBe(true);
    expect(src.includes("/respond")).toBe(true);
    expect(src.includes("postFlowRequestResponse")).toBe(true);
    expect(src.includes("fetchFlowRequest")).toBe(true);
  });

  test("respond body is { kind: 'direct_response', text }", async () => {
    const src = await Bun.file(
      "src/features/flow-center/flowRequestActions.ts",
    ).text();
    // The literal must be a discriminated body — no `action: 'accept'`
    // leakage from the B.1 stub, no other kinds.
    expect(src.includes("kind: \"direct_response\"")).toBe(true);
    expect(src.includes("text")).toBe(true);
    // The pre-RW-9 stub body shape had action: accept|decline|... — it
    // must NOT be sent from the FE any more.
    expect(/action:\s*['"](accept|decline|revise|needs_more_info)['"]/.test(src)).toBe(false);
  });

  test("flowRequestActions distinguishes not_supported_yet vs not_found vs forbidden", async () => {
    const src = await Bun.file(
      "src/features/flow-center/flowRequestActions.ts",
    ).text();
    expect(src.includes("not_supported_yet")).toBe(true);
    expect(src.includes("not_found")).toBe(true);
    expect(src.includes("forbidden")).toBe(true);
  });
});

describe("RW-9 — no fabricated request fixtures in flow-center sources", () => {
  const GHOSTS = [
    // Phase D fabricated authors / scopes / topics from the older
    // FlowDrawer + MemoryReviewDrawer mock fixtures.
    "user_mei",
    "user_alex",
    "user_priya",
    "scope_tikhub",
    "scope_growth",
    "doc_brief_tikhub",
    "topic_launch_date",
    "dec_launch_sep18",
    // The "launch date framing" mock copy from the Phase C drawer.
    "permadeath dropping",
  ];

  const FILES = [
    "src/features/flow-center/FlowDrawer.tsx",
    "src/features/flow-center/flowRequestActions.ts",
    "src/features/flow-center/types.ts",
  ];

  for (const path of FILES) {
    test(`${path} has no fabricated ids / mock copy`, async () => {
      const src = await Bun.file(path).text();
      const stripped = strip(src);
      for (const ghost of GHOSTS) {
        expect(stripped.includes(ghost)).toBe(false);
      }
    });
  }
});

describe("RW-9 — invariant-suite alignment", () => {
  test("FlowDrawer never reads memory_auto_accepted from the respond envelope", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("memory_auto_accepted")).toBe(false);
  });

  test("flowRequestActions never reads memory_auto_accepted from the respond envelope", async () => {
    const src = await Bun.file(
      "src/features/flow-center/flowRequestActions.ts",
    ).text();
    expect(src.includes("memory_auto_accepted")).toBe(false);
  });
});
