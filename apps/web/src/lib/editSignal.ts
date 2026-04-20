// Client-side edit classifier — v1 heuristic.
//
// Why a heuristic at all? The north-star §"Direct edits are signals, not
// silent state-mutations" mandates that edits to rendered docs get
// classified into one of four kinds and, for three of those, prompt the
// human before crystallizing. The real classifier is an LLM call that
// looks at the diff + surrounding graph context; v1 ships the UX loop
// with a heuristic stand-in so we can build + demo the ceremony before
// the backend exists. When the v2 LLM endpoint lands, swap the body of
// `classifyEdit` (or proxy it) and the rest of the pipeline is unchanged.
//
// This file is intentionally dependency-free so it can be unit-tested
// without a React or Next.js harness.
//
// ---------------------------------------------------------------------
// Kinds (see docs/north-star.md §"Documents, knowledge, and edits"):
//   prose_polish      — stylistic only, auto-save, no prompt
//   semantic_reversal — edit contradicts an existing crystallized decision
//   new_content       — prose not mapped into the graph yet
//   structural_change — deadline / assignment / dependency delta
// ---------------------------------------------------------------------

export type EditKind =
  | "prose_polish"
  | "semantic_reversal"
  | "new_content"
  | "structural_change";

export type EditSignal = {
  kind: EditKind;
  // 0..1. Over 0.8 on prose_polish means "save silently". Everything
  // else prompts regardless of confidence — the prompt is the feature.
  confidence: number;
  // Tokens/patterns that fired. Surfaced in the modal so the human can
  // see *why* we think this is, e.g., a reversal.
  matchedSignals: string[];
  // Net character delta of the diff, after trim.
  delta: number;
};

// Reversal markers, EN + ZH. Kept small and high-signal on purpose —
// false positives here cost a modal prompt, false negatives cost a
// silent graph mutation. We bias toward prompting.
const REVERSAL_KEYWORDS: string[] = [
  // English
  "instead",
  "no longer",
  "reverses",
  "actually",
  "was wrong",
  "correction",
  "supersedes",
  "reverting",
  "reverted",
  "strike that",
  "scratch that",
  // Chinese
  "实际上",
  "其实",
  "改为",
  "撤销",
  "推翻",
  "不再",
  "更正",
  "修正",
  "取消",
  "废弃",
];

// Structural-change signals. Dates, assignment verbs, dependency words.
const STRUCTURAL_KEYWORDS: string[] = [
  // English
  "deadline",
  "due",
  "owner",
  "assigned to",
  "assignee",
  "depends on",
  "blocked by",
  "blocks",
  // Chinese
  "截止",
  "到期",
  "负责人",
  "指派",
  "分配给",
  "依赖",
  "阻塞",
  "交付日",
];

// Date-ish patterns. ISO-ish (2026-04-20), slash (4/20, 2026/04/20),
// month-name EN (Apr 20, April 20), Chinese (4月20日, 四月二十).
// Deliberately loose — we'd rather prompt on a false positive than miss.
const DATE_PATTERNS: RegExp[] = [
  /\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b/,
  /\b\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?\b/,
  /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b/i,
  /\d{1,2}\s*月\s*\d{1,2}\s*日/,
  /(?:今天|明天|后天|下周|本周|下月|本月)/,
];

// "@username" mention — both ASCII and CJK-safe-ish. Matches the shape
// an edit-inserted assignment would take in a markdown body.
const MENTION_PATTERN = /@[A-Za-z0-9_\u4e00-\u9fa5][\w\u4e00-\u9fa5.-]*/;

export function classifyEdit(before: string, after: string): EditSignal {
  const beforeTrim = before.trim();
  const afterTrim = after.trim();
  const delta = afterTrim.length - beforeTrim.length;
  const absDelta = Math.abs(delta);
  const diffSegment = diffTail(beforeTrim, afterTrim);
  const haystack = (diffSegment + "\n" + afterTrim).toLowerCase();

  const matchedSignals: string[] = [];

  // 1) Semantic reversal — keyword hit trumps everything else. The
  //    north-star is explicit that reversal detection is the ceremony
  //    we must not miss, so it takes priority over "this is also a big
  //    addition" or "this also has a date in it".
  for (const kw of REVERSAL_KEYWORDS) {
    if (haystack.includes(kw.toLowerCase())) {
      matchedSignals.push(`reversal:${kw}`);
    }
  }
  if (matchedSignals.length > 0) {
    return {
      kind: "semantic_reversal",
      // Confidence scales gently with how many markers fired. Caps at
      // 0.9 — we never claim certainty from a heuristic.
      confidence: Math.min(0.6 + 0.1 * matchedSignals.length, 0.9),
      matchedSignals,
      delta,
    };
  }

  // 2) Structural change — dates, mentions, assignment verbs.
  for (const kw of STRUCTURAL_KEYWORDS) {
    if (haystack.includes(kw.toLowerCase())) {
      matchedSignals.push(`structural:${kw}`);
    }
  }
  for (const re of DATE_PATTERNS) {
    if (re.test(diffSegment) || re.test(afterTrim) !== re.test(beforeTrim)) {
      matchedSignals.push(`date:${re.source.slice(0, 20)}`);
      break;
    }
  }
  if (MENTION_PATTERN.test(diffSegment)) {
    matchedSignals.push("mention");
  }
  if (matchedSignals.length > 0) {
    return {
      kind: "structural_change",
      confidence: Math.min(0.55 + 0.1 * matchedSignals.length, 0.85),
      matchedSignals,
      delta,
    };
  }

  // 3) New content — net-positive, non-trivial, no reversal markers.
  //    "Non-trivial" is 100 chars to avoid classifying a bullet-point
  //    rewrite as a new thesis.
  if (delta > 100) {
    return {
      kind: "new_content",
      confidence: Math.min(0.5 + delta / 1000, 0.85),
      matchedSignals: [`net_added:${delta}`],
      delta,
    };
  }

  // 4) Prose polish — default. High confidence only when the edit is
  //    small and doesn't insert a digit (numbers-in-prose often signal
  //    a metric change, which is a semantic edit even if no keyword
  //    fired). Otherwise drop to 0.65 so the UI still prompts.
  const insertedDigit = /\d/.test(diffSegment);
  const confidence = absDelta <= 40 && !insertedDigit ? 0.9 : 0.65;
  return {
    kind: "prose_polish",
    confidence,
    matchedSignals: absDelta <= 40 ? ["small_delta"] : ["medium_delta"],
    delta,
  };
}

// Return the substring of `after` that's past the common prefix with
// `before`, plus the common-suffix-stripped change region. This is a
// cheap stand-in for a real diff — we only need the *new* text to
// keyword-match against, and false positives are cheap here. Keeps the
// module dependency-free (no diff-match-patch).
function diffTail(before: string, after: string): string {
  let i = 0;
  const min = Math.min(before.length, after.length);
  while (i < min && before[i] === after[i]) i++;
  let jA = after.length;
  let jB = before.length;
  while (jA > i && jB > i && before[jB - 1] === after[jA - 1]) {
    jA--;
    jB--;
  }
  return after.slice(i, jA);
}
