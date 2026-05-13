// RW-6 — Object-route placeholder + fabricated-id safety tests.
//
// Three guarantees:
//   1. The four global object routes no longer render the Phase E.1
//      "Coming in Phase E.2" placeholder string.
//   2. Each route uses the live API path it claims to use (so a
//      regression to placeholder doesn't silently happen).
//   3. None of the fabricated mock ids from earlier scaffolds
//      (Mei, Ravi, dec_2026_*, kb_launch_*, etc.) appear in the
//      live route sources.

import { describe, expect, test } from "bun:test";

const ROUTES = [
  "src/app/scopes/[id]/page.tsx",
  "src/app/kb-items/[id]/page.tsx",
  "src/app/decisions/[id]/page.tsx",
  "src/app/nodes/[id]/page.tsx",
];

describe("RW-6 — object routes are no longer placeholders", () => {
  for (const path of ROUTES) {
    test(`${path} does not render Phase E.1 placeholder`, async () => {
      const src = await Bun.file(path).text();
      // The placeholder Card had this title verbatim.
      expect(src.includes("Coming in Phase E.2")).toBe(false);
      // The placeholder also surfaced "Phase E.1" as a comment hook.
      // Allow the file-header comment to mention it historically, but
      // the rendered body must not.
      const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
      expect(stripped.includes("Coming in Phase E")).toBe(false);
    });
  }

  test("/scopes/[id] fetches /api/scopes/:id", async () => {
    const src = await Bun.file("src/app/scopes/[id]/page.tsx").text();
    expect(src.includes("/api/scopes/")).toBe(true);
    expect(src.includes("serverFetch")).toBe(true);
  });

  test("/kb-items/[id] fetches /api/kb-items/:id", async () => {
    const src = await Bun.file("src/app/kb-items/[id]/page.tsx").text();
    expect(src.includes("/api/kb-items/")).toBe(true);
    expect(src.includes("serverFetch")).toBe(true);
  });

  test("/decisions/[id] fetches /api/decisions/:id", async () => {
    const src = await Bun.file("src/app/decisions/[id]/page.tsx").text();
    expect(src.includes("/api/decisions/")).toBe(true);
    expect(src.includes("serverFetch")).toBe(true);
  });

  test("/nodes/[id] resolves via kb-items + decisions and never invents lineage", async () => {
    const src = await Bun.file("src/app/nodes/[id]/page.tsx").text();
    // Resolver probes both kinds.
    expect(src.includes("/api/kb-items/")).toBe(true);
    expect(src.includes("/api/decisions/")).toBe(true);
    // Successful resolution dispatches via redirect — the node route
    // is a wrapper, not a rendered "fake lineage" page.
    expect(src.includes("redirect(`/kb-items/")).toBe(true);
    expect(src.includes("redirect(`/decisions/")).toBe(true);
  });
});

describe("RW-6 — fabricated mock ids are gone from object routes", () => {
  // Every id that appeared in the Phase D / E.1 mock scaffolds and
  // could mislead a reviewer into thinking the surface is real.
  const FABRICATED_IDS = [
    "Mei",
    "Ravi",
    "Alex",
    "Jess",
    "user_mei",
    "user_ravi",
    "user_alex",
    "doc_shared_brief",
    "task_followup",
    "task_q3_launch_plan",
    "doc_launch_memo",
    "kb_launch_constraints",
    "dec_2026_03_pricing",
    "dec_2026_04_dates",
    "task_marketing_lock",
    "topic_launch_date",
    "topic_pricing_floor",
    "conv_dm_mei",
    "conv_dm_ravi",
    "conv_room_launch",
    "conv_room_growth",
  ];

  for (const path of ROUTES) {
    test(`${path} contains no fabricated mock ids`, async () => {
      const src = await Bun.file(path).text();
      const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
      for (const ghost of FABRICATED_IDS) {
        expect(stripped.includes(ghost)).toBe(false);
      }
    });
  }
});
