import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { DISPLAY_TZ_LABEL, formatIso, formatIsoSeconds } from "./time";

// M1.1 §4 — GMT+8 hardening regression guard.
//
// `formatIso` / `formatIsoSeconds` are the canonical timestamp
// formatters: they pin Asia/Shanghai and append a literal "GMT+8" so
// audit copy doesn't read as the browser's local time. Any direct
// `new Date(...).toLocaleString()` in apps/web outside this lib bypasses
// those guarantees — that bug shipped to prod once already (Slice D
// dogfood: tooltips showed local time without a TZ label).
//
// This test walks the apps/web source tree and asserts that no file
// outside lib/time.ts uses the offending pattern. Number formatting via
// `(0).toLocaleString()` (HealthPanel uses it for thousands separators)
// is intentionally allowed — it's not a timestamp display.

describe("time formatters output", () => {
  test("formatIso appends GMT+8 label", () => {
    const out = formatIso("2026-05-05T10:00:00Z");
    expect(out.endsWith(DISPLAY_TZ_LABEL)).toBe(true);
    expect(out).toContain("GMT+8");
  });

  test("formatIsoSeconds appends GMT+8 label", () => {
    const out = formatIsoSeconds("2026-05-05T10:00:00Z");
    expect(out.endsWith(DISPLAY_TZ_LABEL)).toBe(true);
  });
});

describe("M1.1 — no direct toLocaleString timestamp formatting", () => {
  // Anchor the walk at apps/web/src so the test runs from any cwd.
  const SRC_ROOT = join(import.meta.dir, "..");
  const TIME_LIB_PATH = join(SRC_ROOT, "lib", "time.ts");

  // Pattern: `new Date(...).toLocaleString` (with optional whitespace).
  // We deliberately don't match bare `(number).toLocaleString()` because
  // that's used legitimately for thousands separators on numbers.
  const TIMESTAMP_PATTERN =
    /new\s+Date\s*\([^)]*\)\s*\.\s*toLocale(?:String|DateString|TimeString)\b/;

  // Also forbid patterns like `someDateVar.toLocaleString(...)` when we
  // can spot them — these are typed-Date calls that bypass our pin too.
  // We restrict this stricter rule to *.tsx (component) files only since
  // *.ts files often manipulate dates as part of the lib layer itself.
  const TYPED_DATE_PATTERN =
    /:\s*Date\s*\)\s*\.\s*toLocale(?:String|DateString|TimeString)\b/;

  function* walkSource(dir: string): Generator<string> {
    for (const name of readdirSync(dir)) {
      // Skip framework-managed and hidden dirs.
      if (name === "node_modules" || name === ".next" || name.startsWith("."))
        continue;
      const full = join(dir, name);
      const stat = statSync(full);
      if (stat.isDirectory()) {
        yield* walkSource(full);
      } else if (
        (full.endsWith(".tsx") || full.endsWith(".ts")) &&
        !full.endsWith(".test.ts") &&
        !full.endsWith(".test.tsx")
      ) {
        yield full;
      }
    }
  }

  test("no `new Date(...).toLocaleString()` outside lib/time.ts", () => {
    const violations: string[] = [];
    for (const file of walkSource(SRC_ROOT)) {
      if (file === TIME_LIB_PATH) continue; // own implementation file
      const text = readFileSync(file, "utf-8");
      // Strip line comments — the `// new Date(...).toLocaleString()`
      // doc comment in time.ts isn't the kind of violation we mean,
      // and other files may reference the pattern in commentary too.
      const stripped = text
        .split("\n")
        .map((line) => {
          const idx = line.indexOf("//");
          return idx >= 0 ? line.slice(0, idx) : line;
        })
        .join("\n");
      if (TIMESTAMP_PATTERN.test(stripped)) {
        violations.push(file);
      }
    }
    expect(violations).toEqual([]);
  });

  test("no `(d: Date).toLocaleString()` in components", () => {
    const violations: string[] = [];
    for (const file of walkSource(SRC_ROOT)) {
      if (!file.endsWith(".tsx")) continue;
      const text = readFileSync(file, "utf-8");
      if (TYPED_DATE_PATTERN.test(text)) {
        violations.push(file);
      }
    }
    expect(violations).toEqual([]);
  });
});
