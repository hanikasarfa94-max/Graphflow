import { describe, expect, test } from "bun:test";

// =============================================================================
// v0.6.2 invariant tests — codifies the 5-surface IA pivot doctrine.
//
// Spec: graphflow_handoff_v062/INVARIANT_TESTS.md
//
// These tests are written ahead of the implementation. Most are `test.todo`
// placeholders — the assertions cannot be made today because the endpoints
// (Phase B) and the new shell (Phase A) don't exist yet. As each phase lands,
// flip the corresponding `test.todo` into a real `test(...)` and remove the
// Phase-X comment.
//
// Pivot summary:
//   - From: project-stream-centered shell (rooms, project stream as primary)
//   - To:   5 primary nav items — My AI / Conversations / Tasks /
//           Documents · KB / Flow Center
//   - Projects become a scoping concept, not a routable page. The user reads
//     the "project brief" as a Document, not as a /projects/[id] route.
//   - AI Assistance is read-only — it proposes, the human commits.
//   - Memory candidates are decoupled from flow responses: review / skip /
//     later, with full lineage and authority enforcement on accept.
//
// Phase legend (from handoff doc):
//   A.2 — new sidebar / primary nav ships
//   A.4 — /projects/[id] page removed; brief lives as a Document
//   B.1 — /api/create-menu lands
//   B.2 — /api/ai-assistance/run lands (read-only proposal contract)
//   B.3 — /api/memory-candidates/* lands (review / skip / later / accept)
//   B.4 — /api/flow-requests/{id}/respond decouples memory creation
//   B.5 — /api/conversations adds active_topics + recent dedup
//   B.6 — /api/scopes/{id}/project-brief returns document_id
// =============================================================================

describe("v0.6.2 — primary nav invariant", () => {
  // Activates in Phase A.2 (new sidebar). The new shell must expose exactly
  // these five items in this order, and must NOT expose any of the legacy
  // surface names that the pivot retires.
  test.todo(
    "primary nav has exactly [My AI, Conversations, Tasks, Documents / KB, Flow Center] in order",
  );
  test.todo(
    "primary nav excludes legacy items: Project, Graph, Memory, Capability, Embedded Views",
  );
});

describe("v0.6.2 — create menu invariant", () => {
  // Activates in Phase B.1 (/api/create-menu). The "+" menu is the only
  // place a user creates entities directly. Tasks, topics, flow_requests,
  // and memory entries are all DERIVED — they must never appear as a
  // direct-creation option.
  test.todo(
    "GET /api/create-menu returns items [conversation, document, upload, project_scope]",
  );
  test.todo(
    "GET /api/create-menu excluded_direct_creations is [task, topic, flow_request, memory]",
  );
});

describe("v0.6.2 — AI Assistance is read-only", () => {
  // Activates in Phase B.2 (/api/ai-assistance/run). The single hardest
  // invariant of the pivot: AI proposes, human commits. Any run that
  // returns mutates_state:true is a doctrine violation.
  test.todo(
    "POST /api/ai-assistance/run returns mutates_state=false and a proposal",
  );
});

describe("v0.6.2 — flow response decouples memory creation", () => {
  // Activates in Phase B.4 (/api/flow-requests/{id}/respond). Responding to
  // a flow request must NEVER auto-accept a memory candidate. The user is
  // prompted with review / skip / later — never silently mutated.
  test.todo(
    "POST /api/flow-requests/{id}/respond surfaces memory_candidate_prompt with actions [review, skip, later]",
  );
  test.todo(
    "POST /api/flow-requests/{id}/respond never sets memory_auto_accepted=true",
  );
});

describe("v0.6.2 — later defers a candidate", () => {
  // Activates in Phase B.3 (/api/memory-candidates/{id}/defer). "Later" is a
  // first-class lifecycle state, not a UI affordance over the same row.
  test.todo(
    "POST /api/memory-candidates/{id}/defer transitions status to 'deferred'",
  );
});

describe("v0.6.2 — skip is reversible", () => {
  // Activates in Phase B.3. Skipping must not be terminal — the source
  // flow response must still expose generate_memory_candidate so the user
  // can change their mind without re-running the conversation.
  test.todo(
    "after POST /api/memory-candidates/{id}/skip, the source flow response still offers generate_memory_candidate",
  );
});

describe("v0.6.2 — authority is enforced on accept", () => {
  // Activates in Phase B.3. Accepting a memory candidate is an authoritative
  // act. Project members cannot accept; only the role with authority for
  // the candidate's domain (e.g. pricing_owner) can. 403 with
  // error="authority_required" is the contract.
  test.todo(
    "POST /api/memory-candidates/{id}/accept as project_member returns 403 authority_required",
  );
});

describe("v0.6.2 — memory lineage is required", () => {
  // Activates in Phase B.3. Every accepted memory must carry the chain:
  //   verbatim_source_id  → the raw utterance / artifact it came from
  //   ai_distillation_id  → the AI proposal that compressed it
  //   accepted_by         → the human authority who committed
  // Missing any link is a doctrine violation — memory without lineage is
  // un-auditable.
  test.todo(
    "POST /api/memory-candidates/{id}/accept response includes lineage.{verbatim_source_id, ai_distillation_id, accepted_by}",
  );
});

describe("v0.6.2 — compression analysis carries a caveat", () => {
  // Activated 2026-05-13 by RW-3.3.
  //
  // The backend side of this invariant lives at
  //   apps/api/tests/test_rw3_memory_candidate_actions.py
  //     ::test_compression_analysis_caveat_contains_does_not_guarantee
  // which exercises the real `GET /api/memory-candidates/:id` path
  // and asserts the caveat string contains "does not guarantee".
  //
  // The FE-side companion below is a structural check: the
  // MemoryReviewDrawer must render `candidate.compression_analysis
  // .caveat` verbatim. If a future refactor swaps it for a hardcoded
  // string or paraphrases it, the bun:test below catches the
  // regression even before integration tests run.
  test("MemoryReviewDrawer renders compression_analysis.caveat verbatim", async () => {
    const path = "src/features/flow-center/MemoryReviewDrawer.tsx";
    const src = await Bun.file(path).text();
    // The component must render the server-supplied caveat string
    // (not a hardcoded paraphrase). The grep target is the
    // candidate.compression_analysis.caveat property access inside a
    // JSX expression.
    expect(src.includes("candidate.compression_analysis.caveat")).toBe(true);
    // And no hardcoded paraphrase should sneak in. The doctrine
    // string is "does not guarantee"; a refactor that hard-codes it
    // would defeat the contract.
    expect(src.includes("does not guarantee")).toBe(false);
  });
});

describe("v0.6.2 — conversations dedupe active topics from recent", () => {
  // Activates in Phase B.5. The Conversations surface shows `recent` and
  // `active_topics` as separate buckets; a topic that's already in `recent`
  // must not also appear in `active_topics`, or the user sees the same
  // conversation twice.
  test.todo(
    "GET /api/conversations?scope_id=... — no id appears in both recent and active_topics",
  );
});

describe("v0.6.2 — project is not routable as a page", () => {
  // Activated 2026-05-13 by the Phase A.4 cutover. The /projects/[id]
  // tree was deleted entirely; any request must return 404. This test
  // can't make a live HTTP request from bun:test (no test server), so
  // it asserts the file-system invariant: no /projects/[id] route
  // exists in the Next.js app/ directory. The build itself enforces
  // the runtime 404 — if any project page.tsx came back, this would
  // fail.
  test("no /projects/[id] route file exists after the Phase A.4 cutover", async () => {
    // Bun.Glob — synchronous file-system glob. Asserts there's no
    // page.tsx anywhere under apps/web/src/app/projects/. The build
    // itself enforces the runtime 404; this is a structural canary.
    const glob = new Bun.Glob("projects/**/page.tsx");
    const matches: string[] = [];
    // CWD when `bun test` runs is the package root (apps/web). Anchor
    // explicitly so the test passes regardless of how it's invoked.
    for (const file of glob.scanSync({ cwd: "src/app" })) {
      matches.push(file);
    }
    expect(matches).toEqual([]);
  });
  test.todo(
    "GET /api/scopes/{scope_id}/project-brief returns a document_id (Phase B.6)",
  );
});

// =============================================================================
// Sanity test — proves the file is wired into `bun test` and counted.
// Without this, a misconfigured test runner would silently report 0 tests
// and we'd never notice the todos aren't being tracked.
// =============================================================================

describe("v0.6.2 invariants — file is wired", () => {
  test("placeholder file loads and bun:test is reachable", () => {
    expect(true).toBe(true);
  });
});
