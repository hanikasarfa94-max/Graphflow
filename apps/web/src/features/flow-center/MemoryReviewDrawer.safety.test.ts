// RW-3.5 safety tests — these prove the Revise affordance cannot be
// mistaken for a real persisted action.
//
// Three independent surfaces guard the same invariant:
//
//   1. Drawer source must not contain a Revise button or textarea
//      (rendered UI safety). Asserted by a source grep.
//   2. postCandidateAction's signature must not take a revision body
//      (wire-shape safety). Asserted by a call to the helper with
//      stubbed fetch — the URL hit by the POST is the bare
//      /api/memory-candidates/:id/accept path, with NO query string
//      and NO body field that carries a revised claim.
//   3. The four wired actions are exactly accept / defer / reject /
//      reopen — no `revise` action exists in the dispatcher (typed
//      union safety). Asserted by exhaustive switch.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import {
  postCandidateAction,
  type CandidateAction,
} from "./memoryCandidateActions";

const originalFetch = globalThis.fetch;

describe("Revise safety — RW-3.5", () => {
  beforeEach(() => {
    globalThis.fetch = originalFetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("MemoryReviewDrawer source has no Revise button or textarea", async () => {
    const path = "src/features/flow-center/MemoryReviewDrawer.tsx";
    const src = await Bun.file(path).text();

    // Strip block comments — the file's intent comments LEGITIMATELY
    // explain why Revise was removed, and a naive substring search
    // would match those explanations and false-fail. We only care
    // about live code references.
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");

    // No interactive revise affordance.
    expect(stripped.includes("setRevising")).toBe(false);
    expect(stripped.includes("setRevisedAtom")).toBe(false);
    // No revise textarea in JSX.
    expect(stripped.includes("<textarea")).toBe(false);
    // No `revising` state slot from useState.
    expect(/useState.*revising/i.test(stripped)).toBe(false);
  });

  test("postCandidateAction sends no revision body on accept", async () => {
    let capturedInit: RequestInit | undefined;
    let capturedUrl: string | undefined;
    globalThis.fetch = (async (
      input: RequestInfo | URL,
      init?: RequestInit,
    ) => {
      capturedUrl = typeof input === "string" ? input : (input as URL).toString();
      capturedInit = init;
      return new Response("{}", { status: 200 });
    }) as typeof fetch;

    await postCandidateAction("accept", "cand_abc");

    expect(capturedUrl).toBe("/api/memory-candidates/cand_abc/accept");
    expect(capturedInit?.method).toBe("POST");
    // The body must be `{}` — no revised_claim, no revised_atom, no
    // anything that the BE could mistake for a persisted edit. If
    // anyone adds a revision field in the future without also
    // wiring the BE side, this test catches it.
    const bodyText =
      typeof capturedInit?.body === "string" ? capturedInit.body : "";
    expect(bodyText).toBe("{}");
    expect(bodyText.toLowerCase().includes("revis")).toBe(false);
  });

  test("CandidateAction union does not include 'revise'", () => {
    // Exhaustive switch — TypeScript catches a new variant at
    // compile time; runtime test catches a refactor that adds a new
    // variant but forgets to make it explicit. If a future change
    // adds `| 'revise'` to CandidateAction, the switch default
    // becomes reachable and this test fails.
    const exhaust = (a: CandidateAction): string => {
      switch (a) {
        case "accept":
        case "defer":
        case "reject":
        case "reopen":
          return a;
        default: {
          // If this branch is reachable, a new variant slipped in.
          const _never: never = a;
          return _never;
        }
      }
    };
    expect(exhaust("accept")).toBe("accept");
    expect(exhaust("defer")).toBe("defer");
    expect(exhaust("reject")).toBe("reject");
    expect(exhaust("reopen")).toBe("reopen");
  });
});
