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

describe("RW-9.5 — recorded reply rendering", () => {
  test("FlowDrawer renders a dedicated RecordedReplySection", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("RecordedReplySection")).toBe(true);
    expect(src.includes("flow-drawer-recorded-reply")).toBe(true);
    // The section gates on recorded_reply being non-null so an empty
    // reply doesn't render a phantom card.
    const stripped = strip(src);
    expect(/const\s+rr\s*=\s*fr\.recorded_reply/.test(stripped)).toBe(true);
    expect(stripped.includes("if (!rr) return null")).toBe(true);
  });

  test("RecordedReply reads exactly the BE field names (no renames)", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    // Wire alignment with FlowRequestRecordedReply on the BE — any
    // rename here would silently break the render.
    expect(src.includes("rr.text")).toBe(true);
    expect(src.includes("rr.option_label")).toBe(true);
    expect(src.includes("rr.option_id")).toBe(true);
    expect(src.includes("rr.replied_at")).toBe(true);
    expect(src.includes("rr.replier_user_id")).toBe(true);
  });
});

describe("RW-9.5 — Open conversation link only with a real href", () => {
  test("OpenConversationSection gates on dm.stream_id + dm.href", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("OpenConversationSection")).toBe(true);
    // The link is rendered behind a real-href guard; the absence
    // branch renders an honest "no DM yet" caption with its own
    // test-id.
    expect(src.includes("flow-drawer-open-conversation")).toBe(true);
    expect(src.includes("flow-drawer-dm-absent")).toBe(true);
    const stripped = strip(src);
    expect(/if\s*\(\s*!\s*dm\??\.stream_id\s*\|\|\s*!\s*dm\.href\s*\)/.test(stripped)).toBe(true);
  });

  test("FlowDrawer never fabricates a /conversations href client-side", async () => {
    // The href must come from the BE dm.href payload. If we ever
    // catch the FE composing `/conversations/${something}` inline,
    // the BE guarantee about find_dm_between (no side-effect
    // creation) is no longer trustworthy.
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    const stripped = strip(src);
    expect(/\/conversations\/\$\{/.test(stripped)).toBe(false);
    expect(stripped.includes("\"/conversations/\"")).toBe(false);
  });
});

describe("RW-9.5 — non-route kinds get kind-specific guidance", () => {
  test("NotSupportedState exposes the kind via data attribute", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    expect(src.includes("data-not-supported-kind")).toBe(true);
  });

  test("All 7 known non-route kinds have guidance entries", async () => {
    const src = await Bun.file("src/features/flow-center/FlowDrawer.tsx").text();
    for (const kind of [
      "kb",
      "task_promote",
      "decision",
      "handoff",
      "manual_room",
      "manual_skill",
      "manual_invite",
    ]) {
      // The guidance map carries every kind the server's
      // _KNOWN_KINDS emits as not_supported_yet.
      expect(src.includes(`"${kind}"`)).toBe(true);
    }
  });

  test("Both locale files carry guidance copy for each kind", async () => {
    const en = await Bun.file("src/i18n/locales/en.json").text();
    const zh = await Bun.file("src/i18n/locales/zh.json").text();
    for (const kind of [
      "kb",
      "task_promote",
      "decision",
      "handoff",
      "manual_room",
      "manual_skill",
      "manual_invite",
    ]) {
      // Both locales must define a guidance string per kind.
      expect(
        new RegExp(`"notSupportedGuidance"[\\s\\S]*"${kind}"\\s*:\\s*"`).test(
          en,
        ),
      ).toBe(true);
      expect(
        new RegExp(`"notSupportedGuidance"[\\s\\S]*"${kind}"\\s*:\\s*"`).test(
          zh,
        ),
      ).toBe(true);
    }
  });
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
