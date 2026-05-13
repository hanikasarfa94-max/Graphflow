// RW-7 — Tasks feature safety / structural tests.
//
// Three guarantees:
//   1. The Phase D MOCK_TASKS array and useTasks() hook that
//      fabricated tasks for Mei/Ravi/Alex/Jess are gone.
//   2. The TaskRightRail no longer has the mock useTask() that
//      synthesized context_summary, evidence_sources, and AI
//      assistance buttons.
//   3. Page + feature sources consume the real /api/tasks endpoint.
//   4. No fabricated task ids/people/docs from earlier scaffolds
//      survive in the live source.

import { describe, expect, test } from "bun:test";

describe("RW-7 — Tasks list mock data is gone", () => {
  test("TaskList.tsx has no MOCK_TASKS array", async () => {
    const src = await Bun.file(
      "src/features/tasks/TaskList.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    expect(stripped.includes("MOCK_TASKS")).toBe(false);
    expect(/function\s+useTasks\s*\(/.test(stripped)).toBe(false);
    expect(/export\s+function\s+useTasks\s*\(/.test(stripped)).toBe(false);
  });

  test("TaskRightRail.tsx has no mock useTask() hook", async () => {
    const src = await Bun.file(
      "src/features/tasks/TaskRightRail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    // The Phase D version exported `useTask(id) → TaskDetail`. The new
    // rail takes `task` as a prop; no internal mock survives.
    expect(/function\s+useTask\s*\(/.test(stripped)).toBe(false);
    expect(/export\s+function\s+useTask\s*\(/.test(stripped)).toBe(false);
  });
});

describe("RW-7 — Tasks pages consume real endpoint", () => {
  test("/tasks page does server-side fetch on /api/tasks", async () => {
    const src = await Bun.file("src/app/tasks/page.tsx").text();
    expect(src.includes("serverFetch")).toBe(true);
    expect(src.includes("/api/tasks?")).toBe(true);
  });

  test("/tasks/[id] page does server-side fetch on /api/tasks/:id", async () => {
    const src = await Bun.file("src/app/tasks/[id]/page.tsx").text();
    expect(src.includes("serverFetch")).toBe(true);
    expect(src.includes("/api/tasks/")).toBe(true);
  });
});

describe("RW-7 — fabricated mock ids are gone from Tasks feature", () => {
  const FABRICATED = [
    // mock owners + assignees
    "user_alex",
    "user_ravi",
    "user_mei",
    "user_jess",
    "user_priya",
    "user_vp_ops",
    // mock task ids
    "task_001",
    "task_002",
    "task_003",
    "task_004",
    "task_005",
    "task_006",
    // mock scope labels
    "scope_tikhub",
    "scope_growth",
    // mock requirement ids
    "req_sso",
    "req_soc2",
    "req_onboarding_handoff",
    "req_vendor_renewal",
    // mock source message ids
    "msg_okr_kickoff",
    "msg_pricing_audit",
    // mock TaskRightRail detail invented references
    "doc_pricing_v3",
    "decision_q2_renewal",
    "node_pricing_audit",
  ];

  const FILES = [
    "src/features/tasks/TaskList.tsx",
    "src/features/tasks/TaskCard.tsx",
    "src/features/tasks/Tasks.tsx",
    "src/features/tasks/TaskRightRail.tsx",
    "src/features/tasks/types.ts",
    "src/app/tasks/page.tsx",
    "src/app/tasks/[id]/page.tsx",
  ];

  for (const path of FILES) {
    test(`${path} contains no fabricated mock ids`, async () => {
      const src = await Bun.file(path).text();
      const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
      for (const ghost of FABRICATED) {
        expect(stripped.includes(ghost)).toBe(false);
      }
    });
  }
});
