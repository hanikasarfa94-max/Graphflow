// MyAI landing — structural / safety tests.
//
// Guarantees the landing-vs-active behavior on /my-ai:
//   1. MyAILandingClient owns active state with a sticky-once guard.
//   2. The "Ready to share" section is conditional on hasDrafts —
//      never renders when ready_to_share is empty.
//   3. The "Pick up where you left off" section gates on
//      `hasGrounded && (!active || showReentry)`.
//   4. The post-activity "Show re-entry items" toggle uses bilingual
//      i18n keys.
//   5. MyAIComposer exposes an onActivity callback that fires on
//      focus + first send, and the legacy "No drafts ready to send
//      yet" string is gone from the codebase.
//   6. The composer still POSTs to /api/my-ai/messages.

import { describe, expect, test } from "bun:test";

function strip(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
}

describe("MyAI — landing client owns active state", () => {
  test("MyAILandingClient.tsx exists and is a client component", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAILandingClient.tsx",
    ).text();
    expect(src.startsWith('"use client"')).toBe(true);
    expect(src.includes("useState")).toBe(true);
    // Sticky active flag — must NEVER revert to false during a mount.
    const stripped = strip(src);
    expect(/setActive\(false\)/.test(stripped)).toBe(false);
  });

  test("page.tsx delegates to MyAILandingClient", async () => {
    const src = await Bun.file("src/app/my-ai/page.tsx").text();
    expect(src.includes("MyAILandingClient")).toBe(true);
    // The server page should no longer render the landing sections
    // itself — those move into the client wrapper.
    const stripped = strip(src);
    expect(stripped.includes("Pick up where you left off")).toBe(false);
    expect(stripped.includes("Ready to share")).toBe(false);
    expect(stripped.includes("MyAIComposer")).toBe(false);
  });
});

describe("MyAI — Ready-to-share never renders when empty", () => {
  test("MyAILandingClient gates the section on hasDrafts", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAILandingClient.tsx",
    ).text();
    const stripped = strip(src);
    // The exact noise we're removing — the legacy permanent empty
    // state copy MUST be gone from the wrapper.
    expect(stripped.includes("No drafts ready to send yet")).toBe(false);
    // And the section must render only when hasDrafts is truthy.
    expect(/\{\s*hasDrafts\s*\?[\s\S]{0,400}ready-heading/.test(stripped)).toBe(
      true,
    );
  });

  test("page.tsx no longer contains the empty Ready-to-share fallback", async () => {
    const src = await Bun.file("src/app/my-ai/page.tsx").text();
    const stripped = strip(src);
    expect(stripped.includes("No drafts ready to send yet")).toBe(false);
  });
});

describe("MyAI — grounded section collapses after activity", () => {
  test("Grounded section gated on hasGrounded AND (!active OR showReentry)", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAILandingClient.tsx",
    ).text();
    const stripped = strip(src);
    // The wrapper computes the visibility flag — assert the boolean
    // expression at the source level so a future refactor that
    // accidentally drops the gate trips the test.
    expect(
      /hasGrounded\s*&&\s*\(!active\s*\|\|\s*showReentry\)/.test(stripped),
    ).toBe(true);
    // The post-activity toggle exists.
    expect(stripped.includes("my-ai-show-reentry")).toBe(true);
    expect(stripped.includes("my-ai-hide-reentry")).toBe(true);
  });

  test("Landing-only empty state guards on !active", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAILandingClient.tsx",
    ).text();
    const stripped = strip(src);
    // "Nothing waiting for you right now" only renders pre-activity —
    // after activity it would be noise.
    expect(
      /!hasGrounded\s*&&\s*!active\s*\?/.test(stripped),
    ).toBe(true);
    expect(stripped.includes("my-ai-landing-empty")).toBe(true);
  });
});

describe("MyAI — composer fires onActivity on focus + send", () => {
  test("MyAIComposer accepts onActivity prop with sticky-once semantics", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAIComposer.tsx",
    ).text();
    const stripped = strip(src);
    // Prop declared.
    expect(stripped.includes("onActivity")).toBe(true);
    // Idempotent ref-guard so re-firing on every keystroke is impossible.
    expect(stripped.includes("activitySignaled")).toBe(true);
    expect(/activitySignaled\.current\s*=\s*true/.test(stripped)).toBe(true);
  });

  test("textarea wires onFocus to the activity signaler", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAIComposer.tsx",
    ).text();
    const stripped = strip(src);
    // The handler may be a direct reference (`onFocus={signalActivity}`)
    // OR a wrapping lambda that calls signalActivity() and an
    // additional side-effect (e.g., setting focus-ring state). The
    // intent test: somewhere in the textarea's onFocus binding, the
    // activity signaler fires. Match either shape.
    const directBind = /onFocus\s*=\s*\{\s*signalActivity\s*\}/.test(stripped);
    const lambdaBind =
      /onFocus\s*=\s*\{\s*\(\s*\)\s*=>\s*\{[\s\S]{0,200}signalActivity\s*\(\s*\)/.test(
        stripped,
      );
    expect(directBind || lambdaBind).toBe(true);
  });

  test("onSubmit calls signalActivity before posting", async () => {
    // Covers the Cmd+Enter / programmatic-send path where focus
    // might not have fired yet (e.g. send from a parent shortcut).
    const src = await Bun.file(
      "src/features/my-ai/MyAIComposer.tsx",
    ).text();
    const stripped = strip(src);
    const submit = stripped.slice(stripped.indexOf("const onSubmit"));
    expect(submit.includes("signalActivity()")).toBe(true);
    // signalActivity must precede the actual POST.
    const sigIdx = submit.indexOf("signalActivity()");
    const postIdx = submit.indexOf('"/api/my-ai/messages"');
    expect(sigIdx).toBeGreaterThanOrEqual(0);
    expect(postIdx).toBeGreaterThanOrEqual(0);
    expect(sigIdx).toBeLessThan(postIdx);
  });
});

describe("MyAI — composer still posts to the live endpoint", () => {
  test("MyAIComposer targets /api/my-ai/messages via api()", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAIComposer.tsx",
    ).text();
    expect(src.includes("/api/my-ai/messages")).toBe(true);
    expect(src.includes("method: \"POST\"")).toBe(true);
    // Doctrine: send response NEVER auto-routes to memory drawer.
    const stripped = strip(src);
    expect(stripped.includes("MemoryReviewDrawer")).toBe(false);
    expect(stripped.includes("memory_auto_accepted")).toBe(false);
  });
});

describe("MyAI — bilingual toggle copy", () => {
  test("Both locale files define shellV062.myAi.showReentry + groundedHide", async () => {
    const en = await Bun.file("src/i18n/locales/en.json").text();
    const zh = await Bun.file("src/i18n/locales/zh.json").text();
    for (const locale of [en, zh]) {
      expect(
        /"myAi"\s*:\s*\{[\s\S]*?"showReentry"\s*:\s*"/.test(locale),
      ).toBe(true);
      expect(
        /"myAi"\s*:\s*\{[\s\S]*?"groundedHide"\s*:\s*"/.test(locale),
      ).toBe(true);
      expect(
        /"myAi"\s*:\s*\{[\s\S]*?"landingEmpty"\s*:\s*"/.test(locale),
      ).toBe(true);
    }
  });

  test("Toggle button uses translated copy, not hard-coded English", async () => {
    const src = await Bun.file(
      "src/features/my-ai/MyAILandingClient.tsx",
    ).text();
    const stripped = strip(src);
    // The hard-coded English label must be gone — it should go through
    // useTranslations now.
    expect(stripped.includes("Show re-entry items (")).toBe(false);
    expect(/t\(\s*"showReentry"/.test(stripped)).toBe(true);
    expect(/t\(\s*"groundedHide"/.test(stripped)).toBe(true);
  });
});
