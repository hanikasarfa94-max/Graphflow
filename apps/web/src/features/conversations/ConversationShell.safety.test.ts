// RW-4 safety / structural tests.
//
// Two guarantees:
//   1. The mock useConversation() hook that fabricated Mei/Ravi/Alex
//      messages, invented scopes, and synthesized topic_status is
//      gone from the feature folder.
//   2. The three right rails no longer import the shared spine module
//      (rightRailShared.tsx) — it was the carrier for the invented
//      docs/tasks/decisions in the Phase D scaffold, and we deleted
//      the file. A regression that re-introduces those imports
//      would silently bring back fabricated rail content.

import { describe, expect, test } from "bun:test";

describe("RW-4 — Conversation detail mock fixtures are gone", () => {
  test("ConversationShell has no mock useConversation() hook", async () => {
    const src = await Bun.file(
      "src/features/conversations/ConversationShell.tsx",
    ).text();
    // Strip block + line comments so the explanation in the file
    // header doesn't false-fail the grep.
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    // The new shell uses useConversationDetail (real fetch); the old
    // useConversation (synchronous mock) must not return.
    expect(/function\s+useConversation\s*\(/.test(stripped)).toBe(false);
    expect(/export\s+function\s+useConversation\s*\(/.test(stripped)).toBe(
      false,
    );
    // The fabricated authors must be gone everywhere in the shell.
    for (const ghost of [
      '"Mei"',
      '"Ravi"',
      '"Alex"',
      '"Jess"',
      '"user_mei"',
      '"user_ravi"',
      '"user_alex"',
    ]) {
      expect(stripped.includes(ghost)).toBe(false);
    }
    // The real fetch entry point must be present.
    expect(src.includes("/api/conversations/")).toBe(true);
  });

  test("rightRailShared module has been removed", async () => {
    const file = Bun.file("src/features/conversations/rightRailShared.tsx");
    expect(await file.exists()).toBe(false);
  });

  test("right rails do not import the removed shared spine", async () => {
    for (const path of [
      "src/features/conversations/DMRightRail.tsx",
      "src/features/conversations/RoomRightRail.tsx",
      "src/features/conversations/TopicRightRail.tsx",
    ]) {
      const src = await Bun.file(path).text();
      expect(src.includes("./rightRailShared")).toBe(false);
      expect(src.includes("rightRailShared")).toBe(false);
    }
  });

  test("DMRightRail has no fabricated related-work / evidence", async () => {
    const src = await Bun.file(
      "src/features/conversations/DMRightRail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    // The Phase D scaffold invented these identifiers; none should
    // appear in the live rail.
    for (const ghost of [
      "doc_shared_brief",
      "task_followup",
      "Brief co-edited",
      "Follow-up task",
    ]) {
      expect(stripped.includes(ghost)).toBe(false);
    }
  });

  test("RoomRightRail has no fabricated decisions / docs", async () => {
    const src = await Bun.file(
      "src/features/conversations/RoomRightRail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    for (const ghost of [
      "task_q3_launch_plan",
      "doc_launch_memo",
      "kb_launch_constraints",
      "dec_2026_03_pricing",
      "Pricing decision",
      "Launch memo v4",
    ]) {
      expect(stripped.includes(ghost)).toBe(false);
    }
  });

  test("TopicRightRail renders honest empty + no fabricated evidence", async () => {
    const src = await Bun.file(
      "src/features/conversations/TopicRightRail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    for (const ghost of [
      "task_marketing_lock",
      "dec_2026_04_dates",
      "April date decision",
      "Marketing schedule lock",
    ]) {
      expect(stripped.includes(ghost)).toBe(false);
    }
    // Honest "not wired" affordance must still be there for i18n
    // resolution to fire.
    expect(src.includes("notWiredTag")).toBe(true);
    expect(src.includes("notWiredBody")).toBe(true);
  });
});
