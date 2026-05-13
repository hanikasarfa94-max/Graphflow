// RW-8 — Documents feature safety / structural tests.
//
// Guarantees:
//   1. The Phase D MOCK_DOCUMENTS array + useDocuments / useDocument /
//      useProjectBrief / useDocumentRightRail / useAiAssistance mock
//      hooks are gone.
//   2. The DocumentEditor surface and hooks.ts module are deleted.
//   3. /docs + /docs/[id] consume the live API.
//   4. No fabricated document ids / authors / linked tasks / decisions
//      from the Phase D scaffold survive in the source.

import { describe, expect, test } from "bun:test";

describe("RW-8 — Documents mock data is gone", () => {
  test("DocumentIndex.tsx has no MOCK_DOCUMENTS array", async () => {
    const src = await Bun.file(
      "src/features/documents/DocumentIndex.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    expect(stripped.includes("MOCK_DOCUMENTS")).toBe(false);
    expect(/function\s+useDocuments\s*\(/.test(stripped)).toBe(false);
    expect(/export\s+function\s+useDocuments\s*\(/.test(stripped)).toBe(
      false,
    );
  });

  test("hooks.ts module has been removed", async () => {
    const file = Bun.file("src/features/documents/hooks.ts");
    expect(await file.exists()).toBe(false);
  });

  test("DocumentEditor.tsx has been removed (no mutation in this slice)", async () => {
    const file = Bun.file("src/features/documents/DocumentEditor.tsx");
    expect(await file.exists()).toBe(false);
  });

  test("DocumentDetail.tsx has no useDocument mock or inline editor", async () => {
    const src = await Bun.file(
      "src/features/documents/DocumentDetail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    expect(/function\s+useDocument\s*\(/.test(stripped)).toBe(false);
    expect(stripped.includes("useDocument(")).toBe(false);
    expect(stripped.includes("DocumentEditor")).toBe(false);
    expect(stripped.includes('setEditing')).toBe(false);
  });

  test("DocumentRightRail.tsx has no fabricated related-work / evidence / AI proposals", async () => {
    const src = await Bun.file(
      "src/features/documents/DocumentRightRail.tsx",
    ).text();
    const stripped = src.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, "");
    expect(/function\s+useDocumentRightRail\s*\(/.test(stripped)).toBe(
      false,
    );
    expect(/function\s+useAiAssistance\s*\(/.test(stripped)).toBe(false);
  });
});

describe("RW-8 — Documents pages consume real endpoint", () => {
  test("/docs page does server-side fetch on /api/documents", async () => {
    const src = await Bun.file("src/app/docs/page.tsx").text();
    expect(src.includes("serverFetch")).toBe(true);
    expect(src.includes("/api/documents")).toBe(true);
  });

  test("/docs/[id] page does server-side fetch on /api/documents/:id", async () => {
    const src = await Bun.file("src/app/docs/[id]/page.tsx").text();
    expect(src.includes("serverFetch")).toBe(true);
    expect(src.includes("/api/documents/")).toBe(true);
  });
});

describe("RW-8 — fabricated mock ids are gone from Documents feature", () => {
  const FABRICATED = [
    // mock doc ids
    "doc_brief_tikhub",
    "doc_note_layout_v3",
    "doc_note_pricing",
    "doc_attach_vendor_pdf",
    "doc_kb_onboarding",
    "doc_personal_draft",
    // mock authors
    "user_mei",
    "user_alex",
    "user_ravi",
    "user_jess",
    "user_priya",
    // mock scopes
    "scope_tikhub",
    "scope_growth",
    // Phase D rail synthetic refs
    "task_marketing_calendar",
    "topic_launch_date",
    "dec_launch_sep18",
    "msg_4218",
  ];

  const FILES = [
    "src/features/documents/types.ts",
    "src/features/documents/Documents.tsx",
    "src/features/documents/DocumentIndex.tsx",
    "src/features/documents/DocumentCard.tsx",
    "src/features/documents/DocumentDetail.tsx",
    "src/features/documents/DocumentRightRail.tsx",
    "src/features/documents/ProjectBriefBadge.tsx",
    "src/app/docs/page.tsx",
    "src/app/docs/[id]/page.tsx",
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

describe("RW-8 — Publish + AI Assistance are honest empty", () => {
  test("DocumentRightRail surfaces notWiredAi and notWiredPublish keys", async () => {
    const src = await Bun.file(
      "src/features/documents/DocumentRightRail.tsx",
    ).text();
    expect(src.includes("notWiredAi")).toBe(true);
    expect(src.includes("notWiredPublish")).toBe(true);
  });

  test("DocumentDetail does not call POST /publish", async () => {
    const src = await Bun.file(
      "src/features/documents/DocumentDetail.tsx",
    ).text();
    expect(src.includes("/publish")).toBe(false);
    expect(src.includes("method: \"POST\"")).toBe(false);
  });
});
