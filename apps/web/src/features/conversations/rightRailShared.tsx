"use client";

// rightRailShared — common spine primitives for the three right rails
// (DMRightRail / RoomRightRail / TopicRightRail).
//
// Per DESIGN_LOCK.md hard invariant #10:
//
//   Right rail follows shared spine:
//     Context / Related Work / Evidence / AI Assistance / CTA
//
// All three conversation right rails share this spine; only the
// content and the primary CTA differ. Keeping the section primitives
// in one place stops the three drawers from drifting visually.
//
// AI Assistance doctrine (DESIGN_LOCK.md #4 + API_CONTRACT.md):
//   AI Assistance returns proposals only. Buttons here open the
//   proposal in DrawerHost via useDrawer() — they NEVER mutate state.
//
// Evidence links use the new global URL patterns (no /projects/...):
//   /nodes/[id], /decisions/[id], /docs/[id], /kb-items/[id],
//   /scopes/[id], /conversations/[id].

import Link from "next/link";

import { Button, Card, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

// ── Section primitive ────────────────────────────────────────────────

export function RailSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Card title={title}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {children}
      </div>
    </Card>
  );
}

// ── Context (label/value pair list) ──────────────────────────────────

export interface ContextRow {
  label: string;
  value: string;
}

export function ContextSection({ rows }: { rows: ContextRow[] }) {
  return (
    // TODO(i18n): shellV062.conversations.rightRail.context
    <RailSection title="Context">
      {rows.length === 0 ? (
        <Text variant="caption" muted>
          No context yet.
        </Text>
      ) : (
        rows.map((row) => (
          <div
            key={row.label}
            style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
          >
            <Text variant="caption" muted>
              {row.label}
            </Text>
            <Text variant="body">{row.value}</Text>
          </div>
        ))
      )}
    </RailSection>
  );
}

// ── Related Work / Evidence (link lists) ─────────────────────────────

export interface LinkRef {
  kind: string;
  id: string;
  label: string;
  // Pre-computed URL using the new global patterns; callers MUST
  // build URLs via `linkRefFor` (below) rather than constructing
  // ad-hoc strings, so no `/projects/...` path can leak in.
  url: string;
}

// Map an object reference onto its v0.6.2 URL pattern. Centralized so
// the FRONTEND_IMPLEMENTATION constraint "DO NOT construct any
// /projects/... URLs" stays enforced as we add new evidence kinds.
//
// Phase D.2 extension: as new kinds register (proposals, memory
// atoms, …), add them here. The fall-through returns null so the
// caller can render the row inert rather than emit a broken link.
export function urlForRef(kind: string, id: string): string | null {
  switch (kind) {
    case "conversation":
    case "topic":
    case "room":
    case "dm":
      return `/conversations/${id}`;
    case "node":
      return `/nodes/${id}`;
    case "decision":
      return `/decisions/${id}`;
    case "doc":
    case "document":
      return `/docs/${id}`;
    case "kb_item":
    case "kb-item":
      return `/kb-items/${id}`;
    case "scope":
    case "project":
      return `/scopes/${id}`;
    case "task":
      return `/tasks/${id}`;
    default:
      return null;
  }
}

export function linkRefFor(
  kind: string,
  id: string,
  label: string,
): LinkRef | null {
  const url = urlForRef(kind, id);
  if (!url) return null;
  return { kind, id, label, url };
}

export function RelatedWorkSection({ items }: { items: LinkRef[] }) {
  return (
    // TODO(i18n): shellV062.conversations.rightRail.relatedWork
    <RailSection title="Related work">
      <LinkRefList items={items} emptyCopy="Nothing related yet." />
    </RailSection>
  );
}

export function EvidenceSection({ items }: { items: LinkRef[] }) {
  return (
    // TODO(i18n): shellV062.conversations.rightRail.evidence
    <RailSection title="Evidence">
      <LinkRefList items={items} emptyCopy="No evidence cited yet." />
    </RailSection>
  );
}

function LinkRefList({
  items,
  emptyCopy,
}: {
  items: LinkRef[];
  emptyCopy: string;
}) {
  if (items.length === 0) {
    return (
      <Text variant="caption" muted>
        {emptyCopy}
      </Text>
    );
  }
  return (
    <ul
      style={{
        listStyle: "none",
        margin: 0,
        padding: 0,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      {items.map((it) => (
        <li
          key={`${it.kind}:${it.id}`}
          style={{ display: "flex", gap: 8, alignItems: "center" }}
        >
          <Tag tone="neutral">{it.kind}</Tag>
          <Link
            href={it.url}
            style={{
              color: "var(--wg-accent)",
              textDecoration: "none",
              fontSize: "var(--wg-fs-body)",
              fontFamily: "var(--wg-font-sans)",
            }}
          >
            {it.label}
          </Link>
        </li>
      ))}
    </ul>
  );
}

// ── AI Assistance (proposals only) ───────────────────────────────────

export interface AIAssistAction {
  id: string;
  label: string;
  // Surfaces in the DrawerHost as a proposal. Per DESIGN_LOCK.md
  // invariant #4 these never mutate state.
  proposal_type:
    | "routing_suggestion"
    | "task_candidate"
    | "document_draft"
    | "topic_suggestion"
    | "memory_candidate"
    | "impact_analysis"
    | "capability_explanation"
    | "topic_closure";
}

export function AIAssistanceSection({ actions }: { actions: AIAssistAction[] }) {
  const drawer = useDrawer();

  function openProposal(a: AIAssistAction) {
    // Per DESIGN_LOCK.md #4 + API_CONTRACT.md:
    //   AI Assistance must return proposals only.
    //   Actions mutate state.
    // The drawer body wires `POST /api/ai-assistance/run` (which
    // returns `mutates_state: false`) and renders the resulting
    // proposal — no state change happens here.
    // TODO(phase-d.2): real proposal drawer body. For now we reuse
    // the existing flow_request drawer slot as a placeholder so the
    // motion + chrome render.
    drawer.open({
      type: "flow_request",
      // TODO(i18n): shellV062.conversations.rightRail.aiAssistance.* title keys
      title: `Proposal: ${a.label}`,
      props: { proposal_id: a.id, proposal_type: a.proposal_type },
    });
  }

  return (
    // TODO(i18n): shellV062.conversations.rightRail.aiAssistance
    <RailSection title="AI Assistance">
      {actions.length === 0 ? (
        <Text variant="caption" muted>
          No suggestions right now.
        </Text>
      ) : (
        actions.map((a) => (
          <Button
            key={a.id}
            size="sm"
            variant="ghost"
            onClick={() => openProposal(a)}
            style={{ justifyContent: "flex-start" }}
          >
            {a.label}
          </Button>
        ))
      )}
      <Text variant="caption" muted style={{ marginTop: 4 }}>
        {/* TODO(i18n): shellV062.conversations.rightRail.aiAssistance.caveat */}
        Proposals only. Acceptance happens in the primary action below.
      </Text>
    </RailSection>
  );
}

// ── Primary Action (sticky bottom) ───────────────────────────────────

export function PrimaryActionFooter({
  label,
  disabled,
  onClick,
  hint,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  hint?: string;
}) {
  return (
    <div
      style={{
        position: "sticky",
        bottom: 0,
        background: "var(--wg-surface)",
        padding: 12,
        borderTop: "1px solid var(--wg-line)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginTop: "auto",
      }}
    >
      <Button variant="primary" onClick={onClick} disabled={disabled}>
        {label}
      </Button>
      {hint ? (
        <Text variant="caption" muted>
          {hint}
        </Text>
      ) : null}
    </div>
  );
}
