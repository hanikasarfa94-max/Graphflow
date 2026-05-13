"use client";

// DocumentCard — one row in the DocumentIndex grid/list. Title +
// last-edited stamp + author + scope chip + ProjectBriefBadge when
// the doc is the pinned project brief. Clicking navigates to
// /docs/[id] — never /projects/... (DESIGN_LOCK invariant #2:
// "Project is never a page").
//
// Phase D scaffold (2026-05-13). The card is a `<Link>` wrapper so
// the whole surface is clickable; nested interactive controls (e.g. a
// future "publish" inline action) would need stopPropagation.

import Link from "next/link";

import { Card, Tag, Text } from "@/components/ui";

import { ProjectBriefBadge } from "./ProjectBriefBadge";
import type { Document } from "./types";

// Human-readable relative time. TODO(i18n) — Phase D.2 should swap to
// next-intl's <FormattedRelativeTime />.
function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86_400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86_400)}d ago`;
}

// Doc-kind labels for the secondary chip. TODO(i18n)
const KIND_LABEL: Record<NonNullable<Document["kind"]>, string> = {
  brief: "Brief",
  note: "Note",
  attachment: "Attachment",
};

export function DocumentCard({ doc }: { doc: Document }) {
  const href = `/docs/${doc.document_id}`;
  const kindLabel = doc.kind ? KIND_LABEL[doc.kind] : null;

  return (
    <Link
      href={href}
      style={{ textDecoration: "none", display: "block" }}
      // No /projects/... — strictly /docs/[id].
    >
      <Card
        // Accent rail for the pinned brief makes it stand apart from
        // notes/attachments even at a glance in the grid.
        accent={doc.is_project_brief ? "accent" : null}
        style={{
          cursor: "pointer",
          transition: "border-color var(--wg-dur-short) var(--wg-ease-enter)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {/* Top row: badges */}
          <div
            style={{
              display: "flex",
              gap: 6,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {doc.is_project_brief ? <ProjectBriefBadge /> : null}
            {kindLabel && !doc.is_project_brief ? (
              <Tag tone="neutral">{kindLabel}</Tag>
            ) : null}
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
          <Text
            as="div"
            variant="body"
            style={{
              fontSize: "var(--wg-fs-h3)",
              fontWeight: 600,
              color: "var(--wg-ink)",
              lineHeight: "var(--wg-lh-tight)",
            }}
          >
            {doc.title}
          </Text>

          {/* Attachment hint, if any */}
          {doc.attachment_hint ? (
            <Text variant="caption" muted>
              {doc.attachment_hint}
            </Text>
          ) : null}

          {/* Footer row: author + last edited */}
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              marginTop: 4,
              flexWrap: "wrap",
            }}
          >
            {doc.author ? (
              <Text variant="caption" muted>
                {/* TODO(i18n) */}
                by {doc.author.display_name}
              </Text>
            ) : null}
            <Text variant="caption" muted>
              {/* TODO(i18n) */}·{" "}
            </Text>
            <Text variant="caption" muted>
              {/* TODO(i18n) */}
              edited {formatRelative(doc.updated_at)}
            </Text>
          </div>
        </div>
      </Card>
    </Link>
  );
}
