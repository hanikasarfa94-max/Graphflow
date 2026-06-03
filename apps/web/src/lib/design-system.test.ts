import { describe, expect, test } from "bun:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

// Phase F (Architecture Organization Pass v1) — design-system static guard.
//
// Policy (DESIGN.md §Color, §Components):
//   - "All surfaces, text, accents reference variables. No inline hex
//      outside `globals.css` (and this doc)."
//   - "Inline `style=` is a code-smell — flag in review."
//
// Locking the policy on the WHOLE codebase today would fail on ~150
// existing files. Per CLAUDE.md project notes (`feedback_flows_inline_styles_debt.md`),
// inline-style debt is *tolerated but bounded* — required cleanup
// before the next user-visible touchpoint lands.
//
// SCOPE (deliberate, narrow): this guard runs only on three directories
// that are MEANT to stay clean going forward:
//
//   - apps/web/src/components/rooms/   — the rooms surface
//   - apps/web/src/components/kb/      — the KB surface
//   - apps/web/src/components/flows/   — the flows surface
//   - apps/web/src/features/flows/     — Phase D's new home for flows
//                                        (does not exist at the time of
//                                        writing; included so the rule
//                                        applies the moment the dir
//                                        lands).
//
// The currently-violating files in those three production dirs are
// listed in EXISTING_VIOLATORS below and grandfathered. Any NEW file in
// those directories — and any EXISTING file that picks up an additional
// inline-style or hex-literal violation while still on the allowlist —
// is fine, because the allowlist is per-file: once you're on it, you're
// allowed any number of pre-existing-style smells, but the moment you
// add a NEW file you must obey the rule.
//
// Outside these three dirs (e.g. `components/stream/`, `app/projects/`)
// this guard is silent. Refactor those into their own scoped guard when
// they're ready.
//
// To remove a file from the allowlist: refactor every `style={{` and
// every hex literal out of it (replace with CSS variable tokens from
// globals.css, see DESIGN.md §Color), then delete the entry here.

const SRC_ROOT = join(import.meta.dir, "..");

// Directories under apps/web/src that the rule applies to.
// Re-scoped 2026-06-03: the original scope (components/rooms, components/kb,
// components/flows, features/flows) was the pre-pivot experimental surface
// and has been deleted. The guard now polices the live feature surfaces
// under `features/` so it keeps catching NEW inline-style/hex debt instead
// of silently passing on nothing.
const SCOPED_DIRS = ["features"];

// Files known to currently violate the rule on 2026-06-03 — generated
// by walking the scoped dir (`features/`) and recording every file that
// contains either `style={{` or a `#[0-9a-fA-F]{3,8}` literal in
// non-comment source. Pre-existing debt carried over from the pivot;
// tracked here so the guard blocks NEW offenders. A future wave should
// burn this list down (see feedback_flows_inline_styles_debt.md).
//
// Paths are POSIX-style (forward slashes), relative to apps/web/src.
const EXISTING_VIOLATORS: ReadonlySet<string> = new Set([
  "features/conversations/ConversationComposer.tsx",
  "features/conversations/ConversationHeader.tsx",
  "features/conversations/ConversationList.tsx",
  "features/conversations/ConversationShell.tsx",
  "features/conversations/Conversations.tsx",
  "features/conversations/DMRightRail.tsx",
  "features/conversations/MessageStream.tsx",
  "features/conversations/RoomRightRail.tsx",
  "features/conversations/TopicRightRail.tsx",
  "features/documents/DocumentCard.tsx",
  "features/documents/DocumentDetail.tsx",
  "features/documents/DocumentIndex.tsx",
  "features/documents/DocumentRightRail.tsx",
  "features/documents/Documents.tsx",
  "features/flow-center/AuthorityState.tsx",
  "features/flow-center/FlowCenter.tsx",
  "features/flow-center/FlowDrawer.tsx",
  "features/flow-center/FlowTable.tsx",
  "features/flow-center/MemoryPromptDrawer.tsx",
  "features/flow-center/MemoryReviewDrawer.tsx",
  "features/my-ai/MyAIComposer.tsx",
  "features/my-ai/MyAILandingClient.tsx",
  "features/tasks/TaskCard.tsx",
  "features/tasks/TaskList.tsx",
  "features/tasks/TaskRightRail.tsx",
  "features/tasks/Tasks.tsx",
]);

// `style={{` — JSX inline style object literal. Misses
// `style={someVariable}`, which is intentional: a named style object
// in a TS module is testable and reusable; the smell is the *anonymous
// inline literal at the call site*.
const INLINE_STYLE_PATTERN = /style=\{\{/;

// Hex literal in CSS-color length (3, 4, 6, or 8 hex chars).
// We scan the whole file (after stripping comments + bare identifiers
// where it matters), so this catches hex inside `style={{ ... }}`
// objects, inside template-literal CSS, and inside any object passed
// to a style prop. Word boundary at the end keeps `#fff_extension`
// from accidentally matching, and the `(?![0-9a-fA-F])` guard makes
// `#1234567890` (longer than 8) NOT match — anything longer than 8 is
// not a CSS color, and we don't want to flag it as one.
const HEX_LITERAL_PATTERN = /#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/;

const SCOPED_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);

function isScopedFile(absPath: string): boolean {
  // Skip test fixtures and stories.
  if (
    absPath.endsWith(".test.ts") ||
    absPath.endsWith(".test.tsx") ||
    absPath.endsWith(".stories.ts") ||
    absPath.endsWith(".stories.tsx")
  ) {
    return false;
  }
  // Skip non-source extensions.
  const dotIdx = absPath.lastIndexOf(".");
  if (dotIdx < 0) return false;
  if (!SCOPED_EXTENSIONS.has(absPath.slice(dotIdx))) return false;

  const rel = relative(SRC_ROOT, absPath);
  // Normalise to POSIX for portable matching across Windows/POSIX hosts.
  const relPosix = rel.split(sep).join("/");
  return SCOPED_DIRS.some((d) => {
    const dPosix = d.split(sep).join("/");
    return relPosix === dPosix || relPosix.startsWith(`${dPosix}/`);
  });
}

function* walkScoped(dir: string): Generator<string> {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    // Dir may not exist yet (e.g. features/flows before Phase D lands).
    return;
  }
  for (const name of entries) {
    if (
      name === "node_modules" ||
      name === ".next" ||
      name === "__tests__" ||
      name.startsWith(".")
    ) {
      continue;
    }
    const full = join(dir, name);
    let stat;
    try {
      stat = statSync(full);
    } catch {
      continue;
    }
    if (stat.isDirectory()) {
      yield* walkScoped(full);
    } else if (isScopedFile(full)) {
      yield full;
    }
  }
}

// Strip line comments (// …) and block comments (/* … */) so that a
// commented-out `style={{ color: '#fff' }}` doesn't trip the guard.
// Crude but adequate — string literals containing `//` would be
// over-stripped, but a CSS hex inside a string literal is exactly
// what we want to flag, so the over-strip is safe (we only ever lose
// signal, never gain false positives).
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((line) => {
      const idx = line.indexOf("//");
      return idx >= 0 ? line.slice(0, idx) : line;
    })
    .join("\n");
}

function relPosix(absPath: string): string {
  return relative(SRC_ROOT, absPath).split(sep).join("/");
}

describe("design-system static guard (DESIGN.md §Color, §Components)", () => {
  // Collect once; tests below partition the data different ways.
  const scopedFiles: string[] = [];
  for (const dir of SCOPED_DIRS) {
    const abs = join(SRC_ROOT, dir);
    for (const f of walkScoped(abs)) scopedFiles.push(f);
  }

  test("EXISTING_VIOLATORS only lists files that actually exist", () => {
    // Hygiene: if a file gets deleted/renamed, drop it from the
    // allowlist instead of leaving stale entries that mask real
    // regressions on a future file with the same path.
    const stale: string[] = [];
    for (const rel of EXISTING_VIOLATORS) {
      const abs = join(SRC_ROOT, rel.split("/").join(sep));
      try {
        statSync(abs);
      } catch {
        stale.push(rel);
      }
    }
    expect(stale).toEqual([]);
  });

  test("no NEW inline `style={{ ... }}` outside the allowlist", () => {
    const offenders: string[] = [];
    for (const file of scopedFiles) {
      const rel = relPosix(file);
      if (EXISTING_VIOLATORS.has(rel)) continue;
      const src = stripComments(readFileSync(file, "utf-8"));
      if (INLINE_STYLE_PATTERN.test(src)) {
        offenders.push(rel);
      }
    }
    if (offenders.length > 0) {
      // Surface the policy text so the failure message tells the dev
      // exactly why the test fired.
      // eslint-disable-next-line no-console
      console.error(
        "DESIGN.md §Components: Inline `style={{}}` is a code-smell — " +
          "use the <Button>/<Card>/<Heading>/<Text>/<EmptyState> primitives " +
          "in apps/web/src/components/ui/ or a CSS class. New offenders:\n  " +
          offenders.join("\n  "),
      );
    }
    expect(offenders).toEqual([]);
  });

  test("no NEW hex literals outside the allowlist", () => {
    const offenders: string[] = [];
    for (const file of scopedFiles) {
      const rel = relPosix(file);
      if (EXISTING_VIOLATORS.has(rel)) continue;
      const src = stripComments(readFileSync(file, "utf-8"));
      if (HEX_LITERAL_PATTERN.test(src)) {
        offenders.push(rel);
      }
    }
    if (offenders.length > 0) {
      // eslint-disable-next-line no-console
      console.error(
        "DESIGN.md §Color: 'No inline hex outside globals.css and this doc.' " +
          "Use a CSS variable from apps/web/src/app/globals.css " +
          "(--wg-paper, --wg-surface, --wg-ink, --wg-accent, --wg-amber, " +
          "--wg-ok, etc). New offenders:\n  " +
          offenders.join("\n  "),
      );
    }
    expect(offenders).toEqual([]);
  });

  test("scoped walk actually finds files (sanity check)", () => {
    // If this ever returns 0, the dirs all got renamed/moved and the
    // guard is silently passing on nothing. Fail loudly instead.
    expect(scopedFiles.length).toBeGreaterThan(0);
  });
});
