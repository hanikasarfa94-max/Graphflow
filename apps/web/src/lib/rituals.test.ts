import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  RITUALS,
  expandRitual,
  filterRituals,
  findRitualByCommand,
} from "./rituals";

// Locale files are the canonical source of i18n keys; the rituals
// catalog references keys under `rituals.{id}` and `roles.{role}`. This
// test enforces lockstep so we can never ship a ritual that renders as
// "rituals.save.label" because the zh file forgot the key.

const LOCALES_DIR = join(import.meta.dir, "..", "i18n", "locales");

function loadLocale(file: string): Record<string, unknown> {
  const raw = readFileSync(join(LOCALES_DIR, file), "utf-8");
  return JSON.parse(raw);
}

describe("rituals catalog", () => {
  test("exports the six first-cut rituals in stable order", () => {
    const ids = RITUALS.map((r) => r.id);
    expect(ids).toEqual([
      "save",
      "route",
      "risk",
      "why",
      "handoff",
      "crystallize",
    ]);
  });

  test("every ritual has both en + zh template strings", () => {
    for (const ritual of RITUALS) {
      expect(ritual.template.en.length).toBeGreaterThan(0);
      expect(ritual.template.zh.length).toBeGreaterThan(0);
      // Template must contain the {arg} slot — pickRitual relies on it
      // for caret placement, and send() suppresses unfilled drafts by
      // looking for the literal substring.
      expect(ritual.template.en).toContain("{arg}");
      expect(ritual.template.zh).toContain("{arg}");
    }
  });

  test("findRitualByCommand resolves each registered command", () => {
    for (const ritual of RITUALS) {
      expect(findRitualByCommand(ritual.command)?.id).toBe(ritual.id);
    }
    expect(findRitualByCommand("/nope")).toBeUndefined();
  });

  test("filterRituals — empty / single-slash returns the full catalog", () => {
    expect(filterRituals("").length).toBe(RITUALS.length);
    expect(filterRituals("/").length).toBe(RITUALS.length);
  });

  test("filterRituals — prefix narrows the catalog", () => {
    const result = filterRituals("/sa");
    expect(result.map((r) => r.id)).toEqual(["save"]);
    const noMatch = filterRituals("/zzz");
    expect(noMatch.length).toBe(0);
  });

  test("expandRitual substitutes {arg}", () => {
    const save = RITUALS.find((r) => r.id === "save")!;
    const out = expandRitual(save, "the auth thread", "en");
    expect(out).toContain("the auth thread");
    expect(out).not.toContain("{arg}");
  });
});

describe("rituals i18n contract", () => {
  const en = loadLocale("en.json");
  const zh = loadLocale("zh.json");

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

  test("each ritual id has label + hint in BOTH locales", () => {
    for (const ritual of RITUALS) {
      const enLabel = dive(en, ["rituals", ritual.i18nKey, "label"]);
      const zhLabel = dive(zh, ["rituals", ritual.i18nKey, "label"]);
      const enHint = dive(en, ["rituals", ritual.i18nKey, "hint"]);
      const zhHint = dive(zh, ["rituals", ritual.i18nKey, "hint"]);
      expect(typeof enLabel).toBe("string");
      expect(typeof zhLabel).toBe("string");
      expect(typeof enHint).toBe("string");
      expect(typeof zhHint).toBe("string");
      // Catch the "translator pasted English into zh.json" case.
      expect(zhLabel).not.toBe(enLabel);
      expect(zhHint).not.toBe(enHint);
    }
  });

  test("each role label exists in BOTH locales", () => {
    const roles = new Set(RITUALS.map((r) => r.role));
    for (const role of roles) {
      const enRole = dive(en, ["roles", role]);
      const zhRole = dive(zh, ["roles", role]);
      expect(typeof enRole).toBe("string");
      expect(typeof zhRole).toBe("string");
      expect(zhRole).not.toBe(enRole);
    }
  });

  test("menu chrome (title / hint / argHintPrefix / noMatch) bilingual", () => {
    for (const key of ["menuTitle", "menuHint", "argHintPrefix", "noMatch"]) {
      expect(typeof dive(en, ["rituals", key])).toBe("string");
      expect(typeof dive(zh, ["rituals", key])).toBe("string");
      expect(dive(zh, ["rituals", key])).not.toBe(dive(en, ["rituals", key]));
    }
  });
});
