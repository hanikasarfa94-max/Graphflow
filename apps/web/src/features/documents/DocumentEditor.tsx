"use client";

// DocumentEditor — title + body editor for /docs/[id].
//
// Phase D scaffold (2026-05-13). v1 uses a plain `<textarea>` for the
// body; the rich-text editor (slate/tiptap) is deferred to Phase D.3.
// The doctrine-bearing piece is the **publish flow**:
//
//   1. POST /api/documents/{id}/publish returns `memory_candidates`
//   2. The surface MUST surface these as **proposals**, never
//      auto-accept (DESIGN_LOCK invariants #4, #7).
//   3. Each candidate opens MemoryReviewDrawer via useDrawer().
//      Acceptance happens inside the drawer with server-side
//      authority — never here.
//
// Sticky footer at the bottom carries the Publish CTA. On success, a
// Card appears below (or above the footer) with "Memory candidates
// detected" and one button per candidate to open the review drawer.

import { useState } from "react";

import { Button, Card, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

import { ProjectBriefBadge } from "./ProjectBriefBadge";
import type {
  Document,
  DocumentPublishResponse,
  MemoryCandidateProposal,
} from "./types";

// TODO(phase-d.2): replace with real
//   `POST /api/documents/:id/publish`
// returning a `DocumentPublishResponse`. Phase D fakes two memory
// candidates so the prompt + drawer routing can be exercised
// end-to-end without the backend.
function usePublishDocument(): (
  id: string,
) => Promise<DocumentPublishResponse> {
  return async (id: string) => {
    // Simulate network so the user sees the "Publishing…" state.
    await new Promise((r) => setTimeout(r, 240));
    return {
      document: {
        document_id: id,
        scope_id: "scope_tikhub",
        scope_label: "TikHub",
        title: "(stub)",
        scope: "group",
        status: "published",
        is_project_brief: false,
        kind: "note",
        updated_at: new Date().toISOString(),
        created_at: "2026-05-10T12:30:00Z",
      },
      memory_candidates: [
        {
          candidate_id: `memcand_${id}_a`,
          proposed_atom_preview:
            "Q3 launch date locked to 2026-09-18; marketing schedule depends on it.",
        },
        {
          candidate_id: `memcand_${id}_b`,
          proposed_atom_preview:
            "Acme contract renewal requires VP-ops approval before EOD Thursday.",
        },
      ],
      mutates_state: true,
    };
  };
}

export function DocumentEditor({ doc }: { doc: Document }) {
  const drawer = useDrawer();
  const publish = usePublishDocument();

  const [title, setTitle] = useState(doc.title);
  const [body, setBody] = useState(doc.body_md ?? "");
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<DocumentPublishResponse | null>(
    null,
  );

  async function handlePublish() {
    if (publishing) return;
    setPublishing(true);
    try {
      const result = await publish(doc.document_id);
      // Doctrine — publish does NOT auto-accept memory. We just
      // surface the candidates for the user to review.
      setPublishResult(result);
    } finally {
      setPublishing(false);
    }
  }

  function openCandidate(c: MemoryCandidateProposal) {
    drawer.open({
      type: "memory_review",
      props: { candidate_id: c.candidate_id },
    });
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        // Reserve room at the bottom for the sticky footer so the
        // last content line isn't visually clipped.
        paddingBottom: 80,
      }}
    >
      {/* Header strip — badges + scope */}
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        {doc.is_project_brief ? <ProjectBriefBadge /> : null}
        <Tag tone="neutral">
          {/* TODO(i18n) */}
          {doc.scope_label ?? doc.scope_id}
        </Tag>
        {doc.status === "draft" ? (
          <Tag tone="amber">
            {/* TODO(i18n) */}
            Draft
          </Tag>
        ) : null}
      </div>

      {/* Title */}
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        // TODO(i18n)
        placeholder="Document title"
        style={{
          width: "100%",
          fontSize: "var(--wg-fs-h1)",
          fontFamily: "var(--wg-font-sans)",
          fontWeight: 600,
          color: "var(--wg-ink)",
          background: "transparent",
          border: "none",
          outline: "none",
          padding: "4px 0",
          letterSpacing: "-0.01em",
        }}
      />

      {/* Body — v1 textarea; rich editor in Phase D.3 */}
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        // TODO(i18n)
        placeholder="Write the document body. Markdown is honored at render time."
        rows={18}
        style={{
          width: "100%",
          padding: 14,
          borderRadius: "var(--wg-radius)",
          border: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          fontFamily: "var(--wg-font-sans)",
          fontSize: "var(--wg-fs-body)",
          color: "var(--wg-ink)",
          lineHeight: "var(--wg-lh-normal)",
          resize: "vertical",
          minHeight: 320,
        }}
      />

      {/* Post-publish surfaced candidates — proposal-only, never
          auto-accepted. Each candidate opens MemoryReviewDrawer. */}
      {publishResult && publishResult.memory_candidates.length > 0 ? (
        <Card accent="accent" title="Memory candidates detected">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Text variant="body">
              {/* TODO(i18n) */}
              Publishing surfaced {publishResult.memory_candidates.length}{" "}
              proposed memory{" "}
              {publishResult.memory_candidates.length === 1 ? "atom" : "atoms"}.
              Acceptance is a separate decision — review each one before
              it crystallizes.
            </Text>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {publishResult.memory_candidates.map((c) => (
                <Card key={c.candidate_id} variant="sunk">
                  <div
                    style={{
                      display: "flex",
                      gap: 12,
                      alignItems: "flex-start",
                      justifyContent: "space-between",
                    }}
                  >
                    <Text as="p" variant="body" style={{ flex: 1 }}>
                      {c.proposed_atom_preview}
                    </Text>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => openCandidate(c)}
                    >
                      {/* TODO(i18n) */}
                      Review
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
            <Text variant="caption" muted>
              {/* TODO(i18n) — doctrine */}
              Publish proposed these — it did not accept them. Memory
              crystallization is a separate decision.
            </Text>
          </div>
        </Card>
      ) : publishResult ? (
        <Card variant="sunk">
          <Text variant="caption" muted>
            {/* TODO(i18n) */}
            Published. No memory candidates were surfaced from this
            revision.
          </Text>
        </Card>
      ) : null}

      {/* Sticky CTA footer — the only state-changing surface on this
          screen. Mirrors FlowDrawer's footer composition. */}
      <footer
        style={{
          position: "sticky",
          bottom: 0,
          marginTop: 4,
          paddingTop: 12,
          paddingBottom: 12,
          borderTop: "1px solid var(--wg-line)",
          background: "var(--wg-surface)",
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
          zIndex: 1,
        }}
      >
        <Text
          variant="caption"
          muted
          style={{ marginRight: "auto", alignSelf: "center" }}
        >
          {/* TODO(i18n) */}
          Publish proposes memory; it never accepts memory.
        </Text>
        <Button variant="ghost" size="md" onClick={() => undefined}>
          {/* TODO(i18n) — Phase D.2 wires Save-as-draft via PATCH */}
          Save draft
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={handlePublish}
          disabled={publishing}
        >
          {/* TODO(i18n) */}
          {publishing ? "Publishing…" : "Publish"}
        </Button>
      </footer>
    </div>
  );
}
