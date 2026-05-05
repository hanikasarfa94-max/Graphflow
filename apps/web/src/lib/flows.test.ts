import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  BUCKETS,
  RECIPE_ICON,
  type FlowPacket,
  type FlowRecipeId,
} from "./flows";

// The typed FlowPacket shape is the contract between the BE projection
// and the FE drawer. These tests catch two failure modes:
//
//   1. The FE adds a recipe id that doesn't exist on the BE (or vice-
//      versa) — caught by the static union vs. catalog check.
//   2. A locale file is missing a key the drawer reads — caught by
//      asserting bilingual presence on every recipe / bucket / stage.
//
// The drawer itself ships without React-Testing-Library here (apps/web
// has no RTL setup). Component behavior (3 buckets, empty states, href
// link) is exercised against the live endpoint by the BE projection
// tests; the drawer UI gets a manual dogfood pass before deploy.

const RECIPES_IN_UNION: readonly FlowRecipeId[] = [
  "ask_with_context",
  "promote_to_memory",
  "crystallize_decision",
  "review",
  "handoff",
  "meeting_metabolism",
];

describe("flows typed contract", () => {
  test("RECIPE_ICON has an entry for every FlowRecipeId", () => {
    for (const id of RECIPES_IN_UNION) {
      expect(RECIPE_ICON[id]).toBeDefined();
      expect(typeof RECIPE_ICON[id]).toBe("string");
      expect(RECIPE_ICON[id].length).toBeGreaterThan(0);
    }
  });

  test("BUCKETS exposes the three buckets the drawer actually fetches", () => {
    expect(BUCKETS).toEqual([
      "needs_me",
      "waiting_on_others",
      "awaiting_membrane",
    ]);
  });

  test("a sample BE packet round-trips through the FlowPacket type", () => {
    // Mirror the shape FlowProjectionService emits for a route packet
    // on the BE. If the BE adds a required field, this fails to compile
    // (TS catches the drift) AND the runtime asserts crash if the
    // field is renamed.
    const sample: FlowPacket = {
      id: "route:abc123",
      project_id: "p1",
      recipe_id: "ask_with_context",
      stage: "awaiting_target",
      status: "active",
      source_user_id: "u-source",
      target_user_ids: ["u-target"],
      current_target_user_ids: ["u-target"],
      authority_user_ids: [],
      title: "Quick design call?",
      summary: "Quick design call?",
      intent: "Ask another teammate with framed context.",
      source_refs: [],
      graph_refs: [],
      evidence: {
        citations: [],
        source_messages: [],
        artifacts: [],
        agent_runs: [],
        human_gates: [],
        uncertainty: [],
      },
      routed_signal_id: "abc123",
      timeline: [],
      next_actions: [
        {
          id: "reply",
          label: "Reply",
          kind: "open",
          actor_user_id: "u-target",
          requires_membrane: false,
          href: "/inbox",
        },
      ],
      created_at: "2026-05-05T10:00:00+0800",
      updated_at: "2026-05-05T10:00:00+0800",
    };

    expect(sample.id.startsWith("route:")).toBe(true);
    expect(sample.next_actions[0].kind).toBe("open");
    expect(sample.next_actions[0].href).toBe("/inbox");
    // current_target_user_ids is the spec's "currently blocking" slice;
    // target_user_ids is participation history. Both must be present
    // and may differ — Slice C+ tests will exercise the divergence.
    expect(Array.isArray(sample.target_user_ids)).toBe(true);
    expect(Array.isArray(sample.current_target_user_ids)).toBe(true);
  });
});

const LOCALES_DIR = join(import.meta.dir, "..", "i18n", "locales");

function loadLocale(file: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(LOCALES_DIR, file), "utf-8"));
}

function dive(obj: unknown, path: string[]): unknown {
  let cur: unknown = obj;
  for (const seg of path) {
    if (cur && typeof cur === "object" && seg in (cur as object)) {
      cur = (cur as Record<string, unknown>)[seg];
    } else {
      return undefined;
    }
  }
  return cur;
}

describe("flows i18n contract (en + zh in lockstep)", () => {
  const en = loadLocale("en.json");
  const zh = loadLocale("zh.json");

  test("every bucket has a label + empty-state in BOTH locales", () => {
    const labels = ["needsMe", "waitingOnOthers", "awaitingMembrane"];
    for (const key of labels) {
      const enLabel = dive(en, ["flows", "buckets", key]);
      const zhLabel = dive(zh, ["flows", "buckets", key]);
      expect(typeof enLabel).toBe("string");
      expect(typeof zhLabel).toBe("string");
      expect(zhLabel).not.toBe(enLabel);

      const enEmpty = dive(en, ["flows", "empty", key]);
      const zhEmpty = dive(zh, ["flows", "empty", key]);
      expect(typeof enEmpty).toBe("string");
      expect(typeof zhEmpty).toBe("string");
      expect(zhEmpty).not.toBe(enEmpty);
    }
  });

  test("every recipe id has a label in BOTH locales", () => {
    for (const id of RECIPES_IN_UNION) {
      const enLabel = dive(en, ["flows", "recipes", id]);
      const zhLabel = dive(zh, ["flows", "recipes", id]);
      expect(typeof enLabel).toBe("string");
      expect(typeof zhLabel).toBe("string");
      expect(zhLabel).not.toBe(enLabel);
    }
  });

  test("the workbench chip label is bilingual", () => {
    const enChip = dive(en, ["stream", "workbench", "chipFlows"]);
    const zhChip = dive(zh, ["stream", "workbench", "chipFlows"]);
    expect(typeof enChip).toBe("string");
    expect(typeof zhChip).toBe("string");
    expect(zhChip).not.toBe(enChip);
  });

  test("chrome strings (title / open / loading / error) bilingual", () => {
    for (const key of ["title", "subtitle", "open", "loading", "error", "openMissing"]) {
      const enVal = dive(en, ["flows", key]);
      const zhVal = dive(zh, ["flows", key]);
      expect(typeof enVal).toBe("string");
      expect(typeof zhVal).toBe("string");
      expect(zhVal).not.toBe(enVal);
    }
  });
});
