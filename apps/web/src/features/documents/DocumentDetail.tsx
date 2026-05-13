"use client";

// DocumentDetail — client-side viewer/editor for /docs/[id].
//
// Phase D scaffold (2026-05-13). v1 renders the doc body as plain
// markdown text in view mode; switching to edit mode swaps in
// <DocumentEditor>. The edit-mode toggle is inline (no navigation),
// matching the spec: "for v1 renders a viewer; edit mode toggled
// inline."
//
// Layout — two-column: main content (viewer/editor) on the left,
// <DocumentRightRail /> on the right. The rail follows the universal
// spine per DESIGN_LOCK invariant #10.

import { useState } from "react";

import { Button, Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";

import { DocumentEditor } from "./DocumentEditor";
import { DocumentRightRail } from "./DocumentRightRail";
import { ProjectBriefBadge } from "./ProjectBriefBadge";
import { useDocument } from "./hooks";

export function DocumentDetail({ id }: { id: string }) {
  const doc = useDocument(id);
  const [editing, setEditing] = useState(false);

  if (!doc) {
    return (
      <main
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          padding: "32px 28px 80px",
        }}
      >
        <EmptyState>
          {/* TODO(i18n) */}
          Document not found.
        </EmptyState>
      </main>
    );
  }

  return (
    <main
      style={{
        maxWidth: 1280,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Documents · KB"
        title={doc.title}
        subtitle={
          doc.is_project_brief
            ? // TODO(i18n)
              "Pinned project brief. Edits propose memory candidates; acceptance is a separate decision."
            : // TODO(i18n)
              "Document. Publishing proposes memory candidates; acceptance is a separate decision."
        }
        right={
          <Button
            size="md"
            variant={editing ? "ghost" : "primary"}
            onClick={() => setEditing((e) => !e)}
          >
            {/* TODO(i18n) */}
            {editing ? "View" : "Edit"}
          </Button>
        }
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 320px",
          gap: 20,
        }}
      >
        {/* Main column */}
        <div style={{ minWidth: 0 }}>
          {editing ? (
            <DocumentEditor doc={doc} />
          ) : (
            <article style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* Header strip */}
              <div
                style={{
                  display: "flex",
                  gap: 6,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                {doc.is_project_brief ? <ProjectBriefBadge /> : null}
                <Tag tone="neutral">
                  {/* TODO(i18n) */}
                  {doc.scope_label ?? doc.scope_id}
                </Tag>
                {doc.author ? (
                  <Text variant="caption" muted>
                    {/* TODO(i18n) */}
                    by {doc.author.display_name}
                  </Text>
                ) : null}
                <Text variant="caption" muted>
                  {/* TODO(i18n) */}
                  Last edited {doc.updated_at}
                </Text>
              </div>

              {/* Body — v1 renders raw markdown; D.3 wires a real
                  markdown renderer. */}
              <Card>
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    fontFamily: "var(--wg-font-sans)",
                    fontSize: "var(--wg-fs-body)",
                    lineHeight: "var(--wg-lh-normal)",
                    color: "var(--wg-ink)",
                    margin: 0,
                  }}
                >
                  {doc.body_md ?? ""}
                </pre>
              </Card>

              <Text
                as="p"
                variant="caption"
                muted
                style={{ marginTop: 8, textAlign: "center" }}
              >
                {/* Doctrine — DESIGN_LOCK §"Hard invariants" #7. */}
                Memory crystallization is a separate decision.
              </Text>
            </article>
          )}
        </div>

        {/* Right rail */}
        <DocumentRightRail doc={doc} />
      </div>
    </main>
  );
}
